"""Telegram: the same Viventium by text and voice notes (Core connector, channel "telegram").

Long-polls the Bot API (no webhook, no server) and serves only its owner, paired from Settings on the Mac
(state/core/telegram.json). Every message goes through the same Queen as calls: one
relationship, Life, Feelings and Workers. Everything she says is a message: replies, Worker results,
scheduled moments. A reply is one message unless a {MSG_BREAK} line splits it (main's rule), a voice note gets a voice note
back, and her no_reply is silence. This always-on process is also the clock for schedules and the home of
Worker results whose call hung up.

    .venv/bin/python chat/telegram.py       (./vx up starts it when a bot token is set)
"""
import asyncio
import contextlib
import re
import datetime as dt
from itertools import groupby
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import aiohttp
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from livekit.agents import AgentSession  # noqa: E402

from brain import feelings  # noqa: E402
from brain import prompts as ledger  # noqa: E402
from brain import queen as bq  # noqa: E402
from brain.queen import (Queen, Receipt, Workers, _presented, _spoke, queen_llm, speakable, unbroken,  # noqa: E402
                         voice_controls, voice_only, words_only, written_call, segments, WRAPPING)
from chat.telegram_html import LINK, markdown_to_html, quoted_fences  # noqa: E402
from livekit.agents import RunContext, function_tool  # noqa: E402
from livekit.agents.llm import ToolError, ToolResult  # noqa: E402
from livekit.agents.voice.transcription.filters import filter_emoji, filter_markdown  # noqa: E402
from core import attachments, clock, helpers, jobs, life, relationship, schedules, telegram_approvals, tooltrace  # noqa: E402
from core.state import STATE_ROOT, call_live, closed_file, log_file, setting  # noqa: E402
from speech import sounds  # noqa: E402
from speech import live as live_voice  # noqa: E402
from speech.factory import stt, tts  # noqa: E402

CHANNEL = "telegram"
OWNER = telegram_approvals.OWNER
INBOX = STATE_ROOT / "core" / "telegram-inbox.json"  # messages taken from Telegram, until answered
OUTBOX = STATE_ROOT / "core" / "telegram-outbox.json"  # each message she sends, until Telegram has it (or refused it)
RETRY_FOR = 900.0  # s a message that cannot have reached Telegram is tried again, with the same words
BACKOFF = (2.0, 60.0)  # s before the next try of such a message: the first wait, doubling, and the longest
TURNS = Path(os.environ.get("VX_TURNS") or ROOT / "logs" / "turns.jsonl")  # (a test run keeps its own: the Live view reads yours)
GATHER = 1.5  # s: messages that arrive this close together are answered as one turn
ANSWER_WAIT, ANSWER_LATE, ANSWER_RETRY = 300, 30, 5
ANSWER_INTERRUPT = 6  # the LiveKit handle normally ends within five seconds of a forced interrupt
INBOX_SPEECH = "_speech"  # the saved reply attempt, or a LiveKit speech id from an older inbox
INBOX_RETRY = "_retry_batch"
KEEP_AGAIN = 5.0  # s before a message that could not be kept (a full disk) is tried again, the poll held meanwhile
TOLD = "_told"  # (on a message kept in the inbox: he has been told of its file that did not arrive, _answer)
STATUS_EVERY = 4.5  # s between "typing…" signs: Telegram shows one for about 5 s
CHAT_PAUSE = life.CHAT_PAUSE  # s: a chat quiet this long is summarized into Life memory (the page's typed chat too)
# The voice switch, the one gate for her voice on Telegram (the requirement: on by default; the settings
# page's Channels shows it): on, a voice note of his gets a voice note back; off, every reply is text and she sends no
# voice note. Read at each message, so a change takes effect without a restart.
VOICE_SWITCH = "telegram_voice"
# A voice note with no words in it, and nothing else with it: this plain notice, and no thought or voice of hers.
NO_WORDS = "I couldn't hear any words in that voice note."


def voice_on() -> bool:
    """Whether the voice switch lets her speak on Telegram (on unless he turned it off)."""
    return setting(VOICE_SWITCH, True) is not False
log = logging.getLogger("telegram")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry the bot token in the URL


def note(kind: str, **fields) -> None:  # same telemetry as calls (logs/turns.jsonl), room "telegram"
    from core import brain_trace
    fields = brain_trace.fields(fields)
    try:
        with closed_file(TURNS, "a") as f:  # (his alone from the start: core/state.py)
            f.write(json.dumps({"t": round(time.time(), 3), "kind": kind, "room": CHANNEL, **fields}, default=str) + "\n")
    except OSError as error:
        log.warning("Telegram telemetry could not be written (%s)", type(error).__name__)


WAITS = (1, 2, 4, 8, 16)  # s between tries of a request that may pass: a message out (send) and a file in (download)
# All the time the files of one turn of his may take to arrive, tries and waits together: a network that hangs instead
# of failing would otherwise hold his next words for minutes (each request may wait 70 s; an album is ten files), and
# she is fast first. The files of one turn share it (Telegram._answer sets Bot.receive_by).
RECEIVE_WITHIN = 60.0
DOCUMENTS_WITHIN = 60.0  # one deadline for each batch, on a separate task from words


class NotReceived(Exception):
    """A file of his that did not arrive: why, how many tries it took, and whether Telegram itself refused it (a
    refusal said twice is final; anything else was a failure that did not pass in time)."""

    def __init__(self, why: str, tries: int, refused: bool = False) -> None:
        super().__init__(why)
        self.tries, self.refused = tries, refused


class Received(bytes):
    """A file's bytes, as they arrived, with how many tries that took."""
    tries = 1


class TelegramError(RuntimeError):
    """Telegram's own error answer to a request, with its error code (its HTTP status when it gave none): what is done
    about it is decided by that code, never by the wording of its description."""

    def __init__(self, why: str, code: int) -> None:
        super().__init__(why)
        self.code = code


def passes(error: BaseException) -> bool:
    """Whether Telegram's error answer may pass if asked again: its server error or its rate limit (by its code)."""
    code = getattr(error, "code", 0) or 0
    return code == 429 or code >= 500


POLL_AGAIN = 3.0  # s before polling again after a failed poll (no connection, another poller, an outage page)
SEND_WITHIN = 70.0  # s total, including pool/handshake waits: Forget waits at most an in-flight request's time


class Bot:
    def __init__(self, token: str) -> None:
        self.id = token.partition(":")[0]
        self.http = httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{token}/", timeout=70)
        self.files = f"https://api.telegram.org/file/bot{token}/"
        self.pause = asyncio.sleep  # (a test records the waits instead of sleeping them)
        self.clock = time.monotonic  # (and gives its own time)
        self.receive_by = None  # (when the files of the turn being read must have arrived: set by the channel)
        self._token = token  # (its address carries it: never in a reason told to her, a log or the turn log)

    async def call(self, method: str, files=None, **params):
        """One request; Telegram's error answer raises TelegramError, with its code. An answer that is not Telegram's
        JSON (a proxy, an outage page) raises ValueError."""
        authorize = getattr(self, "authorize", None) if "chat_id" in params else None
        try:
            async with asyncio.timeout(SEND_WITHIN if authorize else None), \
                    telegram_approvals.sending(OWNER) if authorize else contextlib.nullcontext():
                # Every attempt, under the lease: revoke/transfer cannot finish until this request ends.
                if authorize and not authorize(params["chat_id"]):
                    raise TelegramError("This chat is not paired.", 403)
                response = await (self.http.post(method, data=params, files=files) if files
                                  else self.http.post(method, json=params))
        except TimeoutError:
            # It may have reached Telegram. Keep the existing unknown-delivery rule; never repeat it.
            raise httpx.WriteTimeout("Telegram request did not finish in time") from None
        body = response.json()
        if not isinstance(body, dict):  # (JSON, but not Telegram's answer)
            raise ValueError(f"Telegram {method}: not Telegram's answer ({response.status_code})")
        if not body.get("ok"):
            code = body.get("error_code")
            raise TelegramError(f"Telegram {method}: {body.get('description')}",
                                code if isinstance(code, int) else response.status_code)
        return body["result"]

    async def send(self, method: str, files=None, **params):
        """A message out. Retried only when it cannot have arrived (no connection, or Telegram's rate
        limit, by its code), so nothing is sent twice; any other failure is raised to the sender."""
        for wait in WAITS:
            try:
                return await self.call(method, files=files, **params)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                why = type(e).__name__
            except RuntimeError as e:
                if getattr(e, "code", 0) != 429:
                    raise
                why = "rate limited"
            log.warning("%s not sent yet (%s); trying again in %s s", method, why, wait)
            await asyncio.sleep(wait)
        return await self.call(method, files=files, **params)

    async def updates(self):
        offset = None
        while True:
            try:
                batch = await self.call("getUpdates", timeout=50, allowed_updates=["message"],
                                        **({"offset": offset} if offset else {}))
            except (httpx.HTTPError, RuntimeError, ValueError) as e:  # network blip, another poller (409), an outage page
                log.warning("getUpdates: %s", e)
                await asyncio.sleep(POLL_AGAIN)
                continue
            for update in batch:
                offset = update["update_id"] + 1
                yield update

    async def download(self, file_id: str, *, expected_size: int = 0) -> Received:
        """A file he sent. Reading from Telegram is safe to repeat, so any failure is tried again with the waits a
        message out uses, within the time of his turn: no connection, a lost or unreadable answer, Telegram's server
        error or rate limit, a byte count that differs from Telegram's file size. A refusal (any other error status) is asked
        once more, and is final only when Telegram says it again: decided by what happened, never by the wording of
        Telegram's message, which goes to her as Telegram wrote it. An error answer is never taken for his file.
        Raises NotReceived, with the tries it took."""
        tries, why, refusals = 0, "", 0
        deadline = min(self.clock() + RECEIVE_WITHIN, self.receive_by or float("inf"))
        for wait in (*WAITS, None):
            left = deadline - self.clock()
            if left <= 0:
                break
            tries += 1
            try:
                data = Received(await asyncio.wait_for(self._fetch(file_id, expected_size), left))
                data.tries = tries
                return data
            except NotReceived as e:
                why = self._clean(str(e))
                refusals += e.refused
                if refusals >= 2:  # (said twice: Telegram means it)
                    raise NotReceived(why, tries, refused=True) from None
            except asyncio.TimeoutError:  # (the time for this file ran out while Telegram had not answered)
                why = "Telegram did not answer in time"
            except httpx.HTTPError as e:  # (no connection, a timeout, an answer cut off or unreadable on the way)
                why = type(e).__name__  # (its kind only: an error's own text can carry the file's address, and the token)
            if wait is None or wait >= deadline - self.clock():
                break
            log.warning("file not received yet (%s); trying again in %s s", why, wait)
            await self.pause(wait)
        raise NotReceived(f"{why or 'no time left to ask Telegram'}, {tries} tries", tries)

    def _clean(self, why: str) -> str:
        """A reason without the bot's token, whatever error text carried the file's address."""
        return why.replace(self._token, "(token)") if self._token else why

    async def _fetch(self, file_id: str, expected_size: int) -> bytes:
        """One try: check the file bytes against every size Telegram gave us."""
        response = await self.http.post("getFile", json={"file_id": file_id})
        self._answered(response, "where the file is")
        try:
            body = response.json()
        except ValueError:  # (an answer that was not Telegram's JSON: a proxy, an outage page)
            raise NotReceived("no answer from Telegram", 0) from None
        if not isinstance(body, dict):
            raise NotReceived("no answer from Telegram", 0)
        if not body.get("ok"):
            raise NotReceived(f"Telegram refused it ({body.get('description')})", 0, refused=True)
        found = body.get("result") if isinstance(body.get("result"), dict) else {}
        if not found.get("file_path"):  # (an answer with no file in it: not his file, and it may pass)
            raise NotReceived("Telegram's answer had no file in it", 0)
        response = await self.http.get(self.files + found["file_path"])
        self._answered(response, "the file")
        for size in (expected_size, found.get("file_size")):
            if isinstance(size, int) and size > 0 and len(response.content) != size:
                raise NotReceived(f"it did not arrive whole ({len(response.content)} of {size} bytes)", 0)
        return response.content

    @staticmethod
    def _answered(response: httpx.Response, what: str) -> None:
        """Telegram's server error or rate limit may pass; any other error status is its refusal."""
        if response.is_success:
            return
        try:
            body = response.json()
            description = (body.get("description") if isinstance(body, dict) else "") or response.reason_phrase
        except ValueError:
            description = response.reason_phrase
        if response.status_code == 429 or response.status_code >= 500:
            raise NotReceived(f"Telegram could not give {what} yet ({response.status_code} {description})", 0)
        raise NotReceived(f"Telegram refused {what} ({response.status_code} {description})", 0, refused=True)



async def ffmpeg(data: bytes, *args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-v", "error", *args, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate(data)
    return out


_http: aiohttp.ClientSession | None = None


def http() -> aiohttp.ClientSession:
    """The HTTP session cloud speech uses here (inside a call, LiveKit provides one)."""
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession()
    return _http


async def transcribe(recording: bytes | Path, seconds: float | None = None) -> str:
    """A voice note, heard by the same STT as calls: Listening, one for voice notes, recordings and the sound of videos
    alike (core/attachments.hear, with its time limit; its first `seconds` only). A streaming-only one (AssemblyAI) hears
    it as a stream, sent as fast as it takes it (a 6 s note: about 2 s)."""
    return await attachments.hear(recording, seconds)


async def spoken(text: str) -> str:
    """What a voice note says: her voice's own controls kept, stage text ("*laughs*" too), markdown and emoji not (as
    calls)."""
    async def words():
        yield text
    out = voice_only(sounds.unstaged(words()))
    for step in (filter_markdown, speakable, filter_emoji):  # (as a call: addresses are never spelled aloud)
        out = step(out)
    return "".join([piece async for piece in out]).strip()


def shown(text: str) -> str:
    """Text with a voice note, without the voice controls (heard, not read): only those her voices document ([laugh],
    and xAI's <soft>…</soft> around words: the words stay), and never inside code. Other brackets are her words."""
    def drop(piece: str) -> str:  # (a bracketed one takes the space before it; a wrapping one leaves its words' spaces)
        return re.sub(r"( ?)(" + bq.CONTROLS.pattern + ")", lambda m: "" if m.group(2).startswith("[") else m.group(1),
                      piece, flags=re.I)
    return bq.outside_code(text, drop).strip()


async def speak(text: str) -> bytes:
    """Her reply as OGG/Opus, with qualified native tags in the same request as their words."""
    live_voice.now()  # (the voice the settings page gives now: a choice never waits for a restart)
    voice = tts(http_session=http())
    pcm, rate = [], voice.sample_rate
    for _, value in sounds.pieces(await spoken(text)):
        async for chunk in voice.synthesize(value):
            rate = chunk.frame.sample_rate
            pcm.append(bytes(chunk.frame.data))
    return await ffmpeg(b"".join(pcm), "-f", "s16le", "-ar", str(rate), "-ac", "1",
                        "-i", "pipe:0", "-c:a", "libopus", "-b:a", "48k", "-f", "ogg", "pipe:1")


DOWNLOAD_LIMIT = 20_000_000  # bytes: the most Telegram's cloud Bot API lets a bot download (getFile)


def _media(msg: dict) -> tuple[str, str, str, int, str] | None:
    """(what, file id, file name, size, type) of the file a message carries: a photo, a document of any kind, a video,
    a round video, a GIF or a sticker. A name made here comes from Telegram's own id for the file, so a message
    Telegram delivers again keeps no second copy (core/attachments.keep). (A voice note: _voice.)"""
    if msg.get("photo"):
        largest = msg["photo"][-1]  # (Telegram lists a photo's sizes, smallest first)
        return ("a photo", largest["file_id"], f"photo-{largest.get('file_unique_id') or largest['file_id'][-12:]}.jpg",
                int(largest.get("file_size") or 0), "image/jpeg")
    for kind, what, default in (("document", "a file", ""), ("video", "a video", "mp4"), ("video_note", "a video", "mp4"),
                                ("animation", "a GIF", "mp4"), ("sticker", "a sticker", "")):
        if item := msg.get(kind):
            if kind == "sticker":  # (a still one is a picture; an animated one Telegram's own format; a video one a clip)
                default = "tgs" if item.get("is_animated") else "webm" if item.get("is_video") else "webp"
            made = f"{kind}-{item.get('file_unique_id') or item['file_id'][-12:]}" + (f".{default}" if default else "")
            return what, item["file_id"], Path(item.get("file_name") or made).name, int(item.get("file_size") or 0), \
                item.get("mime_type") or ""
    return None


def _voice(msg: dict) -> tuple[str, str, str, int, str] | None:
    """(what, file id, file name, size, type) of a voice note or an audio track: heard as his own words."""
    if item := msg.get("voice") or msg.get("audio"):
        name = item.get("file_name") or f"voice-{item.get('file_unique_id') or item['file_id'][-12:]}.ogg"
        return "a voice note", item["file_id"], Path(name).name, int(item.get("file_size") or 0), item.get("mime_type") or "audio/ogg"
    return None


def readable(text: str, link=None) -> str:
    """Telegram shows Markdown as typed: keep the words, drop the marks (links stay as "text (url)"). `link`: as
    markdown_to_html's, on the same links it finds (its pattern: a titled target too), never inside code or a quoted
    fence: a link it says not to draw is its text alone. A caption that would be left empty is main's."""
    import re
    if link is not None:
        apart, at, labels = quoted_fences(text), 0, {}
        for piece, code in bq.code_pieces(text):
            if code:
                apart.append((at, at + len(piece)))
            at += len(piece)

        def decided(m: re.Match) -> str:
            if any(a <= m.start() < b for a, b in apart) or link(m.group(2)):
                return m.group(0)
            key = f"\x00{len(labels)}\x00"  # (kept apart from the steps below, as the HTML's own placeholders)
            labels[key] = readable(m.group(1))
            return key
        out = readable(LINK.sub(decided, text))
        for key, label in labels.items():
            out = out.replace(key, label)
        return out if out.strip() else readable(text)
    text = re.sub(r"\[([^\]]+)\]\((\S+?)\)", r"\1 (\2)", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return re.sub(r"(?m)^#{1,6}\s+", "", text)


# Her one redo when she wrote a tool call as text: a real call, or the same words, plainly.
REDO = ("Your last reply wrote a tool call as text instead of making it, so nothing ran and they saw nothing. If you "
        "meant to call a tool, call it now; if you were explaining something, say it again in plain words.")

def _unvoiced_text(text: str) -> str:
    """Her words as a text message: her voice's own controls are heard, never shown ([laugh], and xAI's <soft>...</soft>
    around words: the words stay), but only outside code, which stays exactly as she wrote it."""
    def strip(piece: str) -> str:
        for tag in voice_controls():
            piece = re.sub(r" ?" + re.escape(tag), "", piece, flags=re.IGNORECASE)
        return WRAPPING.sub("", piece)
    return bq.outside_code(text, strip)


LOOK = object()  # (Telegram._send: its links not read yet)


async def _file_links(text: str):
    """How her links to files are drawn in one outgoing message: the files she offered, read once for it, off the event
    loop, and only when a link target to a file is in it (attachments.shown_as_link). None draws every link as main does:
    none in it, or a record that cannot be read now (never a message lost to it)."""
    artifact = attachments.ARTIFACT in text
    plain_artifact = (lambda target: not target.strip().startswith(attachments.ARTIFACT)) if artifact else None
    if attachments.FILE_MARK not in text:
        return plain_artifact
    try:
        offered = set(await asyncio.to_thread(attachments.offered))
    except Exception:  # noqa: BLE001
        return plain_artifact
    return lambda target: attachments.shown_as_link(target, offered)


def _messages(text: str) -> list[str]:
    """Her reply as Telegram messages: brain.queen.segments (main's {MSG_BREAK} rule), each within Telegram's length."""
    return [piece for part in segments(text) for piece in _fit(part, 3500)]


def _missed_id(msg: dict) -> str:
    """The one id of the notice that a file of this message did not arrive: Telegram's own chat and message ids, the
    same however its turn is gathered and however often it is answered (a restart before the inbox lets it go)."""
    return f"missed-{(msg.get('chat') or {}).get('id')}-{msg.get('message_id')}"


def _his_id(msg: dict) -> str:
    """His message's own id in the record (Telegram's chat and message ids), for a turn kept without her mind."""
    return f"tg-{(msg.get('chat') or {}).get('id')}-{msg.get('message_id')}"


def _not_arrived(ref: dict) -> str:
    """What he is told, in a message of its own, of a file of his that did not arrive (Telegram._receive's reference):
    what it was, its name exactly as he named it (several in a turn: which one; it goes as plain text, _enqueue), the
    reason, and to send it again unless that cannot help (over Telegram's limit for a bot, with the other way said)."""
    what = " ".join(filter(None, [(ref.get("what") or "a file").removeprefix("a "), ref.get("name") or ""]))
    return f"Your {what} didn't arrive: {ref['error']}." + ("" if ref.get("final") else " Please send it again.")


def _private(path: Path, text: str) -> None:
    """A file of hers, his alone (core/state.private_file), written whole: his messages kept, his chat's owner."""
    from core.state import private_file
    tmp = path.with_name(f".{path.name}.tmp")
    with private_file(tmp, "w") as out:
        out.write(text)
    os.replace(tmp, path)


def _same(a: dict, b: dict) -> bool:
    """The same Telegram message (its chat and message id), however often Telegram delivers it."""
    return (a.get("chat", {}).get("id"), a.get("message_id")) == (b.get("chat", {}).get("id"), b.get("message_id")) \
        and a.get("message_id") is not None


def _fit(part: str, limit: int = 4000) -> list[str]:
    """Telegram takes 4096 characters a message: a longer one is cut at a line or sentence end, each piece as written
    (only the line break at the cut goes: the next line's indentation stays). A cut inside a fenced code block closes
    the fence at the end of its piece and opens it again, with its language, at the start of the next: each message
    is whole code, as she wrote it."""
    pieces = []
    while len(part) > limit:
        cut = max(part.rfind("\n", 0, limit), part.rfind(". ", 0, limit) + 1)
        cut = cut if cut > limit // 2 else limit
        head = part[:cut].rstrip()
        rest = part[cut:].lstrip("\n ") if part[cut - 1:cut] == "." else part[cut:].lstrip("\n")
        if (fence := _open_fence(head)) and rest:
            head, rest = head + "\n" + fence[0], fence[1] + "\n" + rest
        pieces.append(head)
        part = rest
    return pieces + ([part] if part.strip() else [])


def _open_fence(text: str) -> tuple[str, str] | None:
    """A fence still open at the end of `text`, as (what closes it, the line that opened it), else None (code_pieces'
    own rule: closed only by a fence of the same character at least as long)."""
    fence, opener = "", ""
    for line in text.split("\n"):
        found = re.match(r"[ \t]*(`{3,}|~{3,})", line)
        if fence:
            if found and found.group(1)[0] == fence[0] and len(found.group(1)) >= len(fence) \
                    and not line.strip()[len(found.group(1)):].strip():
                fence = ""
            continue
        if found:
            fence, opener = found.group(1), line.strip()
    return (fence, opener) if fence else None


class Telegram:
    @property
    def chat_id(self):
        if not getattr(self, "_owner_checked", False):
            return getattr(self, "_chat_id", None)
        owner = telegram_approvals.read(OWNER)
        return owner.get("chat") if telegram_approvals.owns(
            owner, self.bot.id, owner.get("chat"), owner.get("owner")) else None

    @chat_id.setter
    def chat_id(self, value):
        self._chat_id = value

    def __init__(self, bot: Bot | None) -> None:
        self.bot, self.chat_id = bot, None
        self._owner_checked = bot is not None  # no transport when only listing the channel's tools
        if bot is not None:
            self.bot.authorize = lambda chat: self.chat_id is not None and chat == self.chat_id
        self.voice_next, self.voice_speeches = False, set()  # replies owed as voice notes
        self.reply_attempt: tuple[str | None, str] | None = None
        self.inbox_settled: dict[str, dict] = {}  # finished messages whose inbox removal can be retried
        self.written: set[str] = set()  # replies that were a tool call written as text: they settle nothing
        self.pending, self.last_message, self.gathering = [], 0.0, None
        self.greeting = None  # the next call's first line, written after a pause here (brain/greeting.py)
        self.turn = asyncio.Lock()  # her replies to their messages, one at a time (_answer)
        self.upkeep = clock.Upkeep()  # what every always-on process looks after, each tick (core/clock.py)
        self.memory_job, self.last_said, self.remembered = None, 0.0, 0.0  # chat -> Life memory (wall clock)
        self.memory_for, self.memory_tried = 0.0, 0.0
        said = relationship.call(CHANNEL)  # a chat that paused before a restart still reaches Life
        if said:
            self.last_said = said[-1]["t"]
        self.wake = asyncio.Event()  # a message waits in the outbox
        self.settled: dict[str, asyncio.Future] = {}  # a reply's message (LiveKit item) -> its outcome, when it comes
        self.outcomes: dict[str, Receipt] = {}  # the outcomes known, the latest few
        self.tool_items: dict[str, list[str]] = {}  # a reply -> what its tools put in the outbox (a voice note, the chat)
        self.files_sent: set[str] = set()  # replies whose send_file reached him (sent directly, not through the outbox)
        self.document_task: asyncio.Task | None = None
        self.mind_streak = 0  # her mind's failures in a row here, with no answer between (_mind_silent: what he is told)
        self.mind_failed = 0.0  # when her mind last failed past its own retries (LiveKit's error event: _mind_error)

    async def run(self) -> None:
        owner = telegram_approvals.read(OWNER)
        self.chat_id = owner.get("chat")
        feelings.init()
        self.workers = Workers(record=note)
        self.session = AgentSession(llm=queen_llm(record=note), tools=[self.workers])
        # Someone to tell is here only once the bot has its owner's chat (with none: she "told" an owed result
        # nine times, each refused). Every reply's receipt is Telegram's own: each of its messages accepted.
        self.queen = Queen(history=relationship.recent(), call_id=CHANNEL, record=note, channel=CHANNEL,
                           show=self.text, mode="chat", extra_tools=self._tools(), present=lambda: bool(self.chat_id),
                           show_approval=self.show_approval,
                           receipt=self._receipt, queue_worker_files=self._queue_worker_files,
                           lookup_worker_files=self.workers.lookup_worker_files, workers=self.workers)
        self.queen.recover = self._recover
        self.session.on("speech_created", self._speech)
        self.session.on("conversation_item_added", self._item)
        self.session.on("error", self._mind_error)
        tooltrace.follow(self.session, note)  # (her tool calls in her turn log, as on a call: core/tooltrace.py)
        await self.session.start(agent=self.queen)
        note("call_start")
        log.info("ready")
        self._reconcile()  # (what the last process left in flight or half settled, before anything is sent)
        self._recover_worker_files()
        asyncio.create_task(self._sender())
        asyncio.create_task(self._clock())
        if (unanswered := json.loads(INBOX.read_text()) if INBOX.exists() else []) and self.chat_id:
            log.info("answering %d message(s) taken before a restart", len(unanswered))
            self.pending, self.last_message = list(unanswered), time.monotonic()
            self.gathering = asyncio.create_task(self._gather())
        async for update in self.bot.updates():
            try:
                await self._message(update.get("message") or {})
            except Exception:
                log.exception("message failed")

    async def _message(self, msg: dict) -> None:
        chat, user = msg.get("chat", {}), msg.get("from", {})
        if chat.get("type") != "private":
            return
        if not isinstance(chat.get("id"), int) or not isinstance(user.get("id"), int):
            return  # a private assistant: strangers get nothing
        text = msg.get("text") or ""
        if text.startswith(telegram_approvals.START):
            async with self.turn:
                first = self.chat_id is None
                if not await asyncio.to_thread(telegram_approvals.finish, OWNER, self.bot.id, chat["id"], user["id"],
                                                text.removeprefix(telegram_approvals.START)):
                    return
                self.chat_id = chat["id"]
                if first:
                    asyncio.create_task(self._adopt())
                await self.bot.send("sendMessage", chat_id=self.chat_id,
                                    text="Chat paired.")
            return
        owner = telegram_approvals.read(OWNER)
        if not telegram_approvals.owns(owner, self.bot.id, chat["id"], user["id"]):
            return
        first = self.chat_id is None
        self.chat_id = chat["id"]
        if first:  # results and moments owed while nobody could be told here are told now
            asyncio.get_running_loop().create_task(self._adopt())
        if any(_same(msg, kept) for kept in self.pending + self._kept()):  # (Telegram resends after a restart)
            return
        # Kept before it is taken: the next poll acknowledges it to Telegram, so one that cannot be kept
        # yet (a full disk) holds the poll and is tried again until it is, never taken and then lost on a restart.
        while True:
            try:
                self._keep(msg)
                break
            except OSError as e:
                log.warning("message not kept yet (%s); trying again in %s s", type(e).__name__, KEEP_AGAIN)
                await asyncio.sleep(KEEP_AGAIN)
        if await self._approval_message(msg):
            self._answered([msg])
            return
        # Messages sent together are one turn, like a person reading them all before answering. Later
        # ones get their own reply, in order, each with its own decisions: revising a reply to cover
        # several messages lost work on the local model.
        self.pending.append(msg)
        self.last_message = time.monotonic()
        if self.gathering is None:
            self.pending = self._kept()
            self.gathering = asyncio.create_task(self._gather())

    async def _gather(self) -> None:
        try:
            while self.pending:
                while (left := self.last_message + GATHER - time.monotonic()) > 0:
                    await asyncio.sleep(left)
                msgs, self.pending = self.pending, []
                msgs = [msg for msg in msgs if _his_id(msg) not in getattr(self, "inbox_settled", {})]
                # Recover the saved attempt. Its durable outbox still owns delivery.
                for (speech, _), group in groupby(msgs, key=lambda msg: (msg.get(INBOX_SPEECH), msg.get(INBOX_RETRY))):
                    batch = list(group)
                    if speech:
                        if (batch[0].get("chat") or {}).get("id", self.chat_id) == self.chat_id and not self._outgoing(speech):
                            self._stalled(batch, final=True, unknown=True)
                    elif not await self._answer_kept(batch):
                        continue
                    self._finish_inbox(batch)
        finally:
            self.gathering = None

    async def _answer_kept(self, batch: list[dict]) -> bool:
        keys = {_his_id(msg) for msg in batch}
        for attempt in range(2):
            msgs = [msg for msg in self._kept() if _his_id(msg) in keys]
            if not msgs:
                return True
            try:
                if await self._answer(msgs):
                    return True
            except Exception:
                log.exception("answer failed")
                if speech := next((msg[INBOX_SPEECH] for msg in self._kept()
                                   if _his_id(msg) in keys and msg.get(INBOX_SPEECH)), None):
                    if not self._outgoing(speech):
                        self._stalled(msgs, final=True, unknown=True)
                    return True
            self._stalled(msgs, final=bool(attempt))
            if not attempt:
                await asyncio.sleep(ANSWER_RETRY)
        try:
            self._mark_inbox(batch, INBOX_RETRY, _his_id(batch[0]))
        except OSError as error:
            log.warning("Telegram retry batch could not be saved (%s)", type(error).__name__)
        return False

    def _stalled(self, msgs: list[dict], *, final: bool = False, unknown: bool = False) -> None:
        words = ("I couldn't confirm what happened with your earlier message. Check before asking me to do it again."
                 if unknown else "I still couldn't answer your earlier message. I'll try again when you message me."
                 if final else "Your earlier message is taking longer than expected. I'm still checking it.")
        key = f"{'unresolved' if final else 'stalled'}-{_his_id(msgs[0])}"
        self._enqueue(key, None, words, plain=True)

    def _mark_inbox(self, msgs: list[dict], field: str, value: str | None) -> None:
        keys = {_his_id(msg) for msg in msgs}
        kept = self._kept()
        for msg in kept:
            if _his_id(msg) in keys:
                if value:
                    msg[field] = value
                else:
                    msg.pop(field, None)
        _private(INBOX, json.dumps(kept))

    async def _reply_kept(self, msgs: list[dict], kind: str, *, voice: bool = False, **options):
        # LiveKit creates its speech id inside generate_reply. Keep our attempt first and tie its outbox entries to it.
        attempt = f"attempt-{uuid4().hex}"
        self._mark_inbox(msgs, INBOX_SPEECH, attempt)
        self.reply_attempt = (None, attempt)
        self.voice_next = voice
        try:
            reply = Queen.reply_to_turn(self.queen, self.session, **options)
        except BaseException:
            # LiveKit emits speech_created before it starts a task. A synchronous failure before that event is safe to retry.
            not_started = self.reply_attempt == (None, attempt)
            self.reply_attempt = None
            self.voice_next = False
            if not_started:
                self._mark_inbox(msgs, INBOX_SPEECH, None)
            raise
        self.reply_attempt = (reply.id, attempt)
        note(kind, id=reply.id)
        return reply, await self._wait_reply(reply, msgs)

    async def _wait_reply(self, reply, msgs: list[dict]) -> str:
        """Wait for the same reply through a stall; only an ended reply can be retried."""
        finished = asyncio.Event()
        reply.add_done_callback(lambda _: finished.set())
        try:
            await asyncio.wait_for(finished.wait(), ANSWER_WAIT)
        except asyncio.TimeoutError:
            if not self._outgoing(reply.id):
                self._stalled(msgs)
            log.warning("reply %s still running after %s s", reply.id, ANSWER_WAIT)
            try:
                await asyncio.wait_for(finished.wait(), ANSWER_LATE)
            except asyncio.TimeoutError:
                reply.interrupt(force=True)
                try:
                    await asyncio.wait_for(finished.wait(), ANSWER_INTERRUPT)
                except asyncio.TimeoutError:
                    self._stalled(msgs, final=True, unknown=True)
                    return "settled"
            if self._outgoing(reply.id):
                return "settled"
            if any(item.type in ("function_call", "function_call_output") for item in reply.chat_items):
                self._stalled(msgs, final=True, unknown=True)
                return "settled"
            if reply.id in self.written:
                return "reply"
            self._mark_inbox(msgs, INBOX_SPEECH, None)
            return "retry"
        return "reply"

    def _kept(self) -> list[dict]:
        return json.loads(INBOX.read_text()) if INBOX.exists() else []

    def _keep(self, msg: dict) -> None:
        """Telegram forgets a message once the next poll acknowledges it: keep it until her reply to it
        is written and kept for sending, so a restart in between answers it rather than losing it."""
        _private(INBOX, json.dumps(self._kept() + [msg]))

    def _answered(self, msgs: list[dict]) -> None:
        _private(INBOX, json.dumps([m for m in self._kept() if not any(_same(m, done) for done in msgs)]))

    def _finish_inbox(self, msgs: list[dict]) -> None:
        try:
            self._answered(msgs)
        except OSError as error:
            log.warning("Telegram inbox cleanup deferred (%s)", type(error).__name__)
            self.inbox_settled = getattr(self, "inbox_settled", {})
            self.inbox_settled.update((_his_id(msg), msg) for msg in msgs)

    def _flush_inbox(self) -> None:
        if settled := getattr(self, "inbox_settled", {}):
            try:
                self._answered(list(settled.values()))
            except OSError:
                return
            settled.clear()

    def _told(self, msgs: list[dict]) -> None:
        """His messages, as kept in the inbox, marked: he has been told their file did not arrive. Answered again after a
        restart, however much later (her mind down meanwhile), they are never told twice."""
        for msg in msgs:
            msg[TOLD] = True
        with contextlib.suppress(OSError):  # (only the mark: the notice itself is kept already)
            kept = self._kept()
            for m in kept:
                if any(_same(m, done) for done in msgs):
                    m[TOLD] = True
            _private(INBOX, json.dumps(kept))

    def _mind_error(self, ev) -> None:
        """LiveKit's verdict that her mind failed past its own retries (an LLM error it marks unrecoverable), kept by its
        time: a reply of nothing then is a failure, never a silence she chose (_answer)."""
        error = getattr(ev, "error", None)
        if getattr(error, "type", "") == "llm_error" and getattr(error, "recoverable", True) is False:
            self.mind_failed = time.time()

    async def _approval_message(self, msg: dict) -> bool:
        text = msg.get("text") or ""
        if Workers.approval_choice(text) is None:
            return False
        owner = telegram_approvals.read(OWNER)
        chat, sender = msg.get("chat") or {}, msg.get("from") or {}
        if (chat.get("type") == "private"
                and telegram_approvals.enrolled(owner, self.bot.id, chat.get("id"), sender.get("id"))
                and getattr(self, "workers", None) is not None):
            if reply := await self.workers.approval_reply(text):
                await self.text(reply)
        return True

    async def _answer(self, msgs: list[dict]) -> bool:
        """Her one reply to these messages; True once it is settled: written and kept for sending (the outbox sends it,
        across a restart too, never writing it again), or nothing to send."""
        # One turn at a time, in the order sent: messages whose file is still downloading are never overtaken by later
        # ones, and a reply starts from her context once the reply before it is done, work it handed off included.
        # (Begun together, a later reply saw the earlier words still unanswered and started their work again: four
        # jobs for two.)
        async with self.turn:
            # Recovered inbox entries go through the same raw reply path.
            ordinary = []
            for msg in msgs:
                if (msg.get("chat") or {}).get("id", self.chat_id) != self.chat_id or await self._approval_message(msg):
                    self._answered([msg])
                else:
                    ordinary.append(msg)
            msgs = ordinary
            if not msgs:
                return True
            texts, heard, voice = [], [], False  # (his words and his files, in the order sent: core/attachments.message)
            silent = True  # (nothing in these messages but voice notes with no words in them)
            missed, received, status = [], asyncio.Event(), None  # (his files that did not arrive, with their messages)
            clock = lambda: getattr(self.bot, "clock", time.monotonic)()  # noqa: E731 (the files' clock: a turn with files)
            if any(_media(msg) or _voice(msg) for msg in msgs):
                # The files of this turn share one time to arrive, and he sees she is at work meanwhile: "typing…" kept
                # up beside the downloads, never waited on (a stalled courtesy must not spend a file's time).
                self.bot.receive_by = clock() + RECEIVE_WITHIN
                status = asyncio.create_task(self._show(lambda: "typing", received.is_set))
                await asyncio.sleep(0)  # (its first sign is asked for now, before the files: shown, never waited on)
            try:  # (his files' time: whatever ends it, done, failed or cancelled, ends the "typing…" with it)
                for msg in msgs:
                    if quoted := (msg.get("reply_to_message") or {}).get("text"):
                        texts.append(f'(replying to: "{quoted}")')
                    said = msg.get("text") or msg.get("caption") or ""  # ("/start" too: he opened the chat, she answers)
                    silent = silent and not said.strip() and not quoted
                    if media := _media(msg):  # a file of any kind: kept whole here, and given to her as what it is (after
                        got = await self._receive(*media)
                        texts += [said, got]  # its caption: his words, then what he sent)
                        said, silent = "", False
                        if got.get("error"):
                            missed.append((msg, got))
                    if spoken_note := _voice(msg):  # kept first, like any file; then heard as his own words
                        voice = True
                        started, kept = time.time(), await self._receive(*spoken_note)
                        if kept.get("error"):  # (one that did not arrive is a file that did not arrive: never his words)
                            texts += [kept, said]
                            silent = False
                            missed.append((msg, kept))
                            continue
                        else:
                            heard.append(kept)
                            heard_at, ours = clock(), False  # (ours: the channel's own words, when none of his were heard)
                            long = float((msg.get("voice") or msg.get("audio") or {}).get("duration") or 0) \
                                or await asyncio.to_thread(attachments.duration, Path(kept["path"]))
                            try:  # (she says so, rather than silence; a long one is heard up to the limit, and says so)
                                words = await transcribe(Path(kept["path"]), attachments.LISTEN_SECONDS)
                                silent = silent and not words.strip()
                                if not words.strip():
                                    words, ours = "[They sent a voice note, but no words were heard in it]", True
                                elif long > attachments.LISTEN_SECONDS:
                                    words += (f" [the rest of this voice note, after {attachments.LISTEN_SECONDS // 60} of its "
                                              f"{round(long / 60)} minutes, was not heard here; it is kept, and a Worker can transcribe it]")
                            except Exception as e:  # (could not be heard is not silence: she says so, in her own words)
                                words, silent, ours = f"[They sent a voice note, but it could not be heard: {str(e)[:120]}]", False, True
                            # Hearing it is not his files' time (a minute of it left the next file no
                            # time to be asked for, then called it missing).
                            self.bot.receive_by += clock() - heard_at
                        note("heard", seconds=round(time.time() - started, 2), text=words)
                        # Marked, in this turn and in the history: she heard them ("I'm text only" to a voice note).
                        texts.append(words if ours else "(voice note) " + words)
                    texts.append(said)
            finally:
                received.set()
                if status is not None:
                    status.cancel()
            # A file that did not arrive is told to him by the channel itself, in a message of its own, before anything
            # of hers runs: kept for sending (across a restart too) under his message's own id, so it goes once, whatever
            # her mind then does (answers, stays silent, is unavailable or never finishes). A message of his kept in the
            # inbox remembers it was told, however long it stays owed (the outbox keeps settled notices only a while).
            for msg, ref in missed:
                if not msg.get(TOLD):
                    self._enqueue(_missed_id(msg), None, _not_arrived(ref), plain=True)
                ref["told"] = True
            # Nothing else in the turn (no words of his, no file that arrived; a message he replied to is context, not
            # his words): it is answered by that, without her mind, and kept as what he sent (his history, her context,
            # the turn log), never as an empty turn: each message once, under its own id (never the notice's: one id,
            # one row), however its turn is gathered or answered.
            if missed and not heard and not any((m.get("text") or m.get("caption") or "").strip() for m in msgs) \
                    and all(t.get("error") for t in texts if isinstance(t, dict)):
                kept = {r.get("item") for r in life.record_rows() if r}
                new = []
                for msg, ref in missed:
                    if (item := _his_id(msg)) in kept:
                        continue
                    what = [{k: ref[k] for k in ("what", "name") if ref.get(k)}]
                    record = attachments.missing_text(what)
                    row = relationship.append("user", record, channel=CHANNEL, call_id=CHANNEL, item=item)
                    note("turn", id=item, role="user", text=record)
                    new.append((record, what, row))
                if new:
                    with contextlib.suppress(Exception):  # (the record has them whatever happens; her context, for her next reply)
                        chat = self.queen.chat_ctx.copy()
                        for record, what, row in new:  # (as attachments.message makes it: none of it is his words)
                            extra = {"said": "", "missing": what}
                            if row:
                                extra.update(memory_row=row, memory_digest=life.row_ref(row)["digest"])
                            chat.add_message(role="user", content=[record], extra=extra)
                        await self.queen.update_chat_ctx(chat)
                return True
            if missed:
                self._told([msg for msg, _ in missed])
            if voice and silent:  # (a genuinely silent note: one plain notice, no thought of hers, no voice)
                self._enqueue(f"silent-{msgs[-1].get('message_id', time.time_ns())}", None, NO_WORDS)
                note("silent", messages=len(msgs))
                return True
            words = await attachments.message([t for t in texts if t], heard=heard)
            if not (words.text_content or "").strip():
                return True
            words.id = _his_id(msgs[0])
            turn_ctx = self.queen.chat_ctx.copy()
            turn_ctx.items = [item for item in turn_ctx.items if item.id != words.id]
            spoken_back = voice and voice_on()  # (the voice switch off: her answer is text)
            # (the runtime acts on his own words only, never on what a file says)
            text = attachments.said(words)
            await self.queen.prepare(turn_ctx, text, words.created_at, voice_note=spoken_back, turn_id=words.id)
            begun = time.time()
            reply, waited = await self._reply_kept(msgs, "answering", voice=spoken_back, user_input=words, chat_ctx=turn_ctx)
            replies = [reply]
            if waited != "reply":
                self._worker_sign_in(msgs, *replies)
                return waited == "settled"
            if reply.id in self.written:  # a tool call written as text: nothing ran, so she does it once more
                self.written.discard(reply.id)
                if any(item.type in ("function_call", "function_call_output") for item in getattr(reply, "chat_items", ())):
                    self._stalled(msgs, final=True, unknown=True)
                    return True
                reply, waited = await self._reply_kept(msgs, "redo", instructions=REDO)
                replies.append(reply)
                if waited != "reply":
                    self._worker_sign_in(msgs, *replies)
                    return waited == "settled"
                if reply.id in self.written:  # twice: they are told plainly, never left with silence
                    self.written.discard(reply.id)
                    self._enqueue(f"redo-{reply.id}", reply.id, "Sorry, that didn't start on my side. Could you ask me once more?")
                    self._worker_sign_in(msgs, *replies)
                    return True
            self._worker_sign_in(msgs, *replies)
            await self._mind_silent(reply, begun, msgs)
        return True  # (written and kept: the outbox sends it, outside the turn)

    def _worker_sign_in(self, msgs: list[dict], *replies) -> None:
        if (workers := getattr(self, "workers", None)) is None:
            return

        def enqueued(item: str) -> bool:
            with contextlib.suppress(OSError, ValueError):
                states = {e["state"] for e in json.loads(OUTBOX.read_text()) if e["item"] == item and e["state"] != "replaced"}
                return bool(states) and states.isdisjoint({"refused", "failed", "nothing"})
            return False

        if words := workers.worker_sign_in_notice(*replies, delivered=enqueued):
            self._enqueue(f"worker-sign-in-{_his_id(msgs[-1])}", replies[-1].id, words, kept=words, plain=True)
            note("worker_sign_in_notice", channel=CHANNEL)

    def _said(self, reply) -> bool:
        """Whether anything of hers reached the outbox from this reply: words in it, or a message its tools put there (a
        voice note, words put in the chat). A tool that ran and sent nothing is not something said."""
        if any(getattr(i, "type", "") == "message" and getattr(i, "role", "") == "assistant"
               and (getattr(i, "text_content", "") or "").strip() for i in getattr(reply, "chat_items", None) or []):
            return True
        return self._outgoing(reply.id)

    def _outgoing(self, speech: str) -> bool:
        if speech in getattr(self, "files_sent", ()):  # a file went straight to him
            return True
        with contextlib.suppress(OSError, ValueError):
            return any(speech in (e.get("speech"), e.get("attempt"))
                       for e in json.loads(OUTBOX.read_text()) if isinstance(e, dict))
        return False

    async def _mind_silent(self, reply, begun: float, msgs: list[dict]) -> bool:
        """Her mind failed past its own retries (her model's error, or a step given up in brain/queen.bounded) and
        nothing of hers came of his turn: he is told so in the shared words, once, as plain text, kept in the record, as
        on a call and on the page (a clean Mac: a first message answered by silence). A silence she chose has no
        such failure and stays silent. True when he was told."""
        if self._said(reply):
            self.mind_streak = 0  # (she answered: a later failure is a first one again)
            return False
        await asyncio.sleep(0.5)  # (LiveKit's verdict on a failure can land just after the reply ends)
        if max(getattr(self, "mind_failed", 0.0), bq.MIND_FAILED["at"]) < begun:
            return False
        if self._said(reply):
            self.mind_streak = 0
            return False
        log.warning("reply %s: her mind failed with nothing said; he is told", reply.id)
        self.mind_streak = getattr(self, "mind_streak", 0) + 1  # (the same words as a call's and the page's, by repetition)
        words = bq.mind_silent_words(self.mind_streak, speech=reply)
        self._enqueue(f"mind-{msgs[-1].get('message_id', time.time_ns())}", None, words, kept=words, plain=True)
        note("mind_silent", channel=CHANNEL)
        return True

    def _speech(self, ev) -> None:
        speech = ev.speech_handle
        if self.reply_attempt and self.reply_attempt[0] is None and ev.source == "generate_reply":
            self.reply_attempt = (speech.id, self.reply_attempt[1])
        note("speech", id=speech.id)  # (telemetry: when a reply began)
        if self.voice_next:
            self.voice_speeches.add(speech.id)
            self.voice_next = False
        asyncio.create_task(self._typing(speech))

    async def _typing(self, speech) -> None:  # "typing…" (or "recording…") while she composes
        await self._show(lambda: "record_voice" if speech.id in self.voice_speeches else "typing", speech.done)

    async def _show(self, action, done) -> None:
        """Telegram's sign that she is at work (action()), kept up until done(): only a courtesy, so what it shows
        never waits for it, and a failed one ends it quietly."""
        try:
            while self.chat_id and not done():
                await self.bot.call("sendChatAction", chat_id=self.chat_id, action=action())
                for _ in range(max(1, round(STATUS_EVERY / 0.5))):
                    if done():
                        return
                    await asyncio.sleep(min(0.5, STATUS_EVERY))
        except (httpx.HTTPError, RuntimeError, ValueError):
            pass  # only a courtesy

    def _item(self, ev) -> None:
        item = ev.item
        if item.type != "message":
            return
        text = (item.text_content or "").strip()
        speech = self.session.current_speech if item.role == "assistant" else None
        # (of his messages, his words and the file references only: what was read from a file is never logged)
        note("turn", id=item.id, role=item.role, text=attachments.record_text(item) if item.role == "user" else item.text_content,
             interrupted=item.interrupted, metrics=dict(item.metrics or {}), speech=speech.id if speech is not None else None,
             **({"files": item.extra["files"]} if item.role == "user" and (getattr(item, "extra", None) or {}).get("files") else {}))
        if item.role == "user":  # his words and what he sent (references), never what was read from it
            row = relationship.append("user", attachments.record_text(item), channel=CHANNEL, call_id=CHANNEL,
                                      files=(getattr(item, "extra", None) or {}).get("files"), item=item.id, once=True)
            if row and isinstance(getattr(item, "extra", None), dict):  # (its row: the one identity her memory changes it by)
                item.extra["memory_row"] = row
                item.extra["memory_digest"] = life.row_ref(row)["digest"]
            if text:
                self.last_said = time.time()
            return
        if item.role != "assistant" or item.interrupted or not text:
            return  # a reply cut short is never sent, so never said
        if not bq.mind_decides() and written_call(text, self.queen._tool_ids(), self.queen.his_words()):
            # A tool call written as text (this Mac's model does this): never sent or kept, and unless it was a
            # silence ("no_reply") it settles nothing: _answer has her redo it once, a result stays owed.
            if text.strip("`'\" ").lower() != "no_reply" and speech is not None:
                self.written.add(speech.id)
            return
        # Kept for sending, and in her history only once Telegram has every message of it (_sender).
        self._enqueue(item.id, speech.id if speech is not None else None, text,
                      voice=speech is not None and speech.id in self.voice_speeches)

    # -- The outbox: each message she sends, kept until Telegram has it, sent once --

    def _enqueue(self, item: str, speech: str | None, text: str, voice: bool = False, kept: str = "",
                 plain: bool = False, literal: bool = False) -> None:
        """One reply of hers, as the messages Telegram will show, each with its own immutable words, destination and
        send state, kept (state/core/telegram-outbox.json) until Telegram has it or refused it. `kept` is what her
        history keeps once all of it is sent (her words, or a note of a voice note). `plain`: the channel's own words,
        sent exactly as written (a file's name in them is never read as Markdown or as a voice control)."""
        if literal:
            # Slice without trimming or inserting formatting. Even astral characters fit Telegram's limit.
            parts = [("plain", text[i:i + 2000]) for i in range(0, len(text), 2000)]
        elif plain:
            parts = [("plain", p) for p in _fit(text, 3500)]
        elif voice:
            caption = readable(shown(unbroken(text)))  # (links stay visible)
            parts = [("voice", text)] + ([] if len(caption) <= 1024 else [("text", p) for p in _messages(shown(text))])
        else:
            parts = [("text", p) for p in _messages(_unvoiced_text(text))]
        now = time.time()
        live_speech, attempt = getattr(self, "reply_attempt", None) or (None, None)
        attempt = attempt if speech and live_speech in (None, speech) else None
        with jobs._locked(OUTBOX, list) as out:
            if any(e["item"] == item for e in out):  # (the same one again, from a turn answered again after a restart:
                parts = []                           # its messages are kept, sent or settled, under this id: never twice)
            for n, (kind, words) in enumerate(parts):
                out.append({"key": f"{item}:{n}", "item": item, "speech": speech, "part": n, "parts": len(parts),
                            **({"attempt": attempt} if attempt else {}),
                            "kind": kind, "text": words, "kept": (kept or unbroken(text)) if n == 0 else "",
                            "chat": self.chat_id, "state": "pending", "first": now, "next": now})
        self.wake.set()

    async def _sender(self) -> None:
        """One message at a time, in order: a {MSG_BREAK} line starts a new one, typed like a person. A message that
        cannot have reached Telegram (no connection, its limit, its own error) is tried again with the same words for
        RETRY_FOR; one Telegram refuses (no such chat, the bot blocked) is not; one whose answer was lost after it was
        sent is unknown, never sent twice. Each is kept "sending" before it goes out, so a stop in between leaves it
        unknown, never sent again (_reconcile)."""
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.wake.wait(), 1.0)
            self.wake.clear()
            while (entry := self._due()) is not None:
                if entry["part"]:  # ("typing…" before the next message: only a courtesy, an outage page's answer too)
                    with contextlib.suppress(httpx.HTTPError, RuntimeError, ValueError):
                        await self.bot.call("sendChatAction", chat_id=entry["chat"], action="typing")
                    await asyncio.sleep(min(2.5, 0.5 + len(entry["text"]) / 120))
                # (the files she offered, read before it is marked as being sent: a stop now leaves it to send)
                links = await _file_links(entry["text"]) if entry["kind"] != "plain" else None
                self._sending(entry)
                state, sent, why = await self._send(entry, links)
                if state == "again" and time.time() - entry["first"] > RETRY_FOR:
                    state = "failed"
                self._mark(entry, state, sent, why)

    def _due(self) -> dict | None:
        """The first message still to go, and only when its time has come: never one behind it (a message waiting out a
        failed try holds the ones after it, so he gets them in the order she wrote them)."""
        out = json.loads(OUTBOX.read_text()) if OUTBOX.exists() else []
        first = next((e for e in out if e["state"] in ("pending", "sending")), None)
        return first if first is not None and first["state"] == "pending" and first["next"] <= time.time() else None

    def _sending(self, entry: dict) -> None:
        with jobs._locked(OUTBOX, list) as out:
            if (mine := next((e for e in out if e["key"] == entry["key"]), None)) is not None:
                mine.update(state="sending", pid=os.getpid(), at=time.time())

    def _reconcile(self) -> None:
        """At a start: a message the last process was sending may have reached him (unknown: never sent again), and a
        reply whose every message has its outcome gets its history and receipt, if a stop came before them."""
        with jobs._locked(OUTBOX, list) as out:
            for e in out:
                if e["state"] == "sending":
                    e.update(state="unknown", why="its process stopped while it was being sent")
            items = list(dict.fromkeys(e["item"] for e in out if not e.get("settled")))
        for item in items:
            self._settle_item(item)

    async def _send(self, entry: dict, links=LOOK) -> tuple[str, int | None, str]:
        """(sent | again | refused | unknown, Telegram's message id, why). links: how her links to files are drawn
        (_file_links), read by the sender before it marked this message as being sent; else read here."""
        if links is LOOK:
            links = await _file_links(entry["text"])
        if not entry.get("chat"):
            return "refused", None, "no chat to send to yet"
        try:
            if entry["kind"] == "voice":
                if not voice_on():
                    self._as_text(entry, "voice replies switched off")
                    return "replaced", None, ""
                started = time.time()
                caption = readable(shown(unbroken(entry["text"])), link=links)
                fits = len(readable(shown(unbroken(entry["text"])))) <= 1024  # (as _enqueue decided: else its words follow)
                ogg = await speak(unbroken(entry["text"]))
                if not voice_on():  # the switch may change while synthesis is in flight
                    self._as_text(entry, "voice replies switched off")
                    return "replaced", None, ""
                sent = await self.bot.call("sendVoice", files={"voice": ("reply.ogg", ogg, "audio/ogg")}, chat_id=entry["chat"],
                                           **({"caption": caption} if fits else {}))
                note("sent", voice=True, seconds=round(time.time() - started, 2), text=entry["text"])
            elif entry["kind"] == "plain":  # (the channel's own words, exactly as written)
                sent = await self.bot.call("sendMessage", chat_id=entry["chat"], text=entry["text"])
                note("sent", voice=False, part=entry["part"], parts=entry["parts"], text=entry["text"])
            else:
                try:  # Markdown as real formatting (main's Telegram HTML), else exactly as she wrote it; a link of hers to a
                    # file she never offered is its label, in this message only (attachments.shown_as_link)
                    html = markdown_to_html(entry["text"], link=links)
                    sent = await self.bot.call("sendMessage", chat_id=entry["chat"], text=html, parse_mode="HTML")
                except RuntimeError as e:
                    if "parse" not in str(e).lower() and "entit" not in str(e).lower():
                        raise
                    sent = await self.bot.call("sendMessage", chat_id=entry["chat"], text=entry["text"])
                note("sent", voice=False, part=entry["part"], parts=entry["parts"], text=entry["text"])
            return "sent", (sent or {}).get("message_id"), ""
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:  # never reached Telegram
            return "again", None, type(e).__name__
        except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.WriteTimeout) as e:
            return "unknown", None, f"sent, but Telegram's answer was lost ({type(e).__name__})"  # (never sent twice)
        except RuntimeError as e:  # (Telegram's server error or rate limit may pass, by its code; any other is its refusal)
            if passes(e):
                return "again", None, str(e)[:120]
            return "refused", None, str(e)[:160]
        except ValueError as e:  # (an answer that was not Telegram's JSON: a proxy, an outage page)
            return "again", None, f"no answer from Telegram ({type(e).__name__})"
        except Exception as e:  # noqa: BLE001 (her voice could not be made: the words go as text instead, in its place)
            if entry["kind"] == "voice":
                self._as_text(entry, f"voice not made ({str(e)[:80]})")
                return "replaced", None, ""
            return "refused", None, str(e)[:160]

    def _as_text(self, entry: dict, why: str) -> None:
        """A voice note that could not be made goes as text messages in its place, in the same reply (its receipt and
        history are of what went), right where the voice note was, so nothing after it goes first."""
        texts, now = _messages(shown(entry["text"])), time.time()
        with jobs._locked(OUTBOX, list) as out:
            mine = next((e for e in out if e["key"] == entry["key"]), None)
            if mine is None:
                return
            if not texts:  # (only a sound, with voice replies off: there is nothing to send, and nothing waits for it)
                mine.update(state="nothing", why=why)
            else:
                mine.update(state="replaced", why=why)
                at = out.index(mine)
                out[at + 1:at + 1] = [{"key": f"{entry['key']}-t{n}", "item": entry["item"], "speech": entry["speech"],
                                       "part": n, "parts": len(texts), "kind": "text", "text": words, "chat": entry["chat"],
                                       "kept": unbroken(entry["text"]) if n == 0 else "", "state": "pending", "first": now,
                                       "next": now} for n, words in enumerate(texts)]
        if not texts:
            self._settle_item(entry["item"])  # (its receipt now: silent, never its timeout waited out)
            return
        self.wake.set()

    def _mark(self, entry: dict, state: str, sent, why: str, final: bool = True) -> None:
        """Its outcome, kept; once every message of a reply has one, her history and its receipt follow (_settle_item)."""
        if state == "replaced":
            return
        with jobs._locked(OUTBOX, list) as out:
            mine = next((e for e in out if e["key"] == entry["key"]), None)
            if mine is None:
                return
            if state == "again":
                mine["next"] = time.time() + min(BACKOFF[1], BACKOFF[0] * 2 ** min(mine.get("tries", 0), 5))
                mine["tries"], mine["why"], mine["state"] = mine.get("tries", 0) + 1, why, "pending"
                log.warning("message not sent yet (%s); trying again", why)
                return
            mine.update(state=state, message_id=sent, why=why)
        if state == "sent" and entry["chat"] == self.chat_id and not entry["item"].startswith("document-notice-"):
            self._retry_worker_files()
        if final:
            self._settle_item(entry["item"])

    def _settle_item(self, item: str) -> None:
        """A reply whose every message has its outcome: its history (what reached him: all of it, or the messages that
        went), her context (a reply that never reached him leaves it; a half-sent one keeps only what went) and its
        receipt (delivered; cut, with what reached him, so only the rest is told again; unknown; refused). Its messages
        stay in the outbox a while, settled, with Telegram's ids: a restart before the Queen settled its telling finds
        them (_recover)."""
        with jobs._locked(OUTBOX, list) as out:
            parts = [e for e in out if e["item"] == item and e["state"] != "replaced"]  # (a voice note sent as text)
            if not parts or any(e["state"] in ("pending", "sending") for e in parts):
                return
            first = not parts[0].get("settled")
            for e in out:
                if e["item"] == item:
                    e["settled"] = True
            out[:] = [e for e in out if not e.get("settled")] + [e for e in out if e.get("settled")][-200:]
            parts = [dict(e) for e in parts]
        counted = [e for e in parts if e["state"] != "nothing"]  # (a sound alone with voice replies off: nothing to send)
        states = {e["state"] for e in counted}
        went = [e for e in counted if e["state"] == "sent"]
        done = "silent" if not counted else "sent" if states == {"sent"} else "unknown" if "unknown" in states else \
            "partial" if went else next(s for s in ("refused", "failed") if s in states)
        whole = next((e.get("kept") for e in parts if e.get("kept")), "")
        recorded_approval = bool(went) and item.startswith("worker-approval-")
        reached = whole if done == "sent" or recorded_approval else "\n\n".join(
            e["text"] if e["kind"] == "plain" else unbroken(e["text"]) for e in went)
        why = next((e.get("why") for e in parts if e.get("why")), "")
        if first:
            if reached:  # (with her reply's own id: its row is found by it)
                row = relationship.append("assistant", reached, channel=CHANNEL, call_id=CHANNEL, item=item)
                for message in self.queen.chat_ctx.items:
                    if message.type == "message" and message.id == item and row:
                        message.extra.update(memory_row=row, memory_digest=life.row_ref(row)["digest"])
                self.last_said = time.time()
                self._greet_later()
            if done not in ("sent", "silent"):
                log.warning("a reply was not sent (%s): %s", done, why)
                asyncio.get_event_loop().create_task(self._unsaid(item, reached if done != "unknown" else ""))
        receipt = Receipt({"sent": "delivered", "failed": "undelivered", "partial": "cut"}.get(done, done),
                          reached if done in ("sent", "partial") else "", [e.get("message_id") for e in went], why)
        self.outcomes[item] = receipt
        for old in list(self.outcomes)[:-200]:
            self.outcomes.pop(old, None)
        if (future := self.settled.pop(item, None)) is not None and not future.done():
            future.set_result(receipt)

    async def _unsaid(self, item: str, reached: str = "") -> None:
        """A reply that never reached him leaves her context: she never believes she said it. One half sent keeps
        only the messages that went, so she knows what he saw."""
        chat = self.queen.chat_ctx.copy()
        if any(i.type == "message" and i.id == item for i in chat.items):
            if reached:
                for i in chat.items:
                    if i.type == "message" and i.id == item:
                        i.content = [reached]
            else:
                chat.items[:] = [i for i in chat.items if i.type != "message" or i.id != item]
            await self.queen.update_chat_ctx(chat)

    async def _receipt(self, speech) -> Receipt:
        """For the Queen: what became of one reply here (core of "told": a result is told only once every message of
        it is sent to its owner's chat)."""
        if speech.interrupted:  # (cut short: never sent)
            return Receipt("cut")
        if speech.id in self.written:  # a tool call written as text in place of telling it: nothing went out
            self.written.discard(speech.id)
            return Receipt("undelivered", why="a tool call written as text")
        items = [i.id for i in speech.chat_items if i.type == "message" and i.role == "assistant" and (i.text_content or "").strip()]
        items += self.tool_items.pop(speech.id, [])  # (a voice note or words put in the chat: counted once sent)
        if not items:
            return Receipt("delivered") if _presented(speech) else Receipt("silent")
        receipts = []
        for item in items:
            if item not in self.outcomes:
                future = self.settled.setdefault(item, asyncio.get_event_loop().create_future())
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(future), RETRY_FOR + 120)
            receipts.append(self.outcomes.get(item) or Receipt("unknown", why="no outcome from Telegram in time"))
        if all(r.state == "delivered" for r in receipts):
            return Receipt("delivered", " ".join(r.words for r in receipts), [i for r in receipts for i in r.ids])
        if not any(r.state in ("unknown", "refused", "undelivered") for r in receipts):  # (some of it went: he saw that)
            return Receipt("cut", " ".join(r.words for r in receipts if r.words), [i for r in receipts for i in r.ids],
                           next((r.why for r in receipts if r.why), ""))
        worst = next(r for r in receipts if r.state in ("unknown", "refused", "undelivered"))
        return Receipt(worst.state, why=worst.why)

    async def _recover(self, job: dict) -> None:
        """A result this channel was telling when it last stopped: its messages, kept in the outbox, decide."""
        telling = job.get("telling") or {}
        out = json.loads(OUTBOX.read_text()) if OUTBOX.exists() else []
        mine = [e for e in out if e.get("speech") == telling.get("speech")]
        if not mine:
            return await Queen.recover(self.queen, job)
        while any(e["state"] in ("pending", "sending") for e in mine):
            await asyncio.sleep(2)
            out = json.loads(OUTBOX.read_text()) if OUTBOX.exists() else []
            mine = [e for e in out if e.get("speech") == telling.get("speech")]
        if mine and all(e["state"] == "sent" for e in mine):
            words = unbroken(next((e.get("kept") for e in mine if e.get("kept")), ""))
            await self.queen.resettle({**job, "telling": {**telling, "state": "delivered", "words": words,
                                                          "ids": [e.get("message_id") for e in mine]}})
        else:
            jobs.mark(job["job_id"], job.get("version"), telling={**telling, "state": "unknown",
                                                                  "why": "not known to have been sent"})

    def _greet_later(self, pause: float = 30) -> None:
        """After a pause here, the next call's first line is written by her own mind (brain/greeting.py), in its own
        process: a call made after this chat opens with it at once."""
        if self.greeting is not None and not self.greeting.done():
            self.greeting.cancel()

        async def later() -> None:
            await asyncio.sleep(pause)
            from brain import greeting
            greeting.soon()
        self.greeting = asyncio.get_event_loop().create_task(later())

    async def _receive(self, what: str, file_id: str, name: str, size: int, mime: str) -> dict:
        """A file he sent, kept whole on this Mac (state/inbox/<day>/, untracked) for her and her Workers
        (core/attachments.keep: a message Telegram delivers again is the file already kept), or why it could not be:
        Telegram lets a bot download only DOWNLOAD_LIMIT."""
        def missed(why: str, tries: int, final: bool = False) -> dict:  # (said plainly, by name, on record: never dropped)
            note("not_received", what=what, name=name, size=size, tries=tries, why=why)
            return {"name": name, "what": what, "error": why, "final": final}  # (final: sending it again cannot help)
        limit = (f"Telegram lets a bot download at most {DOWNLOAD_LIMIT // 1_000_000} MB; it can come another way, such "
                 "as Viventium's chat on the Mac")
        if size > DOWNLOAD_LIMIT:
            return missed(f"it is {size / 1e6:.0f} MB, and {limit}", 0, final=True)
        try:
            data = await self.bot.download(file_id, expected_size=size)
        except Exception as e:
            tries = getattr(e, "tries", 1)
            # (a reason of the Bot's own making, already free of its token; of anything else only its kind; and, when
            # Telegram refused a file whose size it did not give, its own limit beside its own words: she says what it means)
            why = str(e)[:160] if isinstance(e, NotReceived) else type(e).__name__
            # (asked to send it again unless the limit and the other way are said: a refusal of a file that fits may
            # pass on a new send, which is a new file id)
            beyond = bool(getattr(e, "refused", False) and not size)
            return missed(f"it could not be downloaded ({why})" + (f"; {limit}" if beyond else ""), tries, final=beyond)
        tries = getattr(data, "tries", 1)
        try:
            ref = await asyncio.to_thread(attachments.keep, data, name, mime, CHANNEL)
        except Exception as e:
            return missed(f"it could not be kept on this Mac ({str(e)[:120]})", tries)
        note("received", what=what, name=ref["name"], type=ref["type"], bytes=ref["bytes"], size=size, tries=tries)
        return ref

    @staticmethod
    def _documents() -> Path:
        return OUTBOX.with_name("telegram-documents.json")

    def _queue_worker_files(self, refs: dict[str, list[dict]]) -> bool:
        """Keep the offered IDs separate from text receipts until Telegram accepts their bytes."""
        if not self.chat_id:
            return False
        with jobs._locked(self._documents()) as entries:
            for candidates in refs.values():
                ref = candidates[0]
                entries.setdefault(ref["id"], {"state": "pending", "tries": 0, "chat": self.chat_id, "ref": ref,
                                               "candidates": candidates})
        self._start_worker_files()
        return True

    def _retry_worker_files(self) -> None:
        # A definite rejection is tried once more, after the next delivered reply.
        path = self._documents()
        if not path.exists():
            return
        released = False
        try:
            with jobs._locked(path) as entries:
                for entry in entries.values():
                    if entry["state"] == "retry" and entry["chat"] == self.chat_id:
                        entry["state"] = "pending"
                        released = True
        except (OSError, ValueError) as error:
            log.warning("document retry could not be released (%s)", type(error).__name__)
            return
        if released:
            self._start_worker_files()

    def _start_worker_files(self) -> None:
        if self.chat_id and (self.document_task is None or self.document_task.done()):
            self.document_task = asyncio.create_task(self._worker_files())

    def _recover_worker_files(self) -> None:
        path = self._documents()
        if not path.exists():
            return
        with jobs._locked(path) as entries:
            for identifier, entry in entries.items():
                if entry["state"] == "sending":
                    if life.row_of_item(f"worker-document-{identifier}"):
                        entry["state"] = "sent"
                    else:
                        entry.update(state="unknown", notice="Telegram did not confirm delivery.")
        self._document_notices()
        self._start_worker_files()

    def _document_notices(self) -> None:
        with jobs._locked(self._documents()) as entries:
            for identifier, entry in entries.items():
                if entry["chat"] == self.chat_id and (problem := entry.get("notice")):
                    name = " ".join(Path(entry["ref"]["path"]).name.splitlines())
                    self._enqueue(f"document-notice-{identifier}-{entry['state']}", None, f"{name}: {problem}", plain=True)
                    entry.pop("notice")

    async def _worker_files(self) -> None:
        """A hung document does not hold the text sender or the Queen."""
        path = self._documents()
        while path.exists() and self.chat_id:
            entries = json.loads(path.read_text())
            pending = [entry for entry in entries.values()
                       if entry["chat"] == self.chat_id and entry["state"] == "pending"]
            if not pending:
                return
            deadline = asyncio.get_running_loop().time() + DOCUMENTS_WITHIN
            for entry in pending:
                await self._worker_document(entry, deadline)

    async def _worker_document(self, entry: dict, deadline: float) -> None:
        ref = entry["ref"]
        identifier, tries = ref["id"], entry["tries"]
        state, problem = "failed", ""
        uploading = False
        try:
            async with asyncio.timeout_at(deadline):
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError
                ref, content = await asyncio.to_thread(attachments.available_worker_file, entry.get("candidates") or [ref])
                if self.chat_id != entry["chat"]:
                    return
                with jobs._locked(self._documents()) as entries:
                    entries[identifier].update(state="sending", ref=ref)
                uploading = True
                tries += 1
                name = Path(ref["path"]).name
                await self.bot.call("sendDocument", files={"document": (name, content)}, chat_id=entry["chat"])
                relationship.append("assistant", attachments.link(ref), channel=CHANNEL, call_id=CHANNEL, files=[ref],
                                    item=f"worker-document-{identifier}", once=True)
                state = "sent"
                note("sent", file=name)
        except attachments.WorkerFileChanged:
            problem = "The file changed after the Worker finished. It was not sent."
        except TimeoutError:
            tries += not uploading
            state = "unknown" if uploading else "retry" if tries < 2 else "failed"
            problem = ("The upload timed out. Telegram did not confirm delivery." if uploading else
                       "The upload did not start in time.")
        except (TelegramError, httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            state = "retry" if tries < 2 else "failed"
            if state == "failed":
                problem = "Telegram could not accept the file after two tries."
        except (OSError, ValueError, RuntimeError, httpx.HTTPError):
            if uploading:
                state, problem = "unknown", "Telegram did not confirm delivery."
            else:
                problem = "The Worker file is unavailable."
        with jobs._locked(self._documents()) as entries:
            entries[identifier].update(state=state, tries=tries, **({"notice": problem} if problem else {}))
        if problem:
            self._document_notices()

    async def _send_document(self, ref: dict, content: bytes, *, first: bool) -> str:
        name = Path(ref["path"]).name
        if not self.chat_id:
            raise ToolError("Nobody has messaged this bot yet: there is no chat to send it to.")
        try:
            await self.bot.send("sendDocument", files={"document": (name, content)}, chat_id=self.chat_id)
        except (httpx.HTTPError, RuntimeError, ValueError) as e:  # never "sent" when it was not (an outage page too)
            raise ToolError(f"{name} could not be sent ({str(e)[:120]}).") from None
        self._retry_worker_files()
        note("sent", file=name)
        relationship.append("assistant", f"(sent the file {name})", channel=CHANNEL, call_id=CHANNEL,
                            files=[ref] if first else None, file_offer="" if first else ref["id"])
        return name

    def _tools(self) -> list:
        """What only a chat can do: send a file, or answer with a voice note when asked."""
        @function_tool()
        async def send_file(ctx: RunContext, path: str) -> ToolResult:
            """Send the user a file from this Mac in the chat: one a Worker made, or one they asked for.

            Use this directly for an existing file with a known exact path, including an older send without an offer ID.

            Args:
                path: The file's full path, as a Worker result or the user gave it.
            """
            file = Path(path).expanduser()
            queen = getattr(self, "queen", None)
            speech = getattr(ctx, "speech_handle", None)
            if isinstance(queen, Queen) and await queen.worker_offer("", speech, str(file.absolute())):
                return ToolResult(f"{file.name} is due to go as a document after this reply.", reply_required=True)
            if not file.is_file():
                raise ToolError(f"No file at {path}.")
            if file.stat().st_size > attachments.MAX_BYTES:
                raise ToolError(f"{file.name} is over Telegram's 50 MB limit.")
            try:
                ref, content = await asyncio.to_thread(attachments.outgoing_file, path, resolve_path=False)
            except (OSError, ValueError) as error:
                raise ToolError(str(error)) from None
            if isinstance(queen, Queen) and await queen.worker_offer(ref["sha256"], speech):
                return ToolResult(f"{file.name} is due to go as a document after this reply.", reply_required=True)
            return await send_document(ctx, ref, content, first=True)

        @function_tool(description=ledger.shipped("modes/resend_file"))
        async def resend_file(ctx: RunContext, offered_id: str) -> ToolResult:
            """Send an offered file again.

            Args:
                offered_id: The id of a file already offered in the conversation. Use it to send that exact file again.
            """
            try:
                ref, content = await asyncio.to_thread(attachments.resendable_file, offered_id)
            except (OSError, ValueError) as error:
                raise ToolError(str(error)) from None
            return await send_document(ctx, ref, content)

        async def send_document(ctx: RunContext, ref: dict, content: bytes, first: bool = False) -> ToolResult:
            name = await self._send_document(ref, content, first=first)
            if (speech := getattr(ctx, "speech_handle", None)) is not None:  # (something of hers reached him: _said)
                self.files_sent.add(speech.id)
            return ToolResult(f"Sent {name}.", reply_required=not await _spoke(ctx))

        @function_tool()
        async def send_voice_note(ctx: RunContext, text: str) -> ToolResult:
            """Send explicitly requested audio on Telegram. Ordinary replies are sent automatically
            as text; a request for "messages" alone means text, without this tool. Call this tool for
            a voice note the user asked for, including an active earlier request for voice replies.
            Plain reply text does not send that audio. Incoming voice notes already get automatic
            audio replies.

            Args:
                text: What to say, in plain spoken words.
            """
            if not voice_on():  # (the voice switch: no voice of hers on Telegram)
                return ToolResult("Voice notes are switched off for Telegram in Settings: say it in your text reply.",
                                  reply_required=True)
            speech = getattr(ctx, "speech_handle", None)
            key = f"{ctx.function_call.call_id}-voice"
            self._enqueue(key, speech.id if speech is not None else None, text, voice=True,
                          kept="(voice note) " + words_only(text))
            if speech is not None:  # (her reply's receipt waits for it: told only once it is sent)
                self.tool_items.setdefault(speech.id, []).append(key)
            return ToolResult("It is going out as a voice note now.", reply_required=False)
        return [send_file, resend_file, send_voice_note]

    async def text(self, text: str) -> None:  # put_in_chat: here it is simply a message, in her reply's receipt
        key, speech = f"chat-{time.time_ns()}", bq._speech_now(self.queen)
        self._enqueue(key, getattr(speech, "id", None), text)
        if speech is not None:
            self.tool_items.setdefault(speech.id, []).append(key)

    async def show_approval(self, text: str, history: str) -> None:
        owner = telegram_approvals.read(OWNER)
        if not telegram_approvals.enrolled(owner, self.bot.id, self.chat_id, owner.get("owner")):
            return
        self._enqueue(f"worker-approval-{time.time_ns()}", None, text, kept=history, literal=True)
        note("shown", text=history)

    async def _adopt(self) -> None:
        """Results nobody owns that this channel may tell (jobs.claim: never while he is on a call that can take them,
        never one asked to be told elsewhere): told here, each once; work still running followed here."""
        if not self.chat_id or getattr(self, "workers", None) is None:  # (no owner yet, or not started yet)
            return
        ready, running = await self.workers.resume(self.queen)
        await self.queen._running(running)
        for job, result in ready:
            self.queen.tell(job, result)

    async def _clock(self) -> None:
        """Every 20 s: scheduled moments that came due wake the Queen; Workers whose call hung up are
        adopted, and their results told here (a reminder that came due while no bot was connected is one
        of those: core/clock.py). A chat quiet for CHAT_PAUSE becomes an episodic Life summary, as a call
        does at hang-up. And what every always-on process looks after (core/clock.Upkeep): her Life core
        view, the shared CLIs' permissions. With no owner yet there is nobody to tell: it only looks after."""
        while True:
            try:
                self._flush_inbox()
                self.upkeep()
                if self.chat_id:
                    jobs.here(CHANNEL)  # (the channel he can be told on: after a call and a typed chat, core/jobs)
                    if hasattr(clock, "wake_due"):  # the clock's own shared path: the channel he is on takes his moments
                        clock.wake_due(self.queen, CHANNEL)
                    else:
                        for item in schedules.due(dt.datetime.now()):
                            self.queen.wake(item)
                    await self._adopt()
                if self.memory_job is not None and self.memory_job.poll() == 0:  # that summary is in Life
                    self.remembered, self.memory_job = self.memory_for, None
                last = self.last_said
                if last and last > self.remembered and time.time() - last > CHAT_PAUSE and life.life() and not call_live() \
                        and helpers.available() and time.time() - self.memory_tried > 600 \
                        and (self.memory_job is None or self.memory_job.poll() is not None):
                    self.memory_for, self.memory_tried = last, time.time()  # a failure is retried in 10 min
                    with log_file("memory.log") as out:  # (this run's own logs, his alone: core/state.py)
                        self.memory_job = subprocess.Popen([sys.executable, "-m", "core.life", "summary", CHANNEL],
                                                           cwd=ROOT, stdout=out, stderr=out, stdin=subprocess.DEVNULL)
            except Exception:
                log.exception("clock")
            await asyncio.sleep(20)


RESTING = ("Viventium is resting: it was quit on your Mac. What you write here waits, and is answered when you open it "
           "again.")


async def resting(bot: Bot) -> bool:
    """His own Quit (./vx down: the menu bar's Quit): his paired chat is told plainly that Viventium rests, and that what he
    writes waits (Telegram holds it; it is read at the next start). Never on a restart, which never runs this.
    Without it, a message to a resting Viventium gets only silence. True when it was sent."""
    owner = telegram_approvals.read(OWNER)
    chat = owner.get("chat")
    if not telegram_approvals.owns(owner, bot.id, chat, owner.get("owner")):
        return False
    try:
        async with asyncio.timeout(8):  # (Quit is never held up by Telegram)
            await bot.call("sendMessage", chat_id=chat, text=RESTING)
        return True
    except Exception as error:  # noqa: BLE001 (no connection, a refusal: Quit goes on)
        log.info("the resting notice was not sent: %s", type(error).__name__)
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("No TELEGRAM_BOT_TOKEN (Keychain item viventium-light/telegram_bot_token, see README).")
    if sys.argv[1:] == ["--resting"]:
        sys.exit(0 if asyncio.run(resting(Bot(token))) else 1)
    asyncio.run(Telegram(Bot(token)).run())


if __name__ == "__main__":
    main()
