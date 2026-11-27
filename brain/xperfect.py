"""Tiny client for this project's own xPerfect instance (its documented runtime HTTP API).

Each hand-off is one conversation with xPerfect's native coordinator, that job's background Queen (it
never speaks to the user). xPerfect saves the job before any model runs (~0.3 s); then the coordinator's
own model does the work or starts Workers, and separate jobs run at the same time within the Mac's real
capacity (main Viventium's Fast Queen pattern).

Your work first, by xPerfect's own admission rules. A job's Worker is prepared without starting anything, so
xPerfect accepts it whatever runs at that moment (brain/patches/xperfect-0007), and its run, owned by the job's
coordinator goal, needs only a free slot: it runs beside a night routine at once where there is room (Hybrid: three),
and waits in xPerfect's own queue for its turn where there is not (Local: one GPU, one slot; the night routine gives
its place up, brain/night.make_room). A run of Light's own (a cortex, a night routine: think) asks for room within its
own time, at xPerfect's pace, and never waits in line ahead of your work.
Why: a night's routines were once refused a Worker thousands of times in a row, every 2 s, because Light retried
instead of letting xPerfect queue the work. xPerfect itself was idle all that time (no run, reservation, event or
Worker in its database), so nothing held its one-at-a-time fence or a slot: what refuses with nothing running is its
resource guard (memory or disk below its headroom). Its own class was never logged, so the cause is likely, not
proven: every refusal and every wait now carries xPerfect's class, dimension and shortage, said once per wait, and a
job that waits says why (reason)."""
import logging
import asyncio
import hashlib
import hmac
import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from core import attachments

log = logging.getLogger("xperfect")
DONE = {"completed", "failed", "cancelled", "interrupted", "needs_input", "blocked"}
TERMINAL_RUN = {"completed", "failed", "cancelled", "interrupted"}
PROJECT_TITLE = "Viventium voice"
THINKING_TITLE = "Viventium subconscious"  # the cortices' own project: never mixed with your jobs (brain/rounds.py)
GOAL = "job"  # each job conversation's one goal, run on the job's own Worker
REPORT_WAIT = 60.0  # s: after a job's Workers finish, how long its coordinator has to report them
PUBLICATION_WAIT = 3.0  # s: looking up files must not hold a telling
# xPerfect's own limits for what one request carries (coordinator.py: a goal's text; a dispatch's instruction and a
# turn's message): within them a job's words go whole; past them, as an exact reference to the whole text on disk.
GOAL_LIMIT, MESSAGE_LIMIT = 262_144, 524_288
RESULT_PAGE = 64_000  # the most of a result xPerfect gives at once (read_result); a longer one is read page by page
# xPerfect's typed marks of a run that waits for room (its queue of host capacity waiters, store.py)
CAPACITY_WAIT = {"host_capacity", "host_worker_busy"}
PREPARE_WAIT = 300.0  # s: how long a job's Worker may be refused for room (xPerfect without patch 0007 refuses it)
ROOM_WAIT = 120.0  # s: the most a run of Light's own waits for room (never more than its own time), then PlaceBusy
# His live xPerfect (vx xp_ports): the Workers online, the Workers on this Mac. A process with a state of its own (a
# test, a probe, an eval, the bench) never makes Workers there: they would run on his real accounts and records.
LIVE_APIS = {8866, 8876}
LIVE_STATES = {"state-cloud", "state-local"}
GROK_APPROVAL_EXPIRED = "The Grok Worker stopped because its approval request expired."
APPROVAL_PREVIEW_VERSION = 4
GROK_START_STOPS = {
    "provider_auth_timeout": "Grok authentication did not answer in time. Try the job again.",
    "provider_auth_refreshing": "The Grok Worker is waiting for Light to refresh its sign-in. Try again shortly.",
    "provider_auth_disabled": "Grok is off in Viventium AI.",
}
GROK_STOPS = {"native_input_expired": GROK_APPROVAL_EXPIRED, **GROK_START_STOPS}


class PlaceBusy(RuntimeError):
    """No room for a run of Light's own on this place now (xPerfect's typed host capacity answer): it is tried again
    later (a night routine comes again; a cortex has no thought this round). Never raised for your work.
    capacity_class: xPerfect's own word for what is full (mutation_scope, family_lane, …)."""

    def __init__(self, message: str, capacity_class: str = "", facts: dict | None = None) -> None:
        super().__init__(message)
        self.facts = facts or {"class": capacity_class}
        self.capacity_class = capacity_class or self.facts.get("class", "")
        self.reason = reason(self.facts)


class Unreachable(RuntimeError):
    """xPerfect did not answer for a minute while a job was followed: its work may still be running and its result may
    still come (a restarting xPerfect is not a failed job). The caller decides what to say; the job is not failed here."""


# A Worker's own thinking effort, as xPerfect's host runtimes read it from that Worker's settings (a run dispatched by a
# coordinator goal carries none of its own: think(owned=True) gives its Worker the effort it was asked for).
EFFORT_ENV = {"claude-code": "WPR_CLAUDE_CODE_EFFORT", "codex-cli": "WPR_CODEX_CLI_REASONING_EFFORT",
              "grok-build": "WPR_GROK_REASONING_EFFORT"}
THINK_GOAL = "think"  # an owned run's one goal (think(owned=True))
# The held Grok grant path remains available to stand-in tests. The proof
# binds the Worker, expiry and deny list to xPerfect's private grant key.
WORKER_ACCESS_GRANTS_ENABLED = False  # Off: production never asks for a grant.
WORKER_ACCESS_HOURS = 12.0  # a Worker, its wait for a slot and the follow-ups it is asked: a run admitted later is refused
WORKER_ACCESS_PROFILES = {"grok-build"}  # (the harness that asks per action without it)
GRANT_KEY = Path("data") / "worker-access-grant.key"  # (in xPerfect's own state: owner_worker_access.GRANT_KEY_FILE)


def _grant_proof(key: bytes, worker: str, expires_at: float, rules: list[str]) -> str:
    """The proof xPerfect checks (owner_worker_access.grant_proof): the Worker, its expiry and the deny list."""
    digest = hashlib.sha256(json.dumps(list(rules), separators=(",", ":")).encode()).hexdigest()
    message = json.dumps({"v": 1, "worker_id": worker, "expires_at": round(float(expires_at), 3), "deny_sha256": digest},
                         sort_keys=True, separators=(",", ":"))
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


# What a run used, as xPerfect reports it (RunResponse)
USAGE = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "total_tokens")
CORTEX_ROLE = "One of Viventium's background cortices: it thinks about one turn of conversation and changes nothing"


# xPerfect's own failure classes (typed, never read from text) that mean the route failed, not the task: a
# sign-in, a limit, the provider or its model out of reach. Only these let a job run again on WORKER_FALLBACK;
# a refusal, a cancel, a rejected request or a full context never do.
ROUTE_DOWN = {"provider_rate_limited", "provider_quota_exhausted", "provider_auth_missing", "provider_unauthorized",
              "provider_account", "provider_connected_account_reconnect_required", "provider_auth_projection_unavailable",
              "provider_unavailable", "provider_unavailable_before_adapter_call", "provider_upstream_unavailable",
              "provider_temporarily_unavailable", "provider_response_failed", "provider_response_deadline_exceeded",
              "provider_progress_stalled", "provider_model", "provider_readiness", "provider_native",
              *GROK_START_STOPS}  # xPerfect emits these auth codes only before prompting Grok.


def _approval_literal(value: str | bool | None) -> str:
    # Use the same quoted encoding for paths, commands, and file bytes. ASCII also
    # makes invisible or direction-changing Unicode visible as escapes.
    return json.dumps(value, ensure_ascii=True)


def _render_approval(effect: list[dict]) -> str:
    return "\n\n".join("\n".join(f"{label}: {_approval_literal(value)}" for label, value in section.items())
                       for section in effect)


def _parse_approval(preview: str) -> list[dict]:
    """Read the text rendered on the Mac as ordered sections of labeled JSON literals."""
    sections = []
    for block in preview.split("\n\n"):
        section = {}
        for line in block.split("\n"):
            label, separator, literal = line.partition(": ")
            if not separator or not label or label in section:
                raise ValueError("Invalid approval preview")
            value = json.loads(literal)
            if value is not None and type(value) not in (str, bool):
                raise ValueError("Invalid approval preview value")
            section[label] = value
        sections.append(section)
    return sections


def _approval_edits(operation: str, targets: list[str], diffs: dict, args: dict) -> list[dict]:
    """Bind each known edit operation to its full arguments and its own target."""
    if diffs and diffs.keys() != set(targets):
        return []

    path = args.get("path")
    if args.keys() <= {"path"} and operation in ("edit", "apply_patch"):
        if not diffs:
            return []
        changes = [{"Target": target, "Change": "File diff"} for target in diffs]
    elif targets != [path]:
        return []
    elif (operation in ("edit", "write") and args.keys() <= {"path", "variant", "content"}
          and args.get("variant", "Write") == "Write" and isinstance(args.get("content"), str)):
        if diffs and diffs[path]["After"] != args["content"]:
            return []
        changes = [{"Target": path, "Change": "Write file", "New text": args["content"]}]
    elif (operation in ("edit", "search_replace") and args.keys() <= {
              "path", "variant", "old_string", "new_string", "replace_all"}
          and args.get("variant", "SearchReplace") == "SearchReplace"
          and isinstance(args.get("old_string"), str) and isinstance(args.get("new_string"), str)
          and isinstance(args.get("replace_all", False), bool)):
        before, after = args["old_string"], args["new_string"]
        replace_all = args.get("replace_all", False)
        if not before and replace_all:
            return []
        if diffs and (diffs[path]["Before"] or "", diffs[path]["After"]) != (before, after):
            return []
        changes = [{"Target": path, "Change": "Search and replace" if before else "Create or fill an empty file",
                    "Old text": before, "New text": after, "Replace all": replace_all}]
    else:
        return []
    for change in changes:
        change.update(diffs.get(change["Target"], {}))
    return changes


def _approval_preview(call: dict, workspace: str) -> tuple[str, str, bool]:
    """Only offer what a known request schema can express and the Mac text can reproduce."""
    call = call if isinstance(call, dict) else {}
    metadata = call.get("_meta")
    native = metadata.get("x.ai/tool") if isinstance(metadata, dict) else None
    meta = native if isinstance(native, dict) else {}
    kind = call.get("kind") if call.get("kind") is not None else meta.get("kind")
    operation = meta.get("name") or call.get("name") or kind
    known_name = isinstance(operation, str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,79}", operation) is not None
    if not known_name:
        operation = "unknown tool"
    if kind in (None, "other") and operation == "run_terminal_command":
        kind = "execute"
    if kind == "write":
        kind = "edit"
    read_only = kind == "read"
    namespace = meta.get("namespace")
    consistent = (
        known_name and call.keys() <= {"toolCallId", "kind", "name", "title", "status",
                                       "rawInput", "rawOutput", "locations", "content", "_meta"}
        and (metadata is None or (isinstance(metadata, dict) and metadata.keys() <= {"x.ai/tool"}
                                 and ("x.ai/tool" not in metadata or isinstance(native, dict))))
        and meta.keys() <= {"version", "name", "kind", "namespace", "label", "read_only", "input"}
        and ("version" not in meta or type(meta["version"]) is int and meta["version"] == 1)
        and (namespace in (None, "grok_build") or (namespace == "opencode" and operation == "write"))
        and (meta.get("kind") in (None, kind) or (meta.get("kind") == "write" and kind == "edit"))
        and all(value is None or value == operation for value in (call.get("name"), meta.get("name")))
        and call.get("status") in (None, "pending") and call.get("rawOutput") is None
        and meta.get("read_only", False) is read_only
    )

    paths, args, diffs, notes = [], {}, {}, []
    for source in (call.get("rawInput"), meta.get("input")):
        if source is None:
            continue
        if not isinstance(source, dict):
            consistent = False
            continue
        for key, value in source.items():
            if key in ("path", "file_path"):
                paths.append(value)
                key = "path"
            if key in args and (type(args[key]) is not type(value) or args[key] != value):
                consistent = False
            args[key] = value

    locations, content = call.get("locations"), call.get("content")
    if locations is not None:
        if isinstance(locations, list) and all(isinstance(entry, dict) for entry in locations):
            for entry in locations:
                paths.append(entry.get("path"))
                line = entry.get("line")
                consistent &= entry.keys() <= {"path", "line"} and (line is None or type(line) is int and line >= 0)
        else:
            consistent = False
    if content is not None:
        if not isinstance(content, list):
            consistent = False
        else:
            for block in content:
                if not isinstance(block, dict):
                    consistent = False
                    continue
                if block.get("type") == "diff":
                    path, before, after = block.get("path"), block.get("oldText"), block.get("newText")
                    paths.append(path)
                    if (block.keys() <= {"type", "path", "oldText", "newText"}
                            and isinstance(path, str) and path not in diffs
                            and isinstance(after, str) and (before is None or isinstance(before, str))):
                        diffs[path] = {"Before": before, "After": after}
                    else:
                        consistent = False
                else:
                    item = block.get("content")
                    if (block.keys() == {"type", "content"} and block["type"] == "content"
                            and isinstance(item, dict) and item.keys() == {"type", "text"}
                            and item["type"] == "text" and isinstance(item["text"], str)):
                        notes.append({"Tool message": item["text"]})
                    else:
                        consistent = False
    targets = list(dict.fromkeys(path for path in paths if isinstance(path, str) and path.strip() and "\x00" not in path))
    consistent &= all(isinstance(path, str) and path in targets for path in paths)
    summary = "\n".join([f"Operation: {operation}", *(f"Target: {_approval_literal(path)}" for path in targets)])
    if not consistent:
        return summary, "The effect can't be shown.", False

    header = {"Operation": operation, "Kind": kind, "Read only": read_only}
    if namespace is not None:
        header["Tool namespace"] = namespace
    if kind == "edit":
        if diffs and "path" in args and list(diffs) != [args["path"]]:
            return summary, "The native target does not match the file changes.", False
        changes = _approval_edits(operation, targets, diffs, args)
        if not changes:
            return summary, "The change can't be shown." if targets else "The Worker did not provide a target.", False
    elif kind == "execute":
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return summary, "The Worker did not provide a command.", False
        # block_until_ms (grok-build): how long the tool waits for the command, shown as given.
        wait = args.get("block_until_ms")
        if (operation not in ("execute", "run_terminal_command") or diffs or targets
                or args.keys() - {"command", "variant", "description", "is_background", "block_until_ms"}
                or args.get("variant", "Bash") != "Bash" or not isinstance(args.get("description", ""), str)
                or not isinstance(args.get("is_background", False), bool) or "\x00" in command
                or "block_until_ms" in args and not (type(wait) is int and wait >= 0)):
            return summary, "The effect can't be shown.", False
        changes = [{"Command": command, "Command type": "Bash", "Runs in background": args.get("is_background", False),
                    **({"Block until (ms)": str(wait)} if "block_until_ms" in args else {})}]
    elif (kind == "read" and operation in ("read", "read_file") and not diffs
          and targets == [args.get("path")] and args.keys() <= {"path", "variant"}
          and args.get("variant", "Read") == "Read"):
        changes = [{"Target": targets[0]}]
    else:
        # Locations and tool categories are presentation metadata. Unknown input schemas cannot be approved.
        return summary, "The effect can't be shown.", False

    if kind == "execute" or any(not Path(path).is_absolute() for path in targets):
        if not Path(workspace).is_absolute() or "\x00" in workspace:
            return summary, "The working folder can't be shown.", False
        header["Working folder"] = workspace
    effect = [header, *changes, *notes]
    details = _render_approval(effect)
    try:
        recovered = _parse_approval(details)
        # ACP text must have an exact UTF-8 representation, including on the browser's wire.
        for section in recovered:
            for value in section.values():
                if isinstance(value, str):
                    value.encode("utf-8")
        if recovered == effect:
            return summary, details, True
    except ValueError:
        pass
    return summary, "The effect can't be shown exactly.", False


def approval_sentence(call: dict, complete: bool) -> str:
    """A short question's action, from typed fields only; private contents stay in Details."""
    if not complete:
        return "The Worker wants to use a tool whose effect cannot be shown."
    meta = (call.get("_meta") or {}).get("x.ai/tool") or {}
    operation = meta.get("name") or call.get("name") or call.get("kind")
    args = {**(call.get("rawInput") or {}), **(meta.get("input") or {})}
    if operation in ("execute", "run_terminal_command"):
        return "The Worker wants to run a command on this Mac."
    paths = [args.get("path") or args.get("file_path")]
    paths += [block.get("path") for block in call.get("content") or [] if block.get("type") == "diff"]
    names = list(dict.fromkeys(Path(path).name for path in paths if isinstance(path, str)))
    # A long or control-bearing native filename is still available whole in Details.
    target = names[0] if len(names) == 1 and 0 < len(names[0]) <= 60 and names[0].isprintable() else "a file"
    if len(names) > 1:
        target = f"{len(names)} files"
    content = args.get("content")
    if operation in ("write", "edit") and isinstance(content, str):
        lines = len(content.splitlines())
        return f"The Worker wants to save {target} with {lines} {'line' if lines == 1 else 'lines'}."
    action = "read" if operation in ("read", "read_file") else "change"
    return f"The Worker wants to {action} {target}."


def _approval_request(pending: dict, workspace: str) -> tuple[str, str, bool, str]:
    """The full native request uses xPerfect's control digest encoding without a field projection."""
    native = pending.get("request")
    call = native.get("toolCall") if isinstance(native, dict) else None
    summary, details, can_allow = _approval_preview(call, workspace)
    try:
        full_request = json.dumps(pending, sort_keys=True, separators=(",", ":"), allow_nan=False)
        # Lone surrogates are not Unicode scalar values. A surrogate pair in a
        # Python string must also stay distinct from a single non-BMP character.
        if json.loads(full_request) != pending:
            raise ValueError("Invalid request text")
        json.dumps(pending, ensure_ascii=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        return summary, "The full request can't be shown exactly.", False, ""
    if (not isinstance(native, dict) or native.keys() - {"sessionId", "toolCall", "options"}
            or "sessionId" in native and not isinstance(native["sessionId"], str)):
        return summary, "The request has unknown fields.", False, full_request
    return summary, details, can_allow, full_request


# An answer that may not be one (Dreaming on this Mac's model, 30k of its 65k context, nothing cut): its model
# began a tool call without its call token, wrote its own markup as text and drifted into a chat reply; its harness took
# that turn for the answer, and xPerfect for a completed run. The tokens a model's vocabulary reserves for its own framing
# (typed control or user-defined: <|im_end|>, <think>, <tool_call>) are consumed by the server that frames its turns, so
# one in an answer is a sign its turn broke off. A real answer can quote one (docs, code, logs, notes), so text alone
# never fails or drops an answer: the outcome keeps it and says which (its "unframed": the marks), and each caller
# decides by its own outputs. Only for places on this Mac by their declared kind (XPerfect.here); the tokens are read
# from the model's own vocabulary through the server that runs it (Ollama), never from a list of words.
FRAMING_BYTES = 32 * 1024 * 1024  # the most of a vocabulary read (qwen3.6's, with its merges and scores: about 12 MB)
FRAMING_WAIT = 10.0  # s: the most a lookup takes of its caller's time (all of it a job's outcome has, which has none)
FRAMING_FETCH = 30.0  # s: one fetch of a vocabulary, in all, whoever waits for it
FRAMING_BACKOFF = (60.0, 3600.0)  # s: after a fetch fails, the next one waits this long, doubling up to the most
_FRAMING: dict[tuple[str, str], tuple[str, frozenset]] = {}  # (server, model) -> (its digest, its framing tokens)
_PENDING: dict[tuple[str, str], tuple] = {}  # (server, model) -> (event loop, the one fetch under way)
_RETRY: dict[tuple[str, str], tuple[float, float]] = {}  # (server, model) -> (no fetch before, the wait after the next)


def _markup(token) -> bool:
    """A reserved token shaped as markup (<...> or [...], no space in it): never a digit, a run of spaces or a word that
    a vocabulary marks as its own."""
    return (isinstance(token, str) and len(token) >= 3 and token[0] + token[-1] in ("<>", "[]")
            and not any(c.isspace() for c in token))


def _capped(method: str, url: str, body: dict | None, cap: int, seconds: float) -> bytes:
    """A response read whole within `cap` bytes and `seconds` in all (a server that drips is cut off too)."""
    end, got = time.monotonic() + seconds, bytearray()
    with httpx.Client(timeout=httpx.Timeout(min(seconds, 10.0))) as client:
        with client.stream(method, url, json=body) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                got += chunk
                if len(got) > cap or time.monotonic() > end:
                    raise ValueError(f"over {cap} bytes or {seconds:.0f} s")
    return bytes(got)


def _digest(base: str, model: str, seconds: float) -> str:
    """Which model the server has under this name now (its digest, Ollama's /api/tags): "" when unknown."""
    try:
        listed = json.loads(_capped("GET", f"{base}/api/tags", None, 1024 * 1024, seconds)).get("models") or []
    except (httpx.HTTPError, ValueError, OSError, AttributeError):
        return ""
    names = {model, model if ":" in model else f"{model}:latest"}
    return next((str(m.get("digest") or "") for m in listed if isinstance(m, dict)
                 and (m.get("name") in names or m.get("model") in names)), "")


def _array(text: str, key: str) -> list:
    """One array of a large JSON object, decoded alone (a vocabulary's merges and scores are never built)."""
    decoder, at = json.JSONDecoder(), 0
    while (at := text.find(f'"{key}":', at)) >= 0:  # (a key inside a string is escaped, \"key\" there: never found)
        at += len(key) + 3
        while at < len(text) and text[at] in " \t\r\n":
            at += 1
        try:
            found, _ = decoder.raw_decode(text, at)
        except ValueError:
            continue
        if isinstance(found, list):
            return found
    return []


def _read_framing(base: str, model: str) -> frozenset:
    try:
        text = _capped("POST", f"{base}/api/show", {"model": model, "verbose": True}, FRAMING_BYTES, FRAMING_FETCH).decode()
    except (httpx.HTTPError, ValueError, OSError, UnicodeDecodeError):
        return frozenset()
    tokens, kinds = _array(text, "tokenizer.ggml.tokens"), _array(text, "tokenizer.ggml.token_type")
    return frozenset(t for t, k in zip(tokens, kinds) if k in (3, 4) and _markup(t))  # (3 control, 4 user-defined)


async def _fetch(key: tuple[str, str], digest: str) -> frozenset:
    found = await asyncio.to_thread(_read_framing, *key)
    if found:
        _FRAMING[key] = (digest, found)
        _RETRY.pop(key, None)
        return found
    wait = min(FRAMING_BACKOFF[1], _RETRY[key][1] * 2) if key in _RETRY else FRAMING_BACKOFF[0]
    if key not in _RETRY:  # (said once a streak: an unchecked answer is never taken for a checked one)
        log.warning("%s at %s: its framing tokens could not be read; its answers are not checked (next try in %.0f s)",
                    key[1], key[0], wait)
    _RETRY[key] = (time.monotonic() + wait, wait)
    return found


async def framing(base: str, model: str, deadline: float) -> frozenset:
    """A model's own framing tokens (see above), as the server that runs it types them, within its caller's own time
    (deadline, on time.monotonic()). Read once for the model the server has under that name now (its digest: another
    model behind the same name is read again), by one fetch whoever asks at once; after a fetch fails, not again until
    its backoff. None when not read in time: nothing is checked then (the fetch goes on, for the next one)."""
    key, end = (base.rstrip("/"), model), min(deadline, time.monotonic() + FRAMING_WAIT)  # (one time for all of it)
    left = lambda: max(0.0, end - time.monotonic())  # noqa: E731
    if left() <= 0:
        return frozenset()
    try:
        digest = await asyncio.wait_for(asyncio.to_thread(_digest, *key, left()), left())
    except asyncio.TimeoutError:
        digest = ""
    kept = _FRAMING.get(key)
    if kept and (kept[0] == digest or not digest):  # (the same model, or the server could not say: the one known)
        return kept[1]
    if not digest or time.monotonic() < _RETRY.get(key, (0.0, 0.0))[0]:
        return frozenset()
    loop = asyncio.get_running_loop()
    pending = _PENDING.get(key)
    if pending is None or pending[0] is not loop or pending[1].done():
        pending = (loop, loop.create_task(_fetch(key, digest)))
        _PENDING[key] = pending
    try:
        return await asyncio.wait_for(asyncio.shield(pending[1]), left())
    except asyncio.TimeoutError:
        return frozenset()


def unframed(text: str, marks) -> list[str]:
    """The framing tokens in an answer, sorted (see above): a sign, never a verdict, that its turn broke off."""
    return sorted(m for m in marks if m in (text or ""))


def markup_line(marks: list[str]) -> str:
    """The one plain line a job's answer carries when its model's own markup appeared in it."""
    return f"(Its model's own markup ({' '.join(marks)}) appeared in this answer: it may have broken off before it was done.)"


# Workers on this Mac beside online ones (the settings page: both ticked under Workers; WORKERS_LOCAL=also,
# or =first when the one on this Mac is preferred). xPerfect runs a harness one way per instance (its endpoint,
# its model, how many jobs at once, and the one coordinator are the deployment's own settings), so the Workers on
# this Mac keep their own xPerfect on its own ports (brain/state-local, XPERFECT_LOCAL_STATE and _API, set by vx)
# and each job is sent to the place its Worker lives on, and stays there: it is remembered with the job.
LOCAL = "local"  # the Worker on this Mac, as a job names it beside xPerfect's own harness names


def mixed() -> bool:
    """Whether Workers on this Mac run beside online ones (two places)."""
    return (os.environ.get("WORKERS") == "signed-in" and os.environ.get("WORKERS_LOCAL") in ("also", "first")
            and bool(os.environ.get("XPERFECT_LOCAL_STATE")) and bool(os.environ.get("XPERFECT_LOCAL_API")))


def fallbacks() -> list[str]:
    """The harnesses a job runs on again, in order, when its own route is down: the others you chose (WORKER_FALLBACK,
    commas), for signed-in Workers only. The local profile declares none: nothing local ever moves online by itself."""
    if os.environ.get("WORKERS") != "signed-in":
        return []
    first = os.environ.get("WORKER_PROFILE", "")
    return [h for h in dict.fromkeys(os.environ.get("WORKER_FALLBACK", "").split(",")) if h and h != first]


def harnesses() -> list[str]:
    """Every Worker a job may go to: the one you prefer first, then the others you chose. With Workers on this
    Mac beside online ones, the one on this Mac is named LOCAL."""
    online = [os.environ.get("WORKER_PROFILE", "codex-cli"), *fallbacks()]
    if not mixed():
        return online
    return [LOCAL, *online] if os.environ["WORKERS_LOCAL"] == "first" else [*online, LOCAL]


def goes_local(harness: str = "") -> bool:
    """Whether a job runs on this Mac's own place of a mix: the Worker named for it, or unnamed, the one you prefer."""
    return mixed() and (harness or harnesses()[0]) == LOCAL


def on_this_mac(job: dict) -> bool:
    """Whether a saved job lives on the mix's place on this Mac. (All Workers on this Mac: that place is the
    only one, and the main one.)"""
    return job.get("place") == LOCAL and mixed()


# A Worker's harness, as xPerfect's provider of its accounts (Connections: "Connect another account")
PROVIDER = {"claude-code": "claude", "codex-cli": "codex", "grok-build": "grok"}


def route(harness: str, account: str = "") -> str:
    """One way a job can run: a harness on this Mac's own sign-in ("codex-cli"), or on an account you connected
    in xPerfect ("codex-cli@<account id>")."""
    return f"{harness}@{account}" if account else harness


def parts(token: str) -> tuple[str, str]:
    """A route as (harness, account id), the account "" for this Mac's own sign-in."""
    harness, _, account = (token or "").partition("@")
    return harness, account


def turned_off() -> set[str]:
    """The routes you turned off on the settings page (Accounts): never used, never logged out or deleted."""
    from core.state import setting
    off = setting("accounts_off", []) or []
    return {str(t) for t in off} if isinstance(off, list) else set()


def backups(first: str) -> list[str]:
    """Where a job runs again when its route is down: the other online Workers you chose, in order, and last the
    Worker on this Mac when it is ticked beside them. It stands by like the others: better done here than not at
    all (with every subscription at its limit, every job failed in seconds). A job on this Mac has
    none: nothing on this Mac moves online by itself."""
    if first == LOCAL:
        return []
    return [h for h in harnesses() if h not in (first, LOCAL)] + ([LOCAL] if mixed() else [])


def _config(local: bool = False) -> dict:
    return json.loads((Path(os.environ["XPERFECT_LOCAL_STATE" if local else "XPERFECT_STATE"]) / "config.json").read_text())


def job_text(job: str, part: str) -> Path:
    from core.state import STATE_ROOT
    return STATE_ROOT / "core" / "job-texts" / f"{job}-{part}.txt"


def keep_text(job: str, part: str, text: str) -> Path:
    """A job's own words kept for it, owner-only (0600), until it is told (forget_texts)."""
    path = job_text(job, part)
    from core.state import closed_dir
    closed_dir(path.parent)  # (0700 from the start)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # (a new file, 0600 before any byte is written)
    with os.fdopen(fd, "w") as out:
        out.write(text)
    os.replace(tmp, path)  # (whole, and never in a file anyone else could read)
    return path


def forget_texts(job: str) -> int:
    """Remove what was kept for a job once it is told (its brief, a long request, each answer's record and texts): how
    many files went."""
    gone = 0
    folder = job_text(job, "x").parent
    for path in [*folder.glob(f"{job}-*"), *folder.glob(f".{job}-*")]:  # (and a temp file a crash left)
        try:
            path.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def pictures_note(pictures: str) -> str:
    """A steer's or an answer's word on what makes pictures and videos now (brain/queen.py pictures_now), after their own
    words and apart from them: it replaces that part of the job's brief. "" when there is none to give."""
    return (f"\n\nPictures and videos, as their Settings stand now (this replaces what your brief says about them):\n"
            f"{pictures}") if pictures else ""


def exact(text: str, limit: int, job: str, part: str) -> str:
    """A job's words as one request to xPerfect carries them: whole when they fit its limit (always, but for a very
    long dictation with a very long conversation); else saved whole in this job's own file and referred to by its full
    path, with as much of the beginning as fits. Never cut without saying where the rest is (a Worker's goal was
    cut at 4,000 characters, and his words after that never reached it)."""
    if len(text) <= limit:
        return text
    path = keep_text(job, part, text)
    note = (f"[The whole text is {len(text):,} characters, more than one request to a Worker holds. Read this file first "
            f"and work from it, it is the exact text; what follows is only its beginning:\n{path}\n]\n\n")
    return note + text[:max(0, limit - len(note) - 1)]


_kept_private: set[Path] = set()  # (folders made owner-only by this process already)


def _owner_only(path: Path, files: tuple[str, ...] = (), tree: bool = False) -> None:
    """Owner-only (as core.state.private): this folder 0700 and the named files in it 0600; with tree,
    every folder and file under it too. A symbolic link is never followed or changed, and nothing else is touched (an
    xPerfect state's programs keep their own modes: the folder alone closes them to anyone else)."""
    import stat as st

    def close(target: Path, mode: int) -> None:
        try:
            if st.S_ISLNK(os.lstat(target).st_mode):
                return
            os.chmod(target, mode, **({"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}))
        except OSError:
            pass
    if path in _kept_private or not path.is_dir() or path.is_symlink():
        return
    _kept_private.add(path)
    close(path, 0o700)
    for name in files:
        close(path / name, 0o600)
    if tree:
        for folder, dirs, names in os.walk(path, followlinks=False):
            for name in dirs:
                close(Path(folder) / name, 0o700)
            for name in names:
                close(Path(folder) / name, 0o600)


def _private_states(state: Path) -> None:
    """His Workers' records and xPerfect's secrets stay his: this xPerfect's state, and the Codex home the Workers on
    this Mac use (its sessions are their conversations)."""
    _owner_only(state, files=("secrets.json", "unlock-password", "config.json"))
    codex = Path(__file__).resolve().parent / "codex-home-local"
    _owner_only(codex, files=("config.toml",))
    _owner_only(codex / "sessions", tree=True)


def _refusal(response: httpx.Response) -> dict | None:
    """xPerfect's typed "no room now" (HTTP 503, code host_capacity), every fact it gives: {"class", "dimension",
    "shortage", "available", "required", "retry_after"} (seconds, from Retry-After), else None."""
    if response.status_code != 503:
        return None
    try:
        detail = response.json().get("detail") or {}
    except ValueError:
        detail = {}
    if not isinstance(detail, dict) or detail.get("code") != "host_capacity":
        return {"class": "host", "retry_after": 2.0} if "host_capacity" in response.text else None
    try:
        wait = float(response.headers.get("Retry-After") or detail.get("retryAfter") or 2)
    except ValueError:
        wait = 2.0
    return {"class": str(detail.get("capacityClass") or "host"), "dimension": str(detail.get("dimension") or ""),
            "shortage": detail.get("shortage") or {}, "available": detail.get("available") or {},
            "required": detail.get("required") or {}, "retry_after": max(0.5, wait)}


def _facts(run: dict) -> dict:
    """The same facts for a run xPerfect holds to wait for room (its run record)."""
    def parsed(key: str) -> dict:
        try:
            value = json.loads(run.get(key) or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}
    return {"class": run.get("capacity_class") or run.get("failure_class") or "", "dimension": "",
            "shortage": parsed("capacity_shortage_json"), "available": parsed("capacity_available_json"),
            "required": parsed("capacity_required_json"), "retry_after": 0.0}


def reason(facts: dict) -> str:
    """Why there is no room, in plain words, from xPerfect's own facts: "this Mac is low on disk: 3.1 GB free, xPerfect
    needs 4.0 GB" (its resource guard), "every Worker place here is in use", "another project is running"."""
    kind, gb = facts.get("class", ""), lambda b: f"{int(b) / 1024 ** 3:.1f} GB"
    short, have, need = facts.get("shortage") or {}, facts.get("available") or {}, facts.get("required") or {}
    for key, what in (("diskBytes", "disk"), ("memoryBytes", "memory")):
        if short.get(key):
            free, wanted = have.get(key), need.get(key)
            return f"this Mac is low on {what}: " + (f"{gb(free)} free, xPerfect needs {gb(wanted)}" if free is not None
                                                     and wanted is not None else f"{gb(short[key])} short")
    for key, what in (("childProcesses", "programs running"), ("threads", "threads")):
        if short.get(key):
            return f"this Mac has too many {what} for xPerfect to start another"
    return {"family_lane": "every Worker place here is in use", "mutation_scope": "another project is running on this "
            "computer, and projects here run one at a time", "account": "this account's runs are all in use",
            "tenant": "every run allowed here is in use", "resource_pressure": "this Mac is short of memory or disk",
            "host_capacity": "this Mac is busy", "host_worker_busy": "this Worker is busy"}.get(kind, f"no room ({kind or 'busy'})")


def _refuse_live_for_tests(api: str, state: Path) -> None:
    """Workers of a test (any process with its own state folder: a test, a probe, an eval, the bench) are made only on
    an xPerfect of its own, never on his live one (its ports, or the live state folders vx sets up). His live Light is
    named, never inferred from folders: VX_RUNTIME=live, which vx exports to the processes it starts for his live
    Light; tests, probes, benches and clones never carry it. (Combined with core.state.live_reason where it is
    there.) Checked before anything else is done."""
    if os.environ.get("VX_RUNTIME") == "live":
        return  # (his live Light)
    where = urlsplit(api)
    if (where.hostname in ("127.0.0.1", "localhost", "::1") and where.port in LIVE_APIS) \
            or (state.name in LIVE_STATES and state.parent.name == "brain"):
        raise RuntimeError(f"a test's Workers never run on the live xPerfect ({api}); give it its own (tools/bench)")


def slots(local: bool = False) -> int:
    """How many jobs' Workers a place runs at once (xPerfect's mission lane, where the work runs; the rest wait):
    1 on this Mac's model, xPerfect's default 3 otherwise."""
    try:
        return max(1, int(_config(local)["env"].get("WPR_HOST_MISSION_SLOTS_PER_CLI", 3)))
    except (OSError, ValueError, KeyError):
        return 3


def _pending(turn: dict) -> bool:  # not answered yet: queued, running, or blocked for a retry
    if turn.get("blocker") in ROUTE_DOWN:  # its route is down: its Workers' own results stand, no waiting on it
        return False
    return not turn.get("response_json") and (not turn.get("blocker") or bool(turn.get("retry_after_at")))


def reports(local: bool = False) -> bool:
    """Whether a place's coordinator is woken to report its Workers' results (it is not on the local model)."""
    try:
        return bool(json.loads(_config(local)["env"].get("GLASSHIVE_COORDINATOR_CONFIG_JSON", "{}")).get("wake_on_results", True))
    except (OSError, ValueError, KeyError):
        return True


def settled(snap: dict, quiet_since: float | None = None, now: float | None = None, wait: float | None = None) -> dict | None:
    """A job's outcome once its background Queen has answered every turn and none of its Workers is still
    working, else None. A Worker's result wakes the coordinator to report it (a "worker_results" turn);
    if no report comes within REPORT_WAIT of the Workers finishing, or the report itself fails, the Workers'
    own results stand.
    A Worker that needs the user's input is told at once (that never wakes the coordinator)."""
    turns, goals = snap.get("turns") or [], snap.get("goals") or []
    if not turns:
        return None
    asking = [g for g in goals if g.get("state") == "needs_input"]
    if asking:
        return {"state": "needs_input", "goals": asking}
    if any(_pending(t) for t in turns) or any(g.get("state") not in DONE for g in goals):
        return None
    last = turns[-1]
    if goals and last.get("origin") != "worker_results":
        if quiet_since is None or (now or time.time()) - quiet_since < (REPORT_WAIT if wait is None else wait):
            return None  # the coordinator has not reported its Workers' results yet
        return {"state": "completed", "goals": goals, "output_text": ""}
    if goals and not last.get("response_json"):
        # Its Workers finished, and the coordinator's report of them failed (its own route down: a file
        # made on the backup was told as "failed"): the Workers' own results stand.
        return {"state": "completed", "goals": goals, "output_text": ""}
    if last.get("response_json"):
        reply = json.loads(last["response_json"])["choices"][0]["message"].get("content") or ""
        return {"state": "completed", "output_text": reply}
    return {"state": "cancelled" if last.get("blocker") == "cancelled" else "failed",
            "error_text": f"its background work ended: {last.get('blocker')}",
            **({"failure_class": last["blocker"]} if last.get("blocker") in ROUTE_DOWN else {})}


class XPerfect:
    def __init__(self, local: bool = False, title: str = PROJECT_TITLE) -> None:
        """local: the xPerfect of the Workers on this Mac, when they run beside online ones (see LOCAL). title: the
        project its Workers go in (THINKING_TITLE for the Subconscious' cortices)."""
        state = Path(os.environ["XPERFECT_LOCAL_STATE" if local else "XPERFECT_STATE"])
        api = os.environ["XPERFECT_LOCAL_API" if local else "XPERFECT_API"]
        _refuse_live_for_tests(api, state)  # (before any permission change, secret read or request)
        _private_states(state)
        token = json.loads((state / "secrets.json").read_text())["api_token"]
        self.http = httpx.AsyncClient(base_url=api, timeout=30, headers={"Authorization": f"Bearer {token}"})
        self.owner = ""
        self.project = ""
        self._accounts: tuple[float, list[dict] | None] | None = None
        self.local = local
        self.title = title
        self.state = state
        # The harness a Worker runs on here when none is named: this place's own (WORKERS_LOCAL_PROFILE: the one
        # brain/state-local is set up for), or the one you prefer.
        self.profile = os.environ.get("WORKERS_LOCAL_PROFILE", "claude-code") if local else os.environ.get("WORKER_PROFILE", "codex-cli")
        self.reporting = reports(local)

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        response = await self.http.request(method, path, json=body)
        if response.is_error:
            raise RuntimeError(f"xPerfect {response.status_code}: {response.text[:300]}")
        return response.json()

    async def _project(self) -> str:
        if not self.project:
            self.owner = (await self._call("GET", "/v1/me"))["user_id"]
            items = (await self._call("GET", "/v1/projects"))["items"]
            found = next((p for p in items if p.get("title") == self.title), None)
            if found is None:
                found = await self._call("POST", "/v1/projects", {
                    "owner_id": self.owner, "title": self.title,
                    "goal": "Work the Queen hands off during voice calls" if self.title == PROJECT_TITLE
                    else "Viventium's background cortices: each run thinks about one turn and changes nothing"})
            self.project = found["project_id"]
        return self.project

    slots = staticmethod(slots)  # (of the main place, or with True the mix's place on this Mac)

    async def accounts(self, *, require_known: bool = False) -> list[dict]:
        """The accounts connected in this xPerfect that are ready (Connections), oldest first; remembered 30 s."""
        now = time.monotonic()
        if self._accounts is None or now - self._accounts[0] > 30:
            try:
                items = (await self._call("GET", "/v1/provider-accounts")).get("items") or []
            except (httpx.HTTPError, RuntimeError):
                self._accounts = (now, None)
            else:
                ready = [a for a in items if str(a.get("status") or "").lower() == "ready"]
                self._accounts = (now, sorted(ready, key=lambda a: str(a.get("created_at") or "")))
        if require_known and self._accounts[1] is None:
            raise Unreachable("could not check connected Worker accounts")
        return self._accounts[1] or []

    async def routes(self, order: list[str]) -> list[str]:
        """Every way a job can run, in order: for each harness, this Mac's own sign-in, then each account you
        connected for that provider; none you turned off. LOCAL (the Worker on this Mac) stays as it is."""
        off, accounts, out = turned_off(), await self.accounts(), []
        for harness in order:
            if harness == LOCAL or harness not in PROVIDER:
                out.append(harness)
                continue
            mine = [route(harness, str(a["account_id"])) for a in accounts if a.get("provider") == PROVIDER[harness]]
            out += [t for t in [harness, *mine] if t not in off]
        return out

    async def submit(self, job: str, request: str, brief: str, profile: str = "", again: bool = False,
                     account: str = "", created=None) -> tuple[str, str]:
        """Admit a hand-off: a Worker with full use of this Mac, then a coordinator conversation whose first
        turn holds the job as its goal (saved before any model runs), and that goal dispatched to the Worker.
        The coordinator's own session only reaches its workspace (xPerfect's design) and, on the local model,
        did the work there instead of dispatching it: so the work always starts on the Worker, and the
        coordinator manages it. Its runs lift xPerfect's one-at-a-time fence: jobs run at the same time.
        The Worker is prepared, not started (xPerfect accepts it whatever runs now), and its run waits in xPerfect's
        own queue for a free slot when there is none. The goal, the brief and the turn carry the whole request
        and conversation (or an exact reference to the whole text: exact).
        With profile, the Worker runs on that harness (the one she picked for this job, or a backup). again: a
        backup run of the same job, after its route was down: the coordinator, whose own route is the one that
        is down, sits out as it does on the local model, and the Worker's own words are told.
        created(conversation id, Worker id): told as soon as the job's conversation exists, before its turn is
        admitted, so the caller keeps its routing even if this process ends in between (as think's started).
        Returns (conversation id, Worker id)."""
        project = await self._project()
        worker = await self._worker(f"Job {job}", profile, account, prepare=True, access=True, attended=True)
        turn = f"{job}-{route(profile, account)}" if again else job  # (a second admission of the same job needs its own key)
        brief = brief.replace("{worker}", worker)
        keep_text(job, "brief", brief)  # (a follow-up run reads it: answer)
        conversation = (await self._call("POST", "/v1/coordinator/conversations",
                                         {"scope": {"project_id": project},
                                          "owned_worker_ids": [worker]}))["conversation_id"]
        if created is not None:
            created(conversation, worker)
        admitted = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/turns", {
            "idempotency_key": turn, "goals": [{"id": GOAL, "text": exact(request, GOAL_LIMIT, job, "request")}],
            "message": exact(f"Goal {GOAL} of this job already runs on Worker {worker}, which has full use of this Mac; "
                             "its brief is below. Do not redo it yourself.\n\n" + brief, MESSAGE_LIMIT, job, "turn")})
        if admitted.get("state") == "blocked":
            raise RuntimeError(f"xPerfect did not accept it ({admitted.get('blocker')})")
        try:
            await self._call("POST", f"/v1/coordinator/conversations/{conversation}/dispatch",
                             {"goal_id": GOAL, "worker_id": worker, "instruction": exact(brief, MESSAGE_LIMIT, job, "brief")})
        except RuntimeError as e:  # (the coordinator dispatched it first: the work runs either way)
            if "already" not in str(e).lower() and "409" not in str(e):
                raise
        if not self.reporting or again:  # local: one GPU; the coordinator's runtime owns the job, its model sits out
            # (it redid the work in its sandbox, held the one session slot, and its results came after the
            # call)
            try:
                await self._call("POST", f"/v1/coordinator/conversations/{conversation}/turns/{turn}/stop", {})
            except RuntimeError as e:  # its run had moved on (409): nothing of the coordinator's left to stop, and
                if "409" not in str(e):  # the work already runs on its Worker ("could not start" for a job that ran)
                    raise
        return conversation, worker

    async def steer_goal(self, conversation: str, key: str, message: str) -> None:
        """A change for a job's running work: steered on its Worker itself (a native run steer), the job
        and its Worker unchanged. Its latest goal still at work is the one steered (a goal answered later, answer,
        is its own). xPerfect's 409 (its run moved on: a steer replaces the run) is read again and tried once more."""
        for attempt in (1, 2):
            goals = [g for g in (await self.job(conversation)).get("goals") or [] if g.get("state") not in DONE]
            if not goals:
                raise RuntimeError("its work is not running any more")
            goal = goals[-1]
            try:
                await self._call("POST", f"/v1/coordinator/conversations/{conversation}/goals/{goal['goal_id']}/control",
                                 {"action": "steer", "run_id": goal.get("control_run_id") or goal.get("run_id"),
                                  "idempotency_key": key, "message": message})
                return
            except RuntimeError as e:
                if attempt == 2 or not str(e).startswith("xPerfect 409"):
                    raise

    async def answer(self, conversation: str, key: str, words: str, question: str = "", job: str = "",
                     request: str = "", pictures: str = "", approval: dict | None = None) -> str:
        """Their answer to a job's Worker that asked them something: a follow-up goal of the same job, dispatched to the
        same Worker (its workspace, its sign-in, what it did so far), with their words exactly. Its run is the job's
        coordinator's like the first (it runs beside other work), and settle(goal_id=…) reads its outcome. A goal still
        at work takes the answer as a steer; one waiting (xPerfect's needs_input) is stopped first (one run at a time).
        Its instruction stands on its own (a harness may not keep its session across runs): the job's request, the path
        of its whole brief (kept at submit), the question and their answer. Sent again with the same key (and the same
        words), it is recovered by its exact goal id: a dispatch that never reached xPerfect is replayed, identical,
        to the original Worker. (xPerfect's goal control "message" is not offered for a goal dispatched to an existing
        Worker, as Light's are: it needs a delegation record.) pictures: what makes pictures and videos now, when the
        brief says otherwise (pictures_note), after their words either way. Returns the follow-up goal's id.
        A native approval is answered on its existing run and returns the current goal's id."""
        if approval is not None:
            choice = {"Allow once": "allow_once", "Deny": "reject_once"}.get(words)
            if approval["conversation"] != conversation or choice not in approval["choices"]:
                raise RuntimeError("That reply does not match the Worker's approval request.")
            fingerprint = approval.get("request_hash")
            if choice == "allow_once" and (approval.get("preview_complete") is not True
                                           or approval.get("preview_version") != APPROVAL_PREVIEW_VERSION
                                           or not isinstance(fingerprint, str)
                                           or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)):
                raise RuntimeError("The effect can't be shown.")
            if approval["expires_at"] <= time.time():
                raise RuntimeError(GROK_APPROVAL_EXPIRED)
            body = {key: approval[key] for key in ("run_id", "attempt_id", "request_id")}
            if choice == "allow_once":
                body["request_fingerprint"] = fingerprint
            response = await self.http.post(f"/v1/workers/{approval['worker_id']}/native-control",
                                            json={**body, "action": "permission", "option_id": approval["choices"][choice]})
            if response.status_code in (404, 409):
                raise RuntimeError("That approval request is no longer open.")
            response.raise_for_status()
            if response.json().get("status") != "permission_submitted":
                raise RuntimeError("That approval request is no longer open.")
            return approval["goal_id"]
        snap = await self.job(conversation)
        goals, turns = snap.get("goals") or [], snap.get("turns") or []
        goal = f"{GOAL}-{key}"[:160]
        mine = next((g for g in goals if g.get("goal_id") == goal), None)
        if mine and mine.get("run_id"):
            return goal  # (sent and dispatched already)
        record = job_text(job or goal, f"answer-{key}").with_suffix(".json")  # (this answer's exact binding, kept with the job)
        try:
            kept = json.loads(record.read_text())
        except (OSError, ValueError):
            kept = None
        if kept is None:
            bound = [g for g in goals if g.get("worker_id") and g.get("goal_id") != goal]
            if not bound or not turns:
                raise RuntimeError("this job has no Worker to answer")
            asked = bound[-1]
            said = f"Their answer, in their own words:\n\n{words}"
            if mine is None and asked.get("state") not in DONE:  # (still at work: the answer goes into it, nothing stopped)
                await self.steer_goal(conversation, key, said + pictures_note(pictures))
                return asked["goal_id"]
            brief = job_text(job, "brief") if job else None
            instruction = ("This is one job of Viventium's background work, going on after its Worker asked them something."
                           + (f"\n\nThe job, as she put it: {request}" if request else "")
                           + (f"\nIts whole brief (the conversation and their own words) is in this file; read it first:\n{brief}"
                              if brief and brief.exists() else "")
                           + f"\n\nIts Worker asked them{': ' + question if question else ' something'}.\n\n{said}"
                           + pictures_note(pictures) + "\n\nGo on with the job: the workspace and what was done so far "
                           "are as they were left.")
            kept = {"worker_id": asked["worker_id"], "asked_goal": asked["goal_id"], "asked_state": asked.get("state"),
                    "asked_run": asked.get("control_run_id") or asked.get("run_id"), "question": question, "said": said,
                    "instruction": exact(instruction, MESSAGE_LIMIT, job or goal, f"answer-{key}-instruction"),
                    "turn": turns[0]["turn_id"]}
            keep_text(job or goal, f"answer-{key}", json.dumps(kept)).rename(record)
        if mine is None and kept.get("asked_state") == "needs_input":  # (waiting: stopped, the answer starts the next run)
            await self._call("POST", f"/v1/coordinator/conversations/{conversation}/goals/{kept['asked_goal']}/control",
                             {"action": "stop", "run_id": kept["asked_run"], "idempotency_key": f"stop-for-{key}"[:160]})
        if mine is None:
            await self._call("POST", f"/v1/coordinator/conversations/{conversation}/goals",
                             {"turn_id": kept["turn"], "goals": [{"id": goal, "text": exact(kept["said"], GOAL_LIMIT, job or goal,
                                                                                          f"answer-{key}-goal")}]})
        got = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/dispatch",
                               {"goal_id": goal, "worker_id": kept["worker_id"], "instruction": kept["instruction"]})
        if not got.get("run_id"):  # (accepted but not started: not done)
            raise RuntimeError(f"xPerfect did not start the answer ({got.get('blocker') or got.get('state') or 'no run'})")
        return goal

    async def think(self, name: str, instruction: str, profile: str, effort: str = "", account: str = "",
                    wait: float = 900.0, started=None, owned: bool = False, role: str = "", dispatched=None) -> dict:
        """One short run of its own: a new Worker on this harness (and account) at this thinking effort, given one
        instruction, its answer read back, and the Worker closed again. For the Subconscious (brain/rounds.py): a
        cortex, or its coordinator; and the night routines (brain/night.py). {"state", "output_text",
        "failure_class", "error_text", "effort", "usage"}: the effort the run was accepted at and the tokens it used, as
        xPerfect reports them; "timeout" when it took longer than `wait` (it is stopped then). "unframed": the model's own
        markup found in its answer on this Mac (a sign its turn broke off; the answer is kept, its caller decides).
        started(worker id): told as soon as the Worker exists.
        It waits for room only within its own time (at most ROOM_WAIT, at xPerfect's pace), and never waits in line ahead
        of your work: PlaceBusy when there is still no room, or when xPerfect queues its run to wait (it is stopped then). Its route down (xPerfect holds the
        run behind that route's cooldown, typed): it ends at once with that class, so the caller can use the next.
        owned (a night routine): its run belongs to a coordinator goal of its own, so xPerfect's one-at-a-time fence for
        runs no goal owns neither holds it nor is held by it: only a free slot is needed. Its Worker carries the effort
        (a goal's run takes its Worker's), is prepared (accepted whatever runs), and the coordinator's own model sits
        out (its turn is stopped at once). Where the coordinator reports results (Hybrid, wake_on_results), xPerfect
        wakes it once when the run ends: one short report, read by no one.
        role: what this Worker is and what it may change, said truthfully by the caller (a night routine writes the
        Life folder by design); unset, a cortex's (it thinks about one turn and changes nothing). "run_state": its run's
        own state in xPerfect when this returned ("none": no run was dispatched): a "failed" outcome whose run still
        waits there (its route cooling down) is no run over.
        instruction may be a callable: it is made once the Worker exists, right before its run is dispatched (a cortex's
        words as they stand by his change list then, after any wait for room). started() returning False (its place was
        taken back for your work meanwhile: brain/rounds.Lane.started) dispatches nothing: "cancelled", gave_way.
        dispatched(worker), asked right after the dispatch returns: False (its place was taken back, or what it read was
        forgotten, meanwhile) stops the run there, and its stop is waited for like any end."""
        role = role or CORTEX_ROLE
        if owned:
            worker = await self._worker(name, profile, account, role=role, prepare=True, patient=False, access=True,
                                        env={EFFORT_ENV[profile]: effort} if effort and profile in EFFORT_ENV else None)
        else:  # (cortices of one round take turns at xPerfect's one-at-a-time fence, within their own time)
            worker = await self._worker(name, profile, account, role=role, room=min(wait, ROOM_WAIT))
        outcome: dict = {}
        try:
            if started is not None and started(worker) is False:  # (its place went to your work: nothing is dispatched)
                outcome = {"state": "cancelled", "output_text": "", "failure_class": "gave_way",
                           "error_text": "its place went to your work before it started", "run_state": "none"}
                return outcome
            if callable(instruction):
                instruction = instruction()
            if owned:
                run = {"run_id": await self._own(worker, instruction)}
            else:
                run = await self._call("POST", f"/v1/workers/{worker}/assign",
                                       {"instruction": instruction, **({"effort": effort} if effort else {})})
            if dispatched is not None and dispatched(worker, run.get("run_id", "")) is False:  # (taken back meanwhile:
                # it stops here)
                await self.interrupt(worker)
            deadline = time.monotonic() + wait
            while True:
                got = await self._call("GET", f"/v1/runs/{run['run_id']}")
                if got.get("state") in ("completed", "failed", "cancelled", "interrupted"):
                    outcome = {"state": got["state"], "run_state": got["state"], "output_text": got.get("output_text") or "",
                               "failure_class": got.get("failure_class") or "", "error_text": got.get("error_text") or "",
                               "effort": got.get("effort") or "", "usage": {k: got.get(k) or 0 for k in USAGE}}
                    if outcome["state"] == "completed" and (marks := unframed(outcome["output_text"],
                                                                               await self._framing(deadline))):
                        log.warning("%s: run %s: its model's own markup (%s) is in its answer: kept, said (unframed)", name,
                                    run["run_id"], " ".join(marks))
                        outcome["unframed"] = marks
                    return outcome
                if got.get("state") == "queued" and (got.get("failure_class") in CAPACITY_WAIT or got.get("capacity_class")):
                    facts = _facts(got)  # (xPerfect's own record of why it waits)
                    log.warning("%s: xPerfect queued it to wait for room (%s; shortage %s): %s; it gives its place back",
                                name, facts["class"], facts["shortage"], reason(facts))
                    await self.interrupt(worker)  # (an unstarted run: xPerfect cancels it exactly)
                    raise PlaceBusy(f"no room for it now: {reason(facts)} ({facts['class']})", facts["class"], facts)
                if got.get("state") == "queued" and got.get("failure_class") in ROUTE_DOWN:
                    await self.interrupt(worker)
                    outcome = {"state": "failed", "output_text": "", "failure_class": got["failure_class"],
                               "error_text": f"its route is down ({got['failure_class']})",
                               "run_state": "queued"}  # (its run still waits in xPerfect, behind the cooldown)
                    return outcome
                if time.monotonic() > deadline:
                    await self.interrupt(worker)
                    outcome = {"state": "timeout", "output_text": "", "failure_class": "", "error_text": "",
                               "run_state": got.get("state") or ""}
                    return outcome
                await asyncio.sleep(1.0)
        finally:
            closed = await self.close(worker)
            outcome["closed"] = closed
            if not closed:
                log.warning("%s: its Worker %s could not be closed; it stays in xPerfect's list", name, worker)

    async def _own(self, worker: str, instruction: str) -> str:
        """An owned run (think): a coordinator conversation of its own in this project, its one goal dispatched to
        this Worker, the coordinator's turn stopped at once (its model has nothing to do). Returns the run id."""
        project = await self._project()
        conversation = (await self._call("POST", "/v1/coordinator/conversations",
                                         {"scope": {"project_id": project}}))["conversation_id"]
        turn = f"{THINK_GOAL}-{worker}"
        admitted = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/turns", {
            "idempotency_key": turn, "goals": [{"id": THINK_GOAL, "text": exact(instruction, GOAL_LIMIT, worker, "goal")}],
            "message": f"Goal {THINK_GOAL} runs on Worker {worker}, its own. Do nothing yourself."})
        if admitted.get("state") == "blocked":
            raise RuntimeError(f"xPerfect did not accept it ({admitted.get('blocker')})")
        try:
            await self._call("POST", f"/v1/coordinator/conversations/{conversation}/turns/{turn}/stop", {})
        except RuntimeError as e:
            if "409" not in str(e):
                raise
        got = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/dispatch",
                               {"goal_id": THINK_GOAL, "worker_id": worker,
                                "instruction": exact(instruction, MESSAGE_LIMIT, worker, "instruction")})
        if not got.get("run_id"):
            raise RuntimeError(f"xPerfect did not start it ({got.get('blocker') or got.get('state')})")
        return got["run_id"]

    async def interrupt(self, worker: str) -> None:
        """Stop what a Worker is doing now (the Subconscious making room for your work)."""
        try:
            await self._call("POST", f"/v1/workers/{worker}/interrupt", {})
        except (httpx.HTTPError, RuntimeError):
            pass

    async def close(self, worker: str) -> bool:
        """Close a Worker that is done (its saved results stay): one cortex run leaves no Worker standing. Whether it
        was closed (a failure is the caller's to say, never taken as done)."""
        try:
            revision = int((await self._call("GET", f"/v1/workers/{worker}")).get("catalog_revision") or 1)
            await self._call("DELETE", f"/v1/workers/{worker}", {"confirm": True, "expected_catalog_revision": revision})
            return True
        except (httpx.HTTPError, RuntimeError, ValueError):
            return False

    async def _worker(self, name: str, profile: str = "", account: str = "",
                      role: str = "Worker for one of Viventium's background jobs", prepare: bool = False,
                      env: dict | None = None, patient: bool | None = None, room: float = 0.0,
                      access: bool = False, attended: bool = False) -> str:
        """A new idle host Worker in this project, on this profile's harness (or the one named), with full use
        of this Mac. account: an account connected in xPerfect, which this Worker then runs on (its own sign-in
        home), instead of this Mac's own sign-in.
        prepare (your work): the Worker is prepared without starting anything, and xPerfect accepts it whatever runs
        now (its slots full, or a night routine's run holding its one-at-a-time fence: patch 0007); its run then waits
        in xPerfect's queue for its turn. Without (a run of Light's own): it asks for room now, at xPerfect's own
        pace, and says there is none (PlaceBusy) after `room` seconds, instead of asking every 2 s for five minutes.
        env: this Worker's own settings (its thinking effort, EFFORT_ENV). patient: whether a refusal is waited out
        (your work, PREPARE_WAIT) or said after `room` seconds (Light's own runs); unset, as prepare.
        attended (submit): the local Grok sign-in is eligible only on a followed host job.
        access (submit, think owned): the held grant path, when enabled in a test."""
        project = await self._project()
        bundle = {**({"provider_account": {"policy": "personal_required", "account_id": account}} if account else {}),
                  **({"env": dict(env)} if env else {}),
                  **({"attended_external_auth": True}
                     if attended and not account and (profile or self.profile) == "grok-build" else {})}
        body = {"owner_id": self.owner, "name": name[:60], "role": role,
                "profile": profile or self.profile, "execution_mode": "host",
                **({"start_synchronously": False} if prepare else {}), **({"bootstrap_bundle": bundle} if bundle else {})}
        patient = prepare if patient is None else patient
        deadline, said = time.monotonic() + (PREPARE_WAIT if patient else room), False
        while True:
            response = await self.http.post(f"/v1/projects/{project}/workers", json=body)
            refused = _refusal(response)
            if refused is None:
                if response.is_error:
                    raise RuntimeError(f"xPerfect {response.status_code}: {response.text[:300]}")
                worker = response.json()["worker_id"]
                if (WORKER_ACCESS_GRANTS_ENABLED and access and (profile or self.profile) in WORKER_ACCESS_PROFILES
                        and os.environ.get("WORKER_GROK_SIGN_IN") != "1"):
                    try:
                        await self._grant(worker, name)
                    except BaseException:
                        await self.close(worker)  # (never left standing without the use it was made for)
                        raise
                return worker
            if not said:  # (once per wait, never per try)
                said = True
                log.warning("%s: xPerfect has no room (%s%s; shortage %s): %s", name, refused["class"],
                            f", {refused['dimension']}" if refused.get("dimension") else "", refused.get("shortage") or {},
                            reason(refused))
            left = deadline - time.monotonic()
            if refused["retry_after"] > left:  # (never asked again before xPerfect's own time; none left: said now)
                if patient:  # (only an xPerfect without patch 0007, or a lasting refusal: said plainly)
                    raise RuntimeError(f"no Worker could be created: {reason(refused)} ({refused['class']})")
                raise PlaceBusy(f"no Worker could be made: {reason(refused)} ({refused['class']})", refused["class"], refused)
            await asyncio.sleep(refused["retry_after"])

    async def _grant(self, worker: str, name: str) -> bool:
        """This Worker's owner grant, minted by xPerfect from Light's proof (WORKER_ACCESS_HOURS, the deny list in this
        place's xPerfect settings). Whether it was granted: no key or deny list here, or an xPerfect without the endpoint
        (no owner grant support), and the Worker runs ungranted, as before; any other refusal is raised."""
        path = self.state / GRANT_KEY
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("not this owner's private file")
            key = bytes.fromhex(path.read_text().strip())
            rules = json.loads(json.loads((self.state / "config.json").read_text())["env"].get("WPR_GROK_DENY") or "[]")
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("%s: no owner grant for its Grok Worker (%s): it runs as Grok asks", name, type(e).__name__)
            return False
        if not key or not rules:
            log.warning("%s: no owner grant for its Grok Worker (no key or no deny list): it runs as Grok asks", name)
            return False
        expires = round(time.time() + WORKER_ACCESS_HOURS * 3600, 3)
        response = await self.http.post(f"/v1/workers/{worker}/worker-access-grant", json={
            "expires_at": expires, "deny_rules": rules, "proof": _grant_proof(key, worker, expires, rules)})
        if response.status_code == 404:
            log.warning("%s: this xPerfect has no owner grant support. Its Grok Worker runs as Grok asks.", name)
            return False
        if response.is_error:
            raise RuntimeError(f"xPerfect refused the Grok Worker's owner grant ({response.status_code}): {response.text[:300]}")
        return True

    async def workspace(self, worker: str) -> str:
        try:
            return (await self._call("GET", f"/v1/workers/{worker}")).get("workspace_dir") or ""
        except (httpx.HTTPError, RuntimeError):
            return ""

    async def deliverables(self, goal: dict) -> list[dict] | None:
        """File identities from the run's publication record. None means the lookup failed."""
        worker, run = goal.get("worker_id") or "", goal.get("run_id") or ""
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,160}", identifier) for identifier in (worker, run)):
            return []
        try:
            async with asyncio.timeout(PUBLICATION_WAIT):
                record = await self._call("GET", f"/v1/workers/{worker}")
                if not isinstance(record, dict) or record.get("worker_id") != worker or not record.get("owner_id"):
                    return None
                return await asyncio.to_thread(self._deliverables, record, run, goal.get("active_attempt_id") or "")
        except FileNotFoundError:
            return []
        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
            log.info("publication lookup failed for run %s (%s)", run, type(error).__name__)
            return None

    async def publications(self, goals: list[dict]) -> dict:
        results = await asyncio.gather(*(self.deliverables(goal) for goal in goals))
        runs, files, pending = [], [], []
        for goal, found in zip(goals, results):
            if found is None:
                pending.append({key: goal.get(key) for key in ("worker_id", "run_id", "active_attempt_id")})
            else:
                runs.append(goal["run_id"])
                files.extend(found)
        return {"published_runs": runs, "deliverables": files, "pending_publications": pending}

    @staticmethod
    def _deliverables(worker: dict, run: str, attempt: str) -> list[dict]:
        workspace = Path(worker.get("workspace_dir") or "")
        state = Path(worker.get("state_dir") or "")
        if not workspace.is_absolute() or not state.is_absolute():
            return []
        # Host runtime _run_root() keeps its output_files manifest beside the
        # reported state directory. Its root_path is relative to workspace_dir.
        manifest = state.parent / "home" / ".glasshive-runs" / run
        with attachments.worker_directory(workspace) as directory:
            identity = attachments.worker_directory_identity(directory)
        with attachments.worker_directory(manifest) as directory:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open("native-image-scope.json", flags, dir_fd=directory), "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return []
                scope = json.load(source)
        expected = {"worker_id": worker["worker_id"], "owner_id": worker["owner_id"], "run_id": run,
                    "attempt_id": attempt, "workspace_dir": str(workspace), "file_output_transport": "artifact_sha256"}
        if not isinstance(scope, dict) or any(scope.get(k, "") != v for k, v in expected.items()):
            return []
        if not isinstance(items := scope.get("output_files"), list):
            return []
        files = []
        for item in items:
            if not isinstance(item, dict) or item.get("source_root", "workspace") != "workspace":
                continue
            name = item.get("root_path") or item.get("workspace_path")
            if not isinstance(name, str) or "\x00" in name:
                continue
            relative = Path(name)
            digest = item.get("sha256")
            if relative.parts and not relative.is_absolute() and ".." not in relative.parts \
                    and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest):
                files.append({"workspace": str(workspace), "workspace_identity": identity,
                              "relative": relative.as_posix(), "sha256": digest})
        return files

    async def say(self, conversation: str, key: str, message: str) -> None:
        """One more turn for a job's background Queen (a change, or the next request), saved at once."""
        admitted = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/turns",
                                    {"idempotency_key": key, "message": message})
        if admitted.get("state") == "blocked":
            raise RuntimeError(f"xPerfect did not accept it ({admitted.get('blocker')})")

    async def job(self, conversation: str) -> dict:
        return await self._call("GET", f"/v1/coordinator/conversations/{conversation}")

    async def working(self, conversation: str) -> bool:
        snap = await self.job(conversation)
        return any(_pending(t) for t in snap.get("turns") or []) or any(
            g.get("state") not in DONE for g in snap.get("goals") or [])

    async def _goal_wait(self, goal: dict) -> dict | None:
        """Whether this goal's own run waits for room, and why (its run record): {"state": "waiting", "reason", "facts",
        "goal_id"}, else None."""
        if goal.get("state") != "queued" or not goal.get("run_id"):
            return None
        try:
            run = await self._call("GET", f"/v1/runs/{goal['run_id']}")
        except (httpx.HTTPError, RuntimeError):
            return None
        if run.get("state") == "queued" and (run.get("failure_class") in CAPACITY_WAIT or run.get("capacity_class")):
            facts = _facts(run)
            return {"state": "waiting", "reason": reason(facts), "facts": facts, "goal_id": goal["goal_id"]}
        return None

    async def wait_reason(self, conversation: str) -> dict | None:
        """Whether a job's work waits for room now, and why, from xPerfect's own record of its latest waiting run:
        {"state": "waiting", "reason": "this Mac is low on disk: …", "facts": {…}, "goal_id"}, else None."""
        for goal in reversed((await self.job(conversation)).get("goals") or []):
            if (info := await self._goal_wait(goal)) is not None:
                return info
        return None

    async def _grok_approval(self, conversation: str, goal: dict, seen: tuple[str, ...]) -> dict | None:
        """Read the exact native permission request for this goal's current run."""
        worker, run = goal["worker_id"], goal.get("control_run_id") or goal.get("run_id")
        if not run:
            return None
        response = await self.http.get(f"/v1/workers/{worker}/native-control")
        if response.status_code in (404, 409):  # between runs, or xPerfect predates native controls
            return None
        response.raise_for_status()
        state = response.json()
        attempt = state.get("attempt_id")
        if state.get("run_id") != run or not attempt or goal.get("active_attempt_id") not in (None, "", attempt):
            return None
        pending = state.get("pending_requests") or []
        for item in pending:
            request_id, expires = item.get("request_id"), item.get("expires_at")
            if (request_id in seen or item.get("method") != "session/request_permission" or not isinstance(request_id, str)
                    or not re.fullmatch(r"[a-f0-9]{16,64}", request_id)
                    or not isinstance(expires, (int, float)) or not expires > time.time()):
                continue
            native = item.get("request")
            native = native if isinstance(native, dict) else {}
            options = native.get("options")
            options = [option for option in options if isinstance(option, dict)] if isinstance(options, list) else []
            choices = {"reject_once": None}  # ACP cancels if there is no unambiguous one-time reject.
            ids = [option.get("optionId") for option in options]
            for kind in ("allow_once", "reject_once"):
                matching = [option.get("optionId") for option in options if option.get("kind") == kind]
                if (len(matching) == 1 and isinstance(matching[0], str) and matching[0]
                        and ids.count(matching[0]) == 1):
                    choices[kind] = matching[0]
            workspace = await self.workspace(worker)
            summary, details, can_allow, full_request = _approval_request(
                item, workspace if isinstance(workspace, str) else "")
            if not can_allow:
                choices.pop("allow_once", None)
            digest = hashlib.sha256(full_request.encode("ascii")).hexdigest() if full_request else None
            return {"state": "needs_input", "output_text": summary, "approval_details": details,
                    "approval_request": full_request,
                    "approval_sentence": approval_sentence(native.get("toolCall") or {}, can_allow),
                    "approval": {"conversation": conversation, "worker_id": worker, "run_id": run,
                                 "attempt_id": attempt, "request_id": request_id, "goal_id": goal["goal_id"],
                                 "expires_at": expires, "choices": choices, "request_hash": digest,
                                 "preview_complete": can_allow, "preview_version": APPROVAL_PREVIEW_VERSION,
                                 "kind": kind if isinstance(kind := (native.get("toolCall") or {}).get("kind"), str)
                                 else ""}}
        return None

    async def settle(self, conversation: str, own_words: bool = False, goal_id: str = "", waiting=None,
                     prior_runs: list[str] = (), grok_worker: str = "", seen_approval: tuple[str, ...] = ()) -> dict:
        """Wait for a job's outcome (see settled): {"state", "output_text" or "error_text"}. A job whose work
        failed because its route is down ends at once with its failure class and run id, so it can
        run on the declared fallback instead of waiting on a provider. own_words: its coordinator sits out.
        goal_id: only that goal's outcome (a follow-up, answer), in its Worker's own words (the coordinator's reports
        of earlier goals are not its outcome). xPerfect not answering for a minute: Unreachable (typed). An answer with
        its model's own markup in it is kept, with one plain line that says so ("unframed": the marks).
        waiting(info): told once each time its work starts waiting for room, with the reason (wait_reason), so the job
        is said to be waiting, never "underway"; the wait is logged once, never per poll. An `approval` outcome carries
        a live native request. The caller shows it and resumes settlement with its request id."""
        failures, quiet_since, waiting_now = 0, None, set()
        while True:
            try:
                snap = await self.job(conversation)
                failures = 0
            except (httpx.HTTPError, RuntimeError) as e:  # a restarting xPerfect is not a failed job
                failures += 1
                if failures > 60:
                    raise Unreachable(f"xPerfect did not answer for a minute ({type(e).__name__})") from e
                await asyncio.sleep(1.0)
                continue
            if goal_id:
                snap = {**snap, "goals": [g for g in snap.get("goals") or [] if g.get("goal_id") == goal_id],
                        "turns": [t for t in snap.get("turns") or [] if t.get("origin") != "worker_results"]}
                own_words = True
            goals = snap.get("goals") or []
            held = [g for g in goals if g.get("state") == "queued" and g.get("failure_class") in CAPACITY_WAIT]
            now_held = {(g.get("goal_id"), g.get("run_id")) for g in held}
            for goal in held:
                if (goal.get("goal_id"), goal.get("run_id")) not in waiting_now:  # (each wait said once, its own reason)
                    info = await self._goal_wait(goal) or {"state": "waiting", "goal_id": goal.get("goal_id"),
                                                           "facts": {"class": goal["failure_class"]},
                                                           "reason": reason({"class": goal["failure_class"]})}
                    log.warning("job %s waits for room: %s (%s)", conversation, info["reason"], info["facts"].get("class"))
                    if waiting is not None:
                        waiting(info)
            waiting_now = now_held
            for goal in goals:
                # While a route cools down xPerfect holds its Worker's run queued, with the class that put it there
                # (a job sat 3 minutes behind Claude's limit, then failed): that is the route down too.
                if goal.get("failure_class") in ROUTE_DOWN and goal.get("state") in ("queued", "claimed"):
                    return {"state": "route_down", "failure_class": goal["failure_class"],
                            "run_id": goal.get("control_run_id") or goal.get("run_id")}
                if goal.get("state") in ("failed", "blocked"):
                    failure = goal.get("failure_class") or (await self._call(
                        "GET", f"/v1/coordinator/conversations/{conversation}/goals/{goal['goal_id']}/result?max_chars=200")).get("failure_class")
                    if failure in ROUTE_DOWN:
                        return {"state": "route_down", "failure_class": failure,
                                "run_id": goal.get("control_run_id") or goal.get("run_id")}
                    if failure == "native_input_expired":
                        return {"state": "failed", "failure_class": failure, "error_text": GROK_APPROVAL_EXPIRED}
                if grok_worker and goal.get("worker_id") == grok_worker and goal.get("state") == "running":
                    if offer := await self._grok_approval(conversation, goal, seen_approval):
                        return offer
            quiet_since = (quiet_since or time.time()) if goals and all(g.get("state") in DONE for g in goals) else None
            if (outcome := settled(snap, quiet_since, wait=None if self.reporting and not own_words else 0)) is not None:
                said = [await self.goal_result(conversation, goal["goal_id"])  # a Worker's own words: its question,
                        for goal in outcome.pop("goals", [])]                   # or an unreported result
                if outcome["state"] == "completed":
                    runs = [goal for goal in goals if goal.get("state") == "completed" and goal.get("run_id")
                            and goal.get("worker_id") and goal["run_id"] not in prior_runs]
                    if runs:
                        outcome.update(await self.publications(runs))
                return await self._framed(conversation, outcome, said)
            await asyncio.sleep(1.5)

    def here(self) -> bool:
        """Whether this place's Workers run on this Mac's own model, by its declared kind: the place on this Mac beside
        online ones (local: brain/state-local, also every job's last backup), or the only place when all Workers are on
        this Mac (WORKERS=local). Never because an endpoint is set (a test's fault sets an online one)."""
        return self.local or os.environ.get("WORKERS") == "local"

    async def _framing(self, deadline: float) -> frozenset:
        """This place's Workers' model framing (see framing), on this Mac only: its models (both harnesses' one) on the
        server vx serves them from (its endpoint, WPR_CLAUDE_CODE_BASE_URL), within the caller's time."""
        if not self.here():
            return frozenset()
        try:
            config = json.loads((self.state / "config.json").read_text())
        except (OSError, ValueError):
            return frozenset()
        base = (config.get("env") or {}).get("WPR_CLAUDE_CODE_BASE_URL", "")
        found = frozenset()
        for model in sorted({m for m in (config.get("models") or {}).values() if m}) if base else ():
            found |= await framing(base, model, deadline)
        return found

    async def _framed(self, conversation: str, outcome: dict, said: list[str]) -> dict:
        """A job's outcome with its Workers' own words (settle), every one kept. When its model's own markup appeared in
        any of it (its coordinator's reply, or a Worker's), one plain line says so, and "unframed" names the marks."""
        for text in said:
            outcome["output_text"] = (outcome.get("output_text", "") + "\n" + text).strip()
        if not (outcome.get("output_text") or "").strip():
            return outcome
        marks = unframed(outcome["output_text"], await self._framing(time.monotonic() + FRAMING_WAIT))
        if marks:
            log.warning("job %s: its model's own markup (%s) is in its answer: kept, said in one line", conversation,
                        " ".join(marks))
            outcome.update(output_text=f"{outcome['output_text']}\n{markup_line(marks)}", unframed=marks)
        return outcome

    async def goal_result(self, conversation: str, goal: str) -> str:
        """A Worker's own words, whole: read page by page as xPerfect gives them (it was cut at 6,000 characters)."""
        text, offset = "", 0
        try:
            while True:
                got = await self._call("GET", f"/v1/coordinator/conversations/{conversation}/goals/{goal}/result"
                                              f"?offset={offset}&max_chars={RESULT_PAGE}")
                text += got.get("output_text") or ""
                after = got.get("next_offset")
                if not isinstance(after, int) or after <= offset:
                    return text
                offset = after
        except (httpx.HTTPError, RuntimeError) as e:
            return (text + f"\n(the rest of its result could not be read: {str(e)[:120]})" if text
                    else f"(its result could not be read: {str(e)[:120]})")

    async def stop(self, conversation: str, *, run_id: str = "") -> dict | None:
        """Request stop and return the snapshot only once the coordinator and its Workers cannot act."""
        # The runtime closes only workers whose native ownership records prove
        # exclusivity. Existing/shared workers keep exact conversation/run scope.
        final = await self._call("POST", f"/v1/coordinator/conversations/{conversation}/stop",
                                 {"close_workers": True})
        if final.get("state") != "stopped" or final.get("confirmation_pending") is not False:
            return None
        if run_id and not any(g.get("run_id") == run_id for g in final.get("goals") or []):
            # A replacement can change the snapshot's run. It cannot prove that the original ended.
            prior = await self._call("GET", f"/v1/runs/{run_id}")
            if prior.get("run_id") != run_id or prior.get("state") not in TERMINAL_RUN:
                return None
            final["prior_run"] = prior
        return final

    async def continuation(self, conversation: str, stopped: dict) -> dict:
        """The prior runs' own results and run-scoped receipts, for a replacement Worker."""
        receipts = []
        goals = list(stopped.get("goals") or [])
        if prior := stopped.get("prior_run"):
            if not any(g.get("control_run_id") == prior["run_id"] for g in goals):
                goals.append({"goal_id": GOAL, **prior})
        for goal in goals:
            worker = goal.get("worker_id")
            for run in dict.fromkeys(filter(None, (goal.get("run_id"), goal.get("control_run_id")))):
                record = {"run_id": run, "worker_id": worker, "state": goal["state"]}
                try:
                    native = await self._call("GET", f"/v1/runs/{run}")
                    if native.get("run_id") == run and native.get("worker_id") == worker:
                        record.update({key: native[key] for key in (
                            "state", "started_at", "runtime_invoked_at", "ended_at", "failure_class",
                            "output_text", "active_attempt_id") if key in native})
                    result = await self._call("GET", f"/v1/coordinator/conversations/{conversation}/goals/"
                                              f"{goal['goal_id']}/result?run_id={run}&max_chars=200")
                    if result.get("run_id") == run and result.get("current_workspace_files"):
                        record["result_files"] = result["current_workspace_files"]
                except (RuntimeError, httpx.HTTPError):
                    record["result_lookup"] = "unavailable"
                if worker:
                    files = await self.deliverables({**goal, **record})
                    record["published_files"] = files
                    if workspace := await self.workspace(worker):
                        record["workspace"] = workspace
                        record["native_evidence_path"] = str(Path(workspace) / "glasshive-run" / "runs" / run / "evidence.json")
                    try:
                        events = await self._call("GET", f"/v1/workers/{worker}/events")
                        record["events"] = [{key: e.get(key) for key in ("event_id", "event_type", "message", "created_at")}
                                            for e in events.get("items") or [] if e.get("run_id") == run]
                    except (RuntimeError, httpx.HTTPError):
                        record["events"] = None
                receipts.append(record)
        return {"conversation_id": conversation, "runs": receipts}
