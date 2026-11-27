"""The call: one LiveKit voice session wiring speech <-> Queen.

LiveKit owns turn-taking, barge-in, echo handling and streaming. This file only picks the parts.
Every user and assistant turn, with LiveKit's own latency metrics, goes to logs/turns.jsonl.
"""
import asyncio
import contextlib
import json
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from livekit import rtc  # noqa: E402
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, JobRequest, RunContext, cli, function_tool, inference  # noqa: E402,E501
from livekit.agents.llm import ChatMessage, ToolError, ToolResult  # noqa: E402
from livekit.agents.voice import room_io  # noqa: E402
from livekit.plugins import silero  # noqa: E402

# Importing the plugin registers both inference runners, which LiveKit loads before registering the agent.
# An incomplete private cache must leave these optional runners out of this worker's startup entirely.
EnglishModel = MultilingualModel = None
if os.environ.get("STT") != "off":
    from core.downloads import snapshot  # noqa: E402
    try:
        snapshot("turn-en", check=True)
        snapshot("turn-multilingual", check=True)
    except (OSError, ValueError):
        pass
    else:
        from livekit.plugins.turn_detector.english import EnglishModel  # noqa: E402
        from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

from brain import feelings  # noqa: E402
from brain import prompts as ledger  # noqa: E402
from brain.queen import MIND_FAILED, Queen, Workers, _spoke, code_pieces, drafts, mind_silent_words, put_in_chat, queen_llm, speakable, unbroken, voice_only, written_call  # noqa: E402
from core import attachments, brain_trace, clock, jobs, life, relationship, schedules, state  # noqa: E402
from core import live as conversation  # noqa: E402
from core import page_sound  # noqa: E402
from core.downloads import voice_notice  # noqa: E402
from core.offloop import OrderedIO  # noqa: E402
from speech import live as live_voice  # noqa: E402
from speech import sounds  # noqa: E402
from speech.factory import stt, tts  # noqa: E402

TURNS = Path(os.environ.get("VX_TURNS") or ROOT / "logs" / "turns.jsonl")  # (a test run keeps its own: the Live view reads yours)
disk = OrderedIO()


def record(kind: str, **fields) -> None:
    fields = brain_trace.fields(fields)
    # Capture the event's time, context and values now, not when a slow disk gets to it.
    line = json.dumps({"t": round(time.time(), 3), "kind": kind, **fields}, default=str) + "\n"
    disk.submit(_record, line)


def _record(line: str) -> None:
    with state.closed_file(TURNS, "a") as f:  # (his alone from the start: core/state.py)
        f.write(line)


# LiveKit's own timing knobs, at their values here unless a profile line or a measurement run sets them (tests/call_test.py's
# speed, pauses, clauses and barge scenarios on the bench): the quiet after his voice before his words go to Whisper
# (VAD_SILENCE), the end-of-turn waits (TURN_MIN_DELAY, LiveKit's 0.5 s; TURN_MAX_DELAY, 1.5 s here, when the turn model is
# unsure) and how long his voice over hers must last to stop her (BARGE_IN_MIN, LiveKit's 0.5 s). Each is chosen by the
# bench's numbers and his own microphone, never by guess.
TIMING = {name: float(os.environ.get(name, default)) for name, default in
          (("VAD_SILENCE", "0.55"), ("TURN_MIN_DELAY", "0.5"), ("TURN_MAX_DELAY", "1.5"), ("BARGE_IN_MIN", "0.5"))}
# His words' timing for a turn whose reply will be drafted (Queen.drafting: her mind is asked at his words' transcript):
# they go to Whisper after 0.35 s of quiet, so her mind is asked about 0.2 s sooner, while his turn ends no sooner than
# 1.0 s after his last word, later than before, so she cuts in less (bench: "pauses" kept as 2 turns where the old
# timing made 6), and free, since her draft is already on its way. Each turn he starts gets one or the other
# (drafts_his_turn, time_his_words), so a turn with no draft (Wing, Listen, her backup answering, a result untold or being
# told, or one he starts while she speaks) keeps exactly the old timing and is never answered later than before.
# A draft thrown away at his turn's end (his last words differ, or her context changed) costs that turn the 0.17 s
# between the two waits. A profile's own VAD_SILENCE or TURN_MIN_DELAY line sets that value for every turn.
DRAFTED_TIMING = {name: float(os.environ.get(name, default)) for name, default in
                  (("VAD_SILENCE", "0.35"), ("TURN_MIN_DELAY", "1.0"))}
# LiveKit's own limits on drafts (preemptive generation), set on purpose: a turn of his up to 60 s is drafted (LiveKit's
# default 10 s left 3.2% of recorded call turns without one, 0.3% over 60 s), and up to 6 drafts in
# one turn (one each time he pauses 0.35 s or more and goes on; LiveKit's default 3; each one past the last is a paid
# request thrown away, counted on the bench: tests/timeline.drafts).
DRAFTING = {"enabled": drafts(), "max_speech_duration": 60.0, "max_retries": 6}


def drafts_his_turn(queen, speech) -> bool:
    """Whether the turn he starts now will be drafted: her side would draft it (Queen.drafting), and no reply of hers is
    under way (her current speech, `speech`). LiveKit drafts nothing while her current speech is on and not interrupted
    (agent_activity.on_preemptive_generation), and when he talks over her it pauses her speech first, so a turn he starts
    over her gets no draft at his words' transcript (bench: 3 of the 30 speed turns, each one he began while she
    spoke). Such a turn keeps the old timing."""
    under_way = speech is not None and not speech.interrupted and not speech.done()
    return queen.drafting() and not under_way


def time_his_words(drafted: bool, vad, session) -> dict:
    """His words' timing for the turn he is starting, by whether its reply will be drafted: Silero's quiet before Whisper
    hears them and LiveKit's least wait before his turn is over (both LiveKit's own live options). Which it gave."""
    use = {**TIMING, **DRAFTED_TIMING} if drafted else TIMING
    vad.update_options(min_silence_duration=use["VAD_SILENCE"])
    session.update_options(endpointing_opts={"min_delay": use["TURN_MIN_DELAY"]})
    return {"drafted": drafted, "vad_silence": use["VAD_SILENCE"], "min_delay": use["TURN_MIN_DELAY"]}


def prewarm(proc: JobProcess) -> None:
    if os.environ.get("STT") != "off":
        proc.userdata["vad"] = silero.VAD.load(min_silence_duration=TIMING["VAD_SILENCE"])
    feelings.init()


# Two spare processes, ready for the next conversation. LiveKit's production default keeps one per CPU core (gigabytes
# held on a large Mac, and ten seconds before she could take a call after every start).
# Her health page (127.0.0.1:AGENT_PORT, "OK" once LiveKit knows her) is what the call page waits for before it
# opens a room: a room opened before she registered never gets her. A personal agent takes every call:
# LiveKit's production default refuses new calls above 0.7 CPU load, which the local models alone can reach. Its load
# is hers, never this Mac's CPU: at 0.99 of the CPU, other apps on a busy Mac still locked her out (with the
# load average above the core count, three calls in a row were refused, "no servers available").
#
# Every open page is a conversation and holds one of her processes, typed or not (one conversation, one path):
# about 0.28 GB and 2% of one core while he types or leaves it open (measured), so a page counts as one of
# MOST_CONVERSATIONS, never as a call. Her calls are bounded where his microphone turns one on (set_voice, MOST_CALLS:
# core/live.take_call). LiveKit's server gives no room to a worker whose load is at or above its target load (0.7,
# agents.target_load's default, the same in every LiveKit config here: livekit-server pkg/service/agentservice.go
# JobRequestAffinity), so her load tops out at FULL, below it: at FULL the worker itself says full (load_threshold) and
# the page says so and asks again by itself (call/ui app/api/token: worker_load at FULL). Before, each open page
# counted 0.3 as a call: three open pages reached 0.9, so a fourth page, typed or a call, never got her
# ("no servers available (received 1 responses)").
FULL = 0.65  # (call/ui/app/api/token/ready.ts FULL_LOAD is the same)
MOST_CONVERSATIONS = max(1, int(os.environ.get("VX_MOST_CONVERSATIONS", "12")))
MOST_CALLS = max(1, int(os.environ.get("VX_MOST_CALLS", "3")))  # (talking at once: a fourth waits, typing, and is said so)


def share(conversations: int) -> float:
    """Her load with this many conversations open (or said yes to): FULL once MOST_CONVERSATIONS are, else below it by at
    least one conversation's share (exactly FULL, never a rounding either side of it)."""
    return FULL if conversations >= MOST_CONVERSATIONS else FULL * conversations / MOST_CONVERSATIONS


def her_load(server: AgentServer) -> float:
    """Her own load for LiveKit: her conversations open or starting (Her.held), as a share of MOST_CONVERSATIONS, up to
    FULL. The same number goes to LiveKit's server (its affinity), her own availability check and her worker page
    (/worker, which the call page reads: ready.ts), so a page is told full exactly when she would refuse it."""
    try:
        return share(server.held())
    except AttributeError:  # (not serving yet, or not her server: nothing open)
        return 0.0


class Her(AgentServer):
    """LiveKit's AgentServer, with one count changed: her conversations, each counted once, whether running or said yes
    to and not started yet. LiveKit's own estimate (agents/worker.py _get_effective_load) counts a room it said yes to as
    a running one's share, or, with none running, as load_threshold / num_idle_processes: right after every start (when
    every open page joins again at the same moment) only two pages got her and the rest waited for the page's 20 s
    timeout. A job is running (active_jobs) a moment before its room stops being reserved (worker.py: launch_job, then
    the request task's end), so a room said yes to is known by its job (joining: her_request) and counted once."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.joining: set[str] = set()  # (the jobs whose rooms she said yes to and whose request has not ended)

    def held(self) -> int:
        running = {info.job.id for info in self.active_jobs}
        return len(running) + max(0, self._reserved_slots - len(running & self.joining))

    def _get_effective_load(self) -> float:
        try:
            return share(self.held())
        except AttributeError:  # (another LiveKit: its own count; tests/capacity_test.py names the one this is for)
            return super()._get_effective_load()


async def her_request(request: JobRequest) -> None:
    """LiveKit's own answer to a room (accept), with its job known as joining until its request has ended: the same
    moment LiveKit stops reserving it (its done callback runs first, then this one, with nothing in between)."""
    server.joining.add(request.id)
    task = asyncio.current_task()
    if task is not None:
        task.add_done_callback(lambda _task: server.joining.discard(request.id))
    await request.accept()


server = Her(setup_fnc=prewarm, host="127.0.0.1", port=int(os.environ.get("AGENT_PORT", "8870")),
             load_threshold=FULL, load_fnc=her_load, num_idle_processes=1 if os.environ.get("SMALL_MAC_TIER") else 2)


def turn_model():
    choice = os.environ.get("TURN", "")
    if choice == "stt":
        return "stt"
    if choice == "audio":
        return inference.TurnDetector(version="v1-mini")
    if EnglishModel is None or MultilingualModel is None:
        return inference.TurnDetector(version="v1-mini")
    english = os.environ.get("STT_LANGUAGE", "en").startswith("en")
    try:  # its files come with ./vx setup (download-files); a Mac set up before this keeps the former model until then
        from huggingface_hub import hf_hub_download
        from livekit.plugins.turn_detector.models import HG_MODEL, MODEL_REVISIONS, ONNX_FILENAME
        wanted = "en" if english and os.environ.get("TURN_MODEL", "english") != "multilingual" else "multilingual"
        hf_hub_download(HG_MODEL, ONNX_FILENAME, subfolder="onnx", revision=MODEL_REVISIONS[wanted], local_files_only=True)
    except Exception:
        return inference.TurnDetector(version="v1-mini")
    # Which of LiveKit's two text turn models reads his words (TURN_MODEL, a measured A/B: english today). What commits a
    # turn at his thinking pause is this verdict: a half-sentence it calls finished waits only TURN_MIN_DELAY, so a longer
    # TURN_MAX_DELAY changed nothing (the bench's eot rows: "So I was thinking about." 0.10 to
    # 0.24 against 0.08). Offline on the bench's own calls the multilingual model held all 41 half-sentences and made
    # none of 39 whole ones wait (English: 40 of 41 answered); on recorded calls about even (14 against 12 of 28 cut turns
    # held, 1.8% against 1.6% of finished turns waiting); on a typed set worse (7.8% unfinished answered against
    # none). TURN_THRESHOLD overrides either threshold.
    if os.environ.get("TURN_MODEL", "english") == "multilingual" or not english:
        return MultilingualModel(**({"unlikely_threshold": float(os.environ["TURN_THRESHOLD"])} if os.environ.get("TURN_THRESHOLD")
                                    else {"unlikely_threshold": 0.03} if english else {}))
    # How sure it must be that you have finished. LiveKit's own 0.029 answered 6.5% of unfinished sentences here
    # ("So I was thinking about" scored 0.037 on a call); at 0.08 none, and 3.6% of finished ones wait the full
    # max_delay instead (measured on 250 finished and 230 unfinished sentences). TURN_THRESHOLD overrides.
    return EnglishModel(unlikely_threshold=float(os.environ.get("TURN_THRESHOLD", "0.08")))


class FilesTold:
    """Which files she offered in the conversation, for her page (its FileLink draws a link of hers as a file only for
    these, once it knows them: call/ui lib/offered-files.ts). The page's ask is the truth (answer: the whole set, from
    the record): it asks once it listens, after a reconnect, and whenever a link names an id it does not know, so a word
    of hers it missed heals itself. Her words are hints sent as they come: the whole set when she joins (whole), each new
    offer (tell), and before her words name a file it does not know of, the record read again and the whole set (named).
    Nothing is ever counted as delivered; the record is read again only for an id not in what it last read; a telling
    that fails is noted, never in the way of what she shows."""

    def __init__(self, send, note) -> None:
        self.send, self.note, self.known = send, note, set()

    async def _read(self) -> list[str]:
        ids = await asyncio.to_thread(attachments.offered)
        self.known = set(ids)
        return ids

    async def answer(self) -> str:  # (the page's ask, RPC "viv.files")
        ids = await self._read()
        self.note("files_asked", files=len(ids))
        return json.dumps(ids)

    async def whole(self) -> None:
        try:
            ids = await self._read()
        except Exception as e:  # noqa: BLE001 (the page asks for it)
            self.note("error", source="files told", error=f"{type(e).__name__}: {str(e)[:160]}")
            return
        await self.tell(ids, whole=True)

    async def tell(self, ids, whole: bool = False) -> None:
        try:
            await self.send(json.dumps({"ids": list(dict.fromkeys(ids)), "whole": whole}))
        except Exception as e:  # noqa: BLE001 (the page's ask heals it)
            self.note("error", source="files told", error=f"{type(e).__name__}: {str(e)[:160]}")

    async def named(self, ident: str) -> None:  # (her words name this file: the record read again only if unknown)
        if ident not in self.known:
            await self.whole()


def file_tools(room: str, channel, files: FilesTold, show, note):
    @function_tool()
    async def send_file(context: RunContext, path: str) -> ToolResult:
        """Give the user a file to download in this chat, on a call or while typing.

        Use this directly for an existing file with a known exact path, including an older send without an offer ID.

        Args:
            path: The full path the user or a Worker gave you. The file must already exist.
        """
        queen = getattr(getattr(context, "session", None), "current_agent", None)
        if isinstance(queen, Queen) and await queen.worker_offer("", context.speech_handle,
                                                                 str(Path(path).expanduser().absolute())):
            return ToolResult("The file is already available to download in this chat.", reply_required=not await _spoke(context))
        try:
            ref = await asyncio.to_thread(attachments.reference, path)
        except (OSError, ValueError) as error:
            raise ToolError(str(error)) from None
        if isinstance(queen, Queen) and await queen.worker_offer(ref["sha256"], context.speech_handle):
            return ToolResult("The file is already available to download in this chat.", reply_required=not await _spoke(context))
        return await present(context, ref, first=True)

    @function_tool(description=ledger.shipped("modes/resend_file"))
    async def resend_file(context: RunContext, offered_id: str) -> ToolResult:
        """Send an offered file again.

        Args:
            offered_id: The id of a file already offered in the conversation. Use it to send that exact file again.
        """
        try:
            ref, _ = await asyncio.to_thread(attachments.resendable_file, offered_id)
        except (OSError, ValueError) as error:
            raise ToolError(str(error)) from None
        return await present(context, ref)

    async def present(context: RunContext, ref: dict, first: bool = False) -> ToolResult:
        await show_file(ref, room, channel(), files, show, note, first=first)
        return ToolResult("The file is available to download in this chat.", reply_required=not await _spoke(context))

    return [send_file, resend_file]


async def show_file(ref: dict, room: str, channel: str, files: FilesTold, show, note, *, first: bool) -> None:
    link = attachments.link(ref)
    recorded = {}
    if first and "worker_result" in ref:
        recorded = await asyncio.to_thread(attachments.result_offers, [ref["worker_result"]])
    if recorded.get(ref["sha256"]) != ref:
        relationship.append("assistant", link, channel=channel, call_id=room, files=[ref] if first else None)
    files.known.add(ref["id"])
    await files.tell([ref["id"]])  # (before its link; a failure is noted, and its link still goes out)
    await show(link)
    note("file_offered", id=ref["id"], name=Path(ref["path"]).name)


def mac_participant(identity: str) -> bool:
    # The local token route assigns this prefix after checking the page's origin.
    return identity.startswith("voice_assistant_user_mac_")


async def show_worker_approval(participant, note, text: str, history: str, *, recipients: list[str],
                               native_request: str = "", approval: dict | None = None) -> None:
    """Display the approval as literal text and keep only its summary in the log."""
    if not recipients:
        return  # LiveKit would broadcast to the room.
    if native_request or approval:
        text = json.dumps({"text": text, "request": native_request, **({"approval": approval} if approval else {})})
    await participant.send_text(text, topic="lk.chat",
                                attributes={"viv.approval": "3" if approval else "2" if native_request else "1"},
                                destination_identities=recipients)
    note("shown", text=history)


@server.rtc_session(on_request=her_request)
async def call(ctx: JobContext) -> None:
    def note(kind: str, **fields) -> None:
        record(kind, room=ctx.room.name, **fields)

    async def said(text):  # what she actually speaks, logged per reply (telemetry)
        spoken = []
        async for piece in text:
            spoken.append(piece)
            yield piece
        speech = session.current_speech  # (which reply: the call tests match its sounds to its own audio)
        note("spoken", text="".join(spoken), speech=speech.id if speech is not None else None)

    files = FilesTold(lambda ids: ctx.room.local_participant.send_text(ids, topic="viv.files"), note)
    page_listening = asyncio.Event()

    async def show(text: str) -> None:  # put_in_chat: the call page's chat, never spoken
        for piece, code in code_pieces(text):  # (each file her words name outside code: her page knows it first)
            for found in () if code else attachments.FILE_TARGET.finditer(piece):
                await files.named(found.group(1))
        await ctx.room.local_participant.send_text(text, topic="lk.chat")
        note("shown", text=text)

    def approval_recipients() -> list[str]:
        return [p.identity for p in ctx.room.remote_participants.values()
                if mac_participant(p.identity) and p.connection_quality != rtc.ConnectionQuality.QUALITY_LOST]

    async def show_approval(remote: str, history: str, *, local_text: str, native_request: str, approval: dict) -> bool:
        if not approval_recipients():
            # A paired phone can deny, but never receives the private request or an Allow control.
            recipients = [p.identity for p in ctx.room.remote_participants.values()
                          if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT]
            instruction = "\nApprove in Viventium on this Mac." if "allow_once" in approval["choices"] else ""
            await show_worker_approval(ctx.room.local_participant, note,
                                       local_text + instruction, history,
                                       recipients=recipients,
                                       approval={**approval, "choices": ["reject_once"]})
            relationship.append("assistant", history, channel_now(), call_id=ctx.room.name)
            return False
        # A pending approval may be picked up as soon as the page joins.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(page_listening.wait(), 3)
        recipients = approval_recipients()
        if not recipients:
            return False
        await show_worker_approval(ctx.room.local_participant, note, local_text, history, recipients=recipients,
                                   native_request=native_request, approval=approval)
        relationship.append("assistant", history, channel_now(), call_id=ctx.room.name)
        return True

    async def download_file(request: rtc.RpcInvocationData) -> str:
        person = ctx.room.remote_participants.get(request.caller_identity)
        if person is None or person.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            raise rtc.RpcError(2000, "This download belongs to the current chat.")
        try:
            payload = json.loads(request.payload)
            identifier = payload["id"]
            request_id = payload.get("request_id", request.request_id)
            if not isinstance(request_id, str) or not request_id or len(request_id) > 64:
                raise ValueError("The download request is unavailable.")
            ref, content = await asyncio.to_thread(attachments.offered_file, identifier)
            name = Path(ref["path"]).name
            await ctx.room.local_participant.send_bytes(content, name=name, mime_type=mimetypes.guess_type(name)[0],
                                                         topic=f"viv.file.{identifier}",
                                                         attributes={"request_id": request_id},
                                                         destination_identities=[request.caller_identity])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise rtc.RpcError(2000, str(error) if isinstance(error, ValueError) else "The file is unavailable.") from None
        note("file_sent", id=identifier, name=name, request_id=request_id)
        return "complete"

    # One conversation, one room (the requirement: no "start call" step, no chat/call path separation). The page joins
    # with its text box open; his microphone on is a call, off is typing. LiveKit's own switch (AgentInput and
    # AgentOutput .set_audio_enabled) turns her hearing and her voice on and off inside this one session, so the
    # conversation, her context and her work carry over; her style, the channel and how she tells results follow
    # (set_voice, below). The same Queen, relationship, memory and Workers either way, each result told once.
    # on: her hearing and voice are on (his microphone is). greeted: she has greeted aloud in this room. opened: the
    # room's own opening (her greeting or quiet arrival) has begun, so a microphone turned on later greets by itself.
    voice = {"on": False, "greeted": False, "opened": False}

    def channel_now() -> str:
        return "call" if voice["on"] else "typed"

    async def offer_worker_file(ref: dict, _content: bytes) -> None:
        if not page_listening.is_set():
            raise ConnectionError("The page is not listening for file offers yet.")
        await show_file(ref, ctx.room.name, channel_now(), files, show, note, first=True)

    workers = Workers(record=note)

    def linked() -> str | None:  # the person her session listens to (LiveKit's room input), once it knows them
        with contextlib.suppress(Exception):
            person = session.room_io.linked_participant
            return person.identity if person is not None else None
        return None
    # The page's chat comes to the shared intake (core/attachments.Inbox): each message ordered and timed when it begins
    # to arrive, its files kept only from that person, then answered by typed(), one at a time, in that order.
    inbox = attachments.Inbox(ctx.room, channel_now(), owner=linked,
                              on_message=lambda words, sender: typed(session, words, sender))
    # Her ears and voice for when his microphone is on. A Mac whose voice parts are not set up still types with her: they
    # are made here, and if one cannot be, typing goes on and talking says plainly why it cannot start (set_voice).
    await asyncio.to_thread(live_voice.now)  # (the voice set now: this process may have started, prewarmed, before it was chosen)
    ears = mouth = None
    if os.environ.get("STT") != "off":
        try:
            ears, mouth = stt(), tts()
        except Exception as e:  # noqa: BLE001 (a missing address or key in the profile: typing must not depend on it)
            record("error", room=ctx.room.name, source="voice parts", error=f"{type(e).__name__}: {str(e)[:160]}")
    session = AgentSession(
        stt=ears, llm=queen_llm(record=note), tts=mouth, vad=ctx.proc.userdata.get("vad"),
        tools=[workers],
        tts_text_transforms=[sounds.unstaged, voice_only, said, "filter_markdown", speakable, "filter_emoji"],
        turn_handling={
            # Whether you have finished: LiveKit's text turn model, on this Mac's CPU, reading your words (it tells
            # "So I was thinking about" from a finished question; the audio one, v1-mini, scored both alike on
            # calls here, so most finished sentences waited the full max_delay). TURN=stt uses a
            # streaming STT's own end-of-turn (AssemblyAI); TURN=audio the former one. VAD barge-in.
            "turn_detection": turn_model() if os.environ.get("STT") != "off" else "manual",
            "interruption": {"mode": "vad", "min_duration": TIMING["BARGE_IN_MIN"]},
            # When the turn model is unsure the user is done, wait at most 1.5 s (default 3 s).
            "endpointing": {"min_delay": TIMING["TURN_MIN_DELAY"], "max_delay": TIMING["TURN_MAX_DELAY"]},
            # LiveKit's preemptive generation where her replies are drafted (drafts(): Hybrid): her mind starts at his
            # words' transcript, while the end of his turn is still judged; the draft carries the notes his turn gets and
            # is kept only when his turn asks exactly that (brain/queen.py Queen._draft, Queen._adopt), else LiveKit makes
            # the reply anew. Off for this Mac's model (a wasted request holds its one slot) and where TURN=stt.
            "preemptive_generation": DRAFTING,
        },
    )

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = ev.item
        if item.type == "message":
            speech = session.current_speech if item.role == "assistant" else None
            # (of his messages, his words and the file references only: what was read from a file is never logged)
            note("turn", id=item.id, role=item.role, channel=channel_now(), text=attachments.record_text(item) if item.role == "user" else item.text_content,
                 interrupted=item.interrupted, metrics=dict(item.metrics or {}), speech=speech.id if speech is not None else None,
                 **({"files": item.extra["files"]} if item.role == "user" and (getattr(item, "extra", None) or {}).get("files") else {}))
            # Her history is LiveKit's own transcript: her words. The sounds she made are heard, never shown back
            # to her (kept there, she copied her own laughs: brain/queen.py words_only).
            if queen.mode == "chat" and item.role == "assistant" and written_call(item.text_content, queen._tool_ids(), queen.his_words()):
                return  # (a tool call written as text was never shown: Queen.transcription_node; so never kept)
            # (the item's id is kept with it, and its row on the item: the one identity her memory changes a message by)
            # Persist before returning: memory tools, search and catch-up need this row immediately.
            text = unbroken(attachments.record_text(item) if item.role == "user" else item.text_content)
            row = relationship.append(item.role, text, channel=channel_now(), call_id=ctx.room.name,
                                      files=(getattr(item, "extra", None) or {}).get("files") if item.role == "user" else None,
                                      item=item.id)
            if row and isinstance(getattr(item, "extra", None), dict):
                item.extra.update({"memory_row": row, "memory_digest": life.row_ref(row)["digest"]})
            if (item.text_content or "").strip():
                worded["at"] = time.time()
                said_here["any"] = True
            # (Her Feelings react to their words in her Subconscious' round, once her answer is out: Emotional
            # reaction, brain/rounds.py, on its card's place.)

    @session.on("function_tools_executed")
    def _on_tools(ev) -> None:
        for call_, output in ev.zipped():
            note("tool", name=call_.name, call_id=call_.call_id, args=call_.arguments,
                 output=getattr(output, "output", None))

    @session.on("tool_execution_updated")
    def _on_tool_update(ev) -> None:  # started / progress (silent or spoken) / ended / reply status
        update = ev.update
        fields = update.model_dump(mode="json", exclude={"function_call"})
        if getattr(update, "function_call", None) is not None:
            fields["name"], fields["call_id"] = update.function_call.name, update.function_call.call_id
        note("tool_event", update=type(update).__name__, **fields)

    @session.on("speech_created")
    def _on_speech(ev) -> None:  # every reply, with its source; the analyzer links turns to it
        speech = ev.speech_handle
        alive()
        note("speech", id=speech.id, source=ev.source, user_initiated=ev.user_initiated)
        speech.add_done_callback(lambda s: note("speech_done", id=s.id, interrupted=s.interrupted,
                                                items=[item.id for item in s.chat_items]))
        if ev.user_initiated or ev.source == "generate_reply":
            begun = time.time()
            channel = channel_now()
            speech.add_done_callback(lambda s: turn_notice(s, begun, channel))

    def turn_notice(handle, begun: float, channel: str) -> None:
        if words := workers.worker_sign_in_notice(handle):
            failed_mind["streak"] = 0
            task = asyncio.create_task(tell_plain(words, "worker_sign_in_notice", channel))
            moving.add(task)
            task.add_done_callback(moving.discard)
        else:
            mind_silent(handle, begun)

    def mind_silent(handle, begun: float) -> None:
        """His turn got no words because her mind failed past its own retries (and her backup's): say so, once, in
        plain words on this channel, and keep it in the record. Decided by structure only: a mind error LiveKit marks
        unrecoverable during this reply, and no words of hers in it (a reply she chose not to give, in Wing or Listen
        only, has no such error, so it stays silent)."""
        if handle.interrupted or any(getattr(item, "type", "") == "message" and getattr(item, "role", "") == "assistant"
                                     and (item.text_content or "").strip() for item in handle.chat_items):
            failed_mind["streak"] = 0  # (she answered: a later failure is a first one again)
            return
        task = asyncio.create_task(tell_silent(handle, begun))
        moving.add(task)
        task.add_done_callback(moving.discard)

    async def tell_silent(handle, begun: float) -> None:
        await asyncio.sleep(0.5)  # (LiveKit's verdict on the failure can land just after the reply ends)
        if max(failed_mind["at"], MIND_FAILED["at"]) < begun:  # (its model's error, or a step given up: brain/queen.bounded)
            return
        failed_mind["streak"] = failed_mind.get("streak", 0) + 1  # (she answered in between: reset in mind_silent above)
        words = mind_silent_words(failed_mind["streak"], speech=handle)
        await tell_plain(words, "mind_silent", channel_now())

    async def tell_plain(words: str, source: str, channel: str) -> None:
        note(source, channel=channel)
        try:
            if channel == "call" and voice["on"]:
                session.say(words, add_to_chat_ctx=False)  # (said while talking; its words show as she says them)
            else:
                await show(words)  # (written while typing)
            relationship.append("assistant", words, channel=channel, call_id=ctx.room.name)
        except Exception as e:  # noqa: BLE001 (the notice itself must never take the conversation down)
            note("error", source=source, error=f"{type(e).__name__}: {str(e)[:160]}")

    @session.on("eot_prediction")
    def _on_eot(ev) -> None:
        note("eot", probability=round(ev.probability, 3), threshold=round(ev.threshold, 3), delay=round(ev.delay, 3))

    # LiveKit's own states, at its own times (telemetry), only where they tell something: his voice detected while hers
    # plays, and hers stopping (paused or cut) while he speaks: a barge-in (tests/timeline.barge_ins). A pause with no
    # words after it is a false interruption, and she resumes.
    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        if ev.new_state == "speaking" and voice["on"]:
            first = queen.first_speech
            if first is not None and not first.done():
                first.interrupt()  # also while the mind is still writing the first words
        if ev.new_state == "speaking" and session.agent_state == "speaking":
            note("state", who="user", old=ev.old_state, new=ev.new_state, at=round(ev.created_at, 3))
        if ev.new_state == "speaking" and voice["on"]:  # (each turn he starts: its timing, by whether it will be drafted)
            timed()

    timing_now = {"drafted": None}

    def timed() -> None:
        """His words' timing for the turn he starts now (time_his_words), set only when it changes, and kept in the turn
        log. Never in the call's way."""
        try:
            drafted = drafts_his_turn(queen, session.current_speech)
            if drafted != timing_now["drafted"]:
                timing_now["drafted"] = drafted
                note("timing", **time_his_words(drafted, ctx.proc.userdata["vad"], session))
        except Exception as e:  # noqa: BLE001
            note("error", source="timing", error=str(e)[:200])

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        if queen.first_speech is not None and session.current_speech is queen.first_speech and ev.new_state == "speaking":
            note("greeting_playout", speech=queen.first_speech.id, at=round(ev.created_at, 3))
        if ev.old_state == "speaking" and session.user_state == "speaking":
            note("state", who="agent", old=ev.old_state, new=ev.new_state, at=round(ev.created_at, 3))

    @session.on("agent_false_interruption")
    def _on_false_interruption(ev) -> None:
        note("false_interruption", resumed=ev.resumed, at=round(ev.created_at, 3))

    # Her mind's own clocks, one row per request (LiveKit's LLM plugin measures them at the provider's own stream, so a
    # hold of Light's in her reply's node never counts as the mind's): its first token, and how much of the prompt the
    # provider had cached (a stable prefix with this turn's notes last is cached). Linked to her reply by its speech.
    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        m = ev.metrics
        if getattr(m, "type", "") == "llm_metrics":
            note("llm", speech=m.speech_id, request=m.request_id, ttft=round(m.ttft, 3) if m.ttft >= 0 else None,
                 duration=round(m.duration, 3), prompt=m.prompt_tokens, cached=m.prompt_cached_tokens,
                 completion=m.completion_tokens, cancelled=m.cancelled,
                 model=getattr(m.metadata, "model_name", None) if m.metadata is not None else None)
        elif getattr(m, "type", "") == "tts_metrics" and queen.first_speech is not None and m.speech_id == queen.first_speech.id:
            note("greeting_tts", speech=m.speech_id, provider=getattr(m.metadata, "model_provider", None),
                 audio=round(m.audio_duration, 3), ttfb=round(m.ttfb, 3), cancelled=m.cancelled)

    # LiveKit 1.8.11 hands this verdict only to its hosted console, so none was recorded here before.
    # Passed on as the session event above; if LiveKit's internals move, the telemetry is skipped, nothing else.
    try:
        from livekit.agents.voice.agent_activity import AgentActivity
        if not getattr(AgentActivity, "_vx_eot", False):
            hosted = AgentActivity.on_eot_prediction

            def on_eot_prediction(self, ev):
                hosted(self, ev)
                self._session.emit("eot_prediction", ev)
            AgentActivity.on_eot_prediction, AgentActivity._vx_eot = on_eot_prediction, True
    except Exception:
        pass

    @ctx.room.on("connection_quality_changed")
    def _on_quality(participant, quality) -> None:  # (telemetry: what presence is judged on)
        note("quality", who=participant.identity[-8:], quality=rtc.ConnectionQuality(quality).name)
        if quality == rtc.ConnectionQuality.QUALITY_LOST and participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            queen.reowe()  # results told in the seconds before may have gone to a closed call: owed again

    failed_mind = {"at": 0.0}  # when her mind last failed past its own retries (LiveKit's own verdict: not recoverable)

    @session.on("error")
    def _on_error(ev) -> None:
        note("error", source=type(ev.source).__name__, error=str(ev.error))
        if type(ev.error).__name__ == "LLMError" and getattr(ev.error, "recoverable", True) is False:
            failed_mind["at"] = time.time()

    def _track(publication, participant) -> None:  # (telemetry: what a caller publishes; in a typed chat, nothing)
        note("track", track=rtc.TrackKind.Name(publication.kind), who=participant.identity[-8:])
    ctx.room.on("track_published", _track)

    async def next_greeting() -> None:
        # After hang-up: the next call's first line, written now by her own mind (brain/greeting.py), in its own
        # process for the same reason as the summary below.
        from brain import greeting

        greeting.soon()

    ctx.add_shutdown_callback(next_greeting)

    async def remember_call() -> None:
        # After hang-up: an episodic Life summary (Memory/Conversations), in its own process so the
        # job's shutdown timer can't cut it off.
        from core import helpers
        if helpers.available() and os.environ.get("LIFE"):
            with state.log_file("memory.log") as log:
                subprocess.Popen([sys.executable, "-m", "core.life", "summary", ctx.room.name], cwd=ROOT,
                                 stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)

    ctx.add_shutdown_callback(remember_call)
    note("call_start", one_path=True, timing={**TIMING, "turn_model": os.environ.get("TURN_MODEL", "english"),
                                              "turn_threshold": os.environ.get("TURN_THRESHOLD") or None,
                                              "drafts": DRAFTING, "drafted_timing": DRAFTED_TIMING})

    def alive() -> None:  # someone is talking with her now: heavy background model work and a settings restart
        def hold() -> None:
            if not voice.get("ended"):
                state.hold_call(ctx.room.name)
                if voice.get("ended"):  # hang-up may have released while this refresh was on disk
                    state.release_call(ctx.room.name)
        if not voice.get("ended"):
            disk.submit(hold)

    worded = {"at": 0.0}  # when the conversation last had words

    async def beat() -> None:
        """While his microphone is on, she is live from its first second to its last. While he types, the page can stay
        open in a tab for days, so she is live only around its turns (alive, above), and like a Telegram chat a pause of
        CHAT_PAUSE reaches Life: one summary of what was said since the last one (core/life.py marks it); what is left
        is summarised when the page is closed, as a call's is."""
        kept = 0.0
        while True:
            if voice["on"] or voice.get("deciding"):
                await disk.run(conversation.touch, ctx.room.name)  # (the menu bar sees this conversation open: core/live.py)
            else:  # (not talking, nothing being decided: no place held, even if a write that freed it had failed)
                told_menu(call=False)
            if voice["on"] or session.current_speech is not None:  # (a long answer is still a turn)
                alive()
            elif worded["at"] > kept and time.time() - worded["at"] > life.CHAT_PAUSE and not await asyncio.to_thread(state.call_live):
                kept = worded["at"]
                await remember_call()
            await asyncio.sleep(20)
    beating = asyncio.create_task(beat())

    async def ended() -> None:
        voice["ended"] = True
        beating.cancel()
        disk.close()  # stale status/telemetry is optional; it must not consume the SDK's shutdown budget
        state.release_call(ctx.room.name)  # (only its own: another page's call keeps her from a restart)
        conversation.gone(ctx.room.name)  # (this room's own status: another page's stays)
    ctx.add_shutdown_callback(ended)
    # Someone is there to hear her: an abrupt hang-up leaves the session open for a reconnect, and a
    # result said then would be lost (it stays owed until they are back, or for the next channel).
    # (Its connection quality goes LOST within seconds of a closed browser; the participant only
    # leaves the room when LiveKit's reconnect window ends, about 20 s later.)
    earlier = await asyncio.to_thread(relationship.recent)
    queen = Queen(history=earlier, call_id=ctx.room.name, record=note, show=show, show_approval=show_approval,
                  extra_tools=file_tools(ctx.room.name, channel_now, files, show, note), files=files.named,
                  offer_worker_file=offer_worker_file,
                  lookup_worker_files=workers.lookup_worker_files, workers=workers,
                  present=lambda: any(p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
                                      and p.connection_quality != rtc.ConnectionQuality.QUALITY_LOST
                                      for p in ctx.room.remote_participants.values()),
                  channel="typed", mode="chat")  # (until his microphone is on: set_voice)

    async def approval_settled(code: str, text: str) -> None:  # (said on that request's own card: the transcript)
        await ctx.room.local_participant.send_text(text, topic="lk.chat", attributes={"viv.approval.code": code})
        note("shown", text=text)
    queen.approval_settled = approval_settled

    async def typed(sess: AgentSession, words: ChatMessage, sender: str) -> None:  # typed on the page, while talking or not
        alive()                                                       # same per-turn notes as speech (LiveKit's own default, plus prepare)
        page_listening.set()
        async with sess._claim_user_turn():
            first = queen.first_speech
            if first is not None and not first.done():
                first.interrupt()  # the install greeting yields immediately, including its pending tour calls
            # Her reply in progress finishes deciding first (its hand-offs run), then the rest is cut: typed A
            # then B lost A's work when B cut her promise before its tool call came.
            speech = sess.current_speech
            if speech is not None and speech is not first and not speech.done():
                with contextlib.suppress(Exception):  # (LiveKit's own wait; none if nothing is generating)
                    await asyncio.wait_for(speech._wait_for_generation(), 10)
            await sess.interrupt()
            turn_ctx = queen.chat_ctx.copy()
            # (the runtime acts on his own words only, never on what a file says)
            text = attachments.said(words)
            approval_page = ctx.room.name if mac_participant(sender) else ""
            if reply := await workers.approval_reply(text, local_page=approval_page):
                _, code = workers.approval_choice(text)
                await ctx.room.local_participant.send_text(reply, topic="lk.chat",
                                                           attributes={"viv.approval.code": code})
                note("shown", text=reply)
                return
            await queen.prepare(turn_ctx, text, words.created_at, attended=True, turn_id=words.id)
            Queen.reply_to_turn(queen, sess, user_input=words, chat_ctx=turn_ctx)  # (one that fails to start ends its turn)

    # Talk, Wing or Listen only: talking starts the way the settings page says, and the page switches it live.
    # (While he types it is always a conversation: she answers what is typed to her.)

    def his_microphone() -> bool:
        """Whether the person she listens to (or, before LiveKit links one, anyone but an agent) has a microphone on in
        this room: a published microphone track that is not muted. Read from the room each time, never remembered."""
        who = linked()
        for person in ctx.room.remote_participants.values():
            if person.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT or (who and person.identity != who):
                continue
            if any(pub.source == rtc.TrackSource.SOURCE_MICROPHONE and not pub.muted
                   for pub in person.track_publications.values()):
                return True
        return False

    said_here = {"any": False}  # (anything said in this room yet: a first microphone on is then a call's opening)

    def can_tell() -> bool:  # talking in Talk with him there; typing only around his turns (core/jobs)
        if not voice["on"]:
            return time.time() - worded["at"] < 60
        return queen.call_mode == "talk" and queen.present()
    switching_voice = asyncio.Lock()

    async def set_voice(opening: bool = True) -> None:
        """His microphone decides, read now: on, she hears and speaks (a call: her voice style, Talk, Wing or Listen as
        the settings page says, she is live throughout); off, she hears nothing and writes (her chat style, live only
        around turns). A reply she is speaking when it goes off finishes aloud (a microphone muted for a cough is not a
        hang-up); her next ones are written unless it is back on. The same session, context, work and room either way."""
        async with switching_voice:
            voice["deciding"] = True
            try:
                await decide_voice(opening)
            finally:
                voice["deciding"] = False

    async def decide_voice(opening: bool) -> None:  # (set_voice's body, under its lock)
        on = his_microphone()
        if on != voice.get("mic", False):  # (his microphone, as it is: kept in the turn log whatever follows)
            voice["mic"] = on
            note("microphone", on=on, **({} if ears is not None and mouth is not None else {"voice_parts": False}))
            told_menu()  # (the menu bar's Ears is this microphone: core/live.py)
            if not on:
                voice["waits"] = False  # (a call that waited for a place: said again if he turns it on again)
        if on and (ears is None or mouth is None):  # (no voice parts here: typing goes on; said once per microphone)
            if not voice.get("told"):
                voice["told"] = True
                await show("Talking needs this Mac's voice parts, and they are not set up yet. Typing works.")
            return
        voice["told"] = False
        if on and (notice := await asyncio.to_thread(voice_notice)) and notice != voice.get("download_notice"):
            voice["download_notice"] = notice
            await show(notice)
        if on == voice["on"]:
            return
        # At most MOST_CALLS rooms talk at once on this Mac (core/live.take_call): one more waits, typing still works,
        # and is told so once; it starts talking by itself as soon as a place is free (wait_to_talk), while his
        # microphone stays on.
        if on and not await place_to_talk():
            if not voice.get("waiting"):  # (first: asking again never depends on the notice below arriving)
                voice["waiting"] = True
                later = asyncio.create_task(wait_to_talk())
                moving.add(later)
                later.add_done_callback(moving.discard)
            if not voice.get("waits"):
                voice["waits"] = True
                note("call_waits", most=MOST_CALLS)
                with contextlib.suppress(Exception):  # (a notice that cannot be sent now: the call still waits)
                    await show(f"Viventium is already talking in {MOST_CALLS} other conversations on this Mac. "
                               "Talking here starts by itself when one of them ends; typing works now.")
            return
        voice["on"] = on
        told_menu(call=on)  # (a call now, or not: its place among the calls at once is kept or freed)
        session.input.set_audio_enabled(on)
        speaking = session.current_speech
        if speaking is None or speaking.done():
            session.output.set_audio_enabled(on)
        else:
            # A reply in progress keeps its way out: one she is speaking finishes aloud when his microphone goes off
            # (a cough is not a hang-up), and one she is writing finishes as text when it comes on (turning her voice on
            # mid-reply would hold the rest of its text for audio that never comes). Her next replies follow.
            async def output_after(handle) -> None:
                with contextlib.suppress(Exception):
                    await handle
                session.output.set_audio_enabled(voice["on"])
            later = asyncio.create_task(output_after(speaking))
            moving.add(later)
            later.add_done_callback(moving.discard)
        queen.mode, queen.channel = ("call", "call") if on else ("chat", "typed")
        inbox.channel = queen.channel
        if on:
            if await asyncio.to_thread(live_voice.now):  # (a voice chosen since her voice was made: the one she speaks with now)
                with contextlib.suppress(Exception):
                    queen.update_options(tts=tts())
            if "mode_read" not in voice:  # (the settings page's choice on the first microphone in this room; after
                voice["mode_read"] = True  # that, what he switched to on the page stays, through a mute and back)
                queen.call_mode = await asyncio.to_thread(state.setting, "call_mode", "talk")
        await queen.update_instructions(await asyncio.to_thread(queen._compose_instructions))
        await queen.update_tools(([put_in_chat] if on else [])
                                 + [t for t in queen.tools if getattr(t, "id", None) != "put_in_chat"])
        note("voice_on" if on else "voice_off")
        if on:
            note("mode", mode=queen.call_mode)
            timed()  # (his first words' timing, before he speaks)
            if can_tell():
                jobs.here(channel_now())
            if opening and voice["opened"] and not voice["greeted"] and not said_here["any"] and queen.first_speech is None:
                voice["greeted"] = True  # nothing said yet: it opens as a call does, once
                await queen.greet([], [])

    moving: set[asyncio.Task] = set()

    async def place_to_talk() -> bool:
        """Whether this room may talk now (core/live.take_call: at most MOST_CALLS at once). A place check that fails
        (its files cannot be read or written) lets the call on and says so in the log: the limit guards this Mac, and a
        broken check must not take her voice away from a call that has its place."""
        try:
            return await disk.run(conversation.take_call, ctx.room.name, await mode_now(), MOST_CALLS)
        except Exception as e:  # noqa: BLE001
            note("error", source="call place", error=f"{type(e).__name__}: {str(e)[:160]}")
            return True

    async def wait_to_talk() -> None:  # a call waiting for a place: asked again every few seconds while his microphone is on
        try:
            while voice.get("mic") and not voice["on"]:
                await asyncio.sleep(3)
                try:
                    await set_voice()
                except Exception as e:  # noqa: BLE001 (one failed look: the next one, 3 s later)
                    note("error", source="call waits", error=f"{type(e).__name__}: {str(e)[:160]}")
        finally:
            voice["waiting"] = False

    def microphone_moved(*_args) -> None:
        task = asyncio.create_task(set_voice())
        moving.add(task)
        task.add_done_callback(moving.discard)

    async def switch(reader) -> None:
        await switch_to((await reader.read_all()).strip())

    async def switch_to(mode: str) -> bool:  # Talk, Wing or Listen only, now (the page's switch, or the menu bar's)
        if mode not in ("talk", "wing", "listen") or mode == queen.call_mode:
            return False
        queen.call_mode = mode
        voice["mode_read"] = True  # (chosen for this room now: a microphone turned on later keeps it)
        note("mode", mode=mode)
        told_menu()
        if mode == "listen":  # she stops speaking at once
            with contextlib.suppress(Exception):
                await session.interrupt()
        return True

    async def mode_now() -> str:  # how she is on this conversation's call: chosen for this room, else what Settings says
        return queen.call_mode if "mode_read" in voice else await asyncio.to_thread(state.setting, "call_mode", "talk")

    def told_menu(call: bool | None = None) -> None:  # the menu bar sees the open conversation as it is (core/live.py): his
        # microphone, the mode. Whether it holds a call's place is written only from what was decided (call: set_voice, when
        # she starts or stops talking); any other status keeps it as it is (core/live.write), so a mode change while a
        # place is being asked for neither gives back one just given nor claims one never given.
        ears_now = voice.get("mic", False)
        mode = queen.call_mode if "mode_read" in voice else None

        def write() -> None:
            with contextlib.suppress(OSError):
                conversation.write(ctx.room.name, ears_now, mode if mode is not None else state.setting("call_mode", "talk"), call=call)
        disk.submit(write)

    async def menu_asked(told: dict) -> None:
        """The menu bar (or Settings) changed what the open conversation follows (core/live.py): the mode now, and the
        page told what it does itself (its microphone, the mode it shows, how she is shown) on the room's text stream."""
        if "mode" in told:
            if told["mode"] in ("talk", "wing", "listen"):
                # (already so here, the page is still told: it can show another, e.g. Listen only saved and a typed-only
                # page, then Talk from the menu bar)
                await switch_to(told["mode"])
                voice["mode_read"] = True
            else:
                told = {k: v for k, v in told.items() if k != "mode"}
        if told:
            with contextlib.suppress(Exception):
                await ctx.room.local_participant.send_text(json.dumps(told), topic="viv.live")
    switching: set[asyncio.Task] = set()

    def on_mode(reader, _who) -> None:
        task = asyncio.create_task(switch(reader))
        switching.add(task)
        task.add_done_callback(switching.discard)
    ctx.room.register_text_stream_handler("viv.mode", on_mode)

    async def voice_changed(values: dict) -> None:  # chosen on the settings page meanwhile: her next spoken words
        try:
            queen.update_options(tts=tts())  # (LiveKit swaps it in the live pipeline)
            await queen.update_instructions(await asyncio.to_thread(queen._compose_instructions))  # (her new voice's own tags, and its name)
            note("voice", tts=values.get("TTS", ""), voice=values.get("TTS_VOICE", ""))
            if voice["on"] and (notice := await asyncio.to_thread(voice_notice)) and notice != voice.get("download_notice"):
                voice["download_notice"] = notice
                await show(notice)
        except Exception as e:  # noqa: BLE001 (a voice that cannot be made: said in the log, the next change still applies)
            note("error", source="voice change", error=f"{type(e).__name__}: {str(e)[:160]}")
    voicing = asyncio.create_task(live_voice.follow(voice_changed))

    async def stop_voicing() -> None:
        voicing.cancel()
    ctx.add_shutdown_callback(stop_voicing)

    def transcript_ready(_reader, identity: str) -> None:
        if identity == linked():
            page_listening.set()

    ctx.room.register_text_stream_handler("viv.transcript-ready", transcript_ready)
    sound_on = asyncio.Event()  # (the page said her voice can be heard there now: core/page_sound.py)

    def sound_told(_reader, identity: str) -> None:
        if identity == linked():
            sound_on.set()

    ctx.room.register_text_stream_handler("viv.sound", sound_told)
    session.input.set_audio_enabled(False)  # (typing until his microphone is on: set_voice, once started, below; set
    session.output.set_audio_enabled(False)  # before the room is attached, so nothing is heard or said meanwhile)
    await session.start(room=ctx.room, agent=queen, room_options=room_io.RoomOptions(
        text_input=False))  # (his typed messages come through the intake above, in the order he sent them)
    # His microphone, from now on: listened to only once she has started, then read as it is (a microphone turned on while
    # she was starting is found here, not lost to a switch made before her hearing and voice existed).
    for event in ("track_published", "track_unpublished", "track_muted", "track_unmuted",
                  "participant_connected", "participant_disconnected"):
        ctx.room.on(event, microphone_moved)
    await set_voice(opening=False)  # (a microphone already on: the greeting below opens it as a call)
    told_menu()
    following = asyncio.create_task(conversation.follow(menu_asked, ctx.room.name, opened=time.time()))

    async def stop_following() -> None:
        following.cancel()
    ctx.add_shutdown_callback(stop_following)
    ctx.room.local_participant.register_rpc_method("viv.file.download", download_file)

    async def files_asked(request: rtc.RpcInvocationData) -> str:  # (the page's ask, once it listens: FilesTold)
        person = ctx.room.remote_participants.get(request.caller_identity)
        if person is None or person.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            raise rtc.RpcError(2000, "This belongs to the current chat.")
        page_listening.set()
        try:
            return await files.answer()
        except Exception as e:  # noqa: BLE001 (the page asks again)
            raise rtc.RpcError(2000, "The files are not known yet.") from e
    ctx.room.local_participant.register_rpc_method("viv.files", files_asked)
    for person in ctx.room.remote_participants.values():  # (what was published before she joined)
        for publication in person.track_publications.values():
            _track(publication, person)
    def _on_page(item: dict) -> dict:
        """One message as the typed chat shows it: every word (relationship.full: a message carried in part to her
        context is whole on the page, which costs no model context), and the files he sent as chips: never a path,
        never what was read from them."""
        text = relationship.full(item)
        return {"t": item["t"], "role": item["role"],
                "text": "" if item.get("files") and text == attachments.reference_text(item["files"]) else text,
                **({"files": [{"name": f.get("name", ""), "type": f.get("type", ""), "bytes": f.get("bytes", 0)}
                              for f in item["files"]]} if item["role"] == "user" and item.get("files") else {})}

    # LiveKit can send before React has subscribed to chat. In particular, resettling a
    # saved text receipt can offer its file immediately and finish the durable job.
    # Give the page time to subscribe, but let the conversation start if its signal
    # never arrives. Only file offers must keep waiting (offer_worker_file).
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(page_listening.wait(), 6)
    note("page_ready", listening=page_listening.is_set())
    await files.whole()  # (which files she offered, before what the page shows: FilesTold)
    # The page opens on the last of the one conversation, from any channel, exactly as she remembers it.
    with contextlib.suppress(Exception):  # (only a courtesy: the conversation works without it)
        await ctx.room.local_participant.send_text(json.dumps(
            [_on_page(item) for item in earlier if item.get("role") in ("user", "assistant")]), topic="viv.history")

    if can_tell():
        jobs.here(channel_now())  # (Telegram leaves what nobody owns to this conversation from now on)
    try:  # work from earlier calls: results to tell now, Workers still running
        ready, running = await workers.resume(queen, page_approvals=bool(approval_recipients()))
    except Exception as e:  # xPerfect unreachable: the call still works, without old results
        note("error", source="resume", error=str(e))
        ready, running = [], []
    voice["opened"] = True  # (from here a microphone turned on with nothing said greets by itself: set_voice)
    async def ask_sound() -> str:  # (the page's real try at playing her track: "on" or "off", core/page_sound.py)
        page = linked()
        if page is None:
            raise ConnectionError("No page has joined this room yet.")
        return await ctx.room.local_participant.perform_rpc(destination_identity=page, method="viv.sound", payload="",
                                                            response_timeout=4.0)

    def quiet() -> bool:  # (nobody has said anything here yet, and she is not speaking)
        return not said_here["any"] and session.user_state != "speaking" and session.current_speech is None

    async def first_hello(setup: dict) -> None:
        """Her first greeting, once its sound can be heard (core/page_sound.py): the setup is only looked at until she
        speaks, then claimed, so a page closed while she waits leaves the whole greeting for the next room."""
        from core import chatgpt_sign_in, grok_sign_in

        if not quiet():
            return
        # The bounded startup wait above also gives the first greeting time to mount.
        note("greeting_ready", transcript=page_listening.is_set())
        if not setup.get("mac_name") and ("Grok subscription" in setup.get("connected", []) or os.environ.get("QUEEN") == "xai_plan"):
            setup["profile_name"] = await asyncio.to_thread(grok_sign_in.profile_name)
        if not setup.get("mac_name") and os.environ.get("QUEEN") == "chatgpt_plan":
            setup["profile_name"] = (await asyncio.to_thread(chatgpt_sign_in.connection.status)).get("name")
        speak = mouth is not None and await mode_now() == "talk"
        if speak:  # (a written greeting needs no sound)
            heard = await page_sound.page_sound(ask_sound, sound_on, lambda: not quiet(), note)
            note("greeting_sound", answer=heard)
            if heard == "said":
                return  # (they went first: she follows their lead, as when they address her before her hello)
            speak = mouth is not None and await mode_now() == "talk"  # (as it is now, after the wait)
        if not quiet() or await asyncio.to_thread(conversation.first_conversation) is None:  # claimed now, once
            return
        setup["voice_controls"] = ears is not None and mouth is not None
        session.output.set_audio_enabled(speak)
        opening = queen.first_greeting(setup, voice=speak, tour=not (state.logs() / "menubar.off").exists())

        def finished(speech):
            session.output.set_audio_enabled(voice["on"])
            note("greeting_finished", speech=speech.id, interrupted=speech.interrupted)

        opening.add_done_callback(finished)

    setup = conversation.first_conversation(claim=False)
    first = setup is not None and quiet()
    if voice["on"] or first:  # (her first hello opens this room too, even while it waits for sound: a microphone
        voice["greeted"] = True  # turned on meanwhile does not greet over it)
    if first:
        hello = asyncio.create_task(first_hello(setup))

        async def stop_hello() -> None:
            hello.cancel()
        ctx.add_shutdown_callback(stop_hello)
    await queen.greet(ready, running, already_opened=setup is not None or said_here["any"])

    async def keep_telling() -> None:
        """Every 20 s while she can tell here: this channel says so, takes the results nobody owns (core/jobs.claim: a
        talking call before a typed chat before Telegram; one asked to be told elsewhere goes there), and the clock's
        moments for the channel he is on (core/clock), the same shared path as Telegram's."""
        while True:
            await asyncio.sleep(20)
            try:
                here, local_page = can_tell(), bool(approval_recipients())
                if here:
                    jobs.here(channel_now())
                else:
                    jobs.gone()
                    if not local_page:
                        continue
                ready, running = await workers.resume(queen, page_approvals=local_page, approvals_only=not here)
                if not here:
                    continue
                await queen._running(running)
                for job, result in ready:
                    queen.tell(job, result)
                if hasattr(clock, "wake_due"):
                    await clock.wake_due_async(queen, channel_now())
            except Exception as e:  # noqa: BLE001 (never in the call's way)
                note("error", source="telling", error=str(e)[:200])
    telling = asyncio.create_task(keep_telling())

    async def stop_telling() -> None:  # hung up: what this channel took and did not finish goes elsewhere at once
        telling.cancel()
        jobs.gone()
        if hasattr(schedules, "release"):  # (its moments too: core/schedules)
            for kind in ("call", "typed"):  # (what it claimed while talking and while typing)
                schedules.release(kind, os.getpid())
    ctx.add_shutdown_callback(stop_telling)


if __name__ == "__main__":
    cli.run_app(server)
