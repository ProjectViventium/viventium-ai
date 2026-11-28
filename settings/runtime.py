"""The adapter between her settings and what really runs on this Mac: vx, the Keychain, each Worker harness's
own sign-in, and her own state. Nothing here knows what a choice means (settings/catalog.py) or where it is
kept (settings/store.py); it only looks, checks and starts.

A saved change that needs her restarted never interrupts you: it waits until your choices have settled, until
no call is live and until no background job is running, and only then restarts her (./vx restart, which checks
first that the new setup can start).

When something does not work, the page is told in plain words what did not change and what to do, if anything; never
a path, a command or a program's own output. That technical line goes to her settings log (logs/settings.log).

vx is the one at the settings root: this checkout's, a test's stand-in, or the test bench's own entry
(tools/bench/bench.py writes it), which restarts only the bench's parts and never this Mac's own (VX_SETTINGS_BENCH).
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from core.harness_status import Connection, connection
from settings import catalog, install, store
from settings.store import ROOT, clean_env, private_open, private_write, read

OFFLINE = os.environ.get("VX_SETTINGS_OFFLINE") == "1"  # tests: no Keychain, no network, no harness CLIs
# The test bench's page (tools/bench/bench.py): the menu bar, starting with this Mac and the app are this Mac's own and
# his Light's; the bench never changes them, and says so.
BENCH = os.environ.get("VX_SETTINGS_BENCH") == "1"
LOGS = ROOT / "logs"
CODE = Path(__file__).resolve().parents[1]  # (this checkout's code: her state is read from here, whatever the settings root)
SETTLE = float(os.environ.get("VX_SETTINGS_SETTLE", "4"))  # s: choices made in a row are applied together


def vx(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """One call to the vx at the settings root. Never raises: a vx that cannot be run, or that does not finish in time,
    comes back as a failed run whose own words say why (for her settings log, never for the page)."""
    try:
        return subprocess.run(["/bin/bash", str(ROOT / "vx"), *args], cwd=ROOT, env=clean_env(), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        said = "\n".join(x.decode(errors="replace") if isinstance(x, bytes) else x for x in (e.stdout, e.stderr) if x)
        return subprocess.CompletedProcess(e.cmd, 124, said, f"no answer in {timeout} s")
    except OSError as e:
        return subprocess.CompletedProcess(["vx", *args], 127, "", str(e))


def logged(what: str, detail: str) -> None:
    """The technical side of something that did not work (a program's own words, an exit code, a path), kept in her
    settings log for whoever looks into it. The page is told only, in plain words, what did not change."""
    lines = " | ".join(line.strip() for line in str(detail).splitlines() if line.strip())
    try:
        with private_open(LOGS / "settings.log", "a") as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {what}: {lines[-4000:] or 'no words'}\n")
    except OSError:
        pass


def ran(what: str, done: subprocess.CompletedProcess) -> bool:
    """Whether a vx call worked; when it did not, its own words go to her settings log."""
    if done.returncode == 0:
        return True
    logged(what, f"exit {done.returncode}\n{done.stdout or ''}\n{done.stderr or ''}")
    return False


def alive(pid_file: Path) -> bool:
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def profile_now() -> str:
    return read(LOGS / "profile").strip() or "local"


# -- What this Mac has: keys (by name only), sign-ins, local models --

def key_item(name: str, env: dict) -> str:
    """The Keychain item a key lives in, as vx names it (NAME_ITEM in a private profile file overrides)."""
    provider = name.removesuffix("_API_KEY").lower()
    return env.get(f"{name}_ITEM") or f"viventium/{'x_ai' if provider == 'xai' else provider}_api_key"


XP_API = "http://127.0.0.1:8866"  # the xPerfect her online Workers run on (brain/state-cloud; vx xp_ports)


# An added account's sign-in that Light started ends by itself if it is not finished in this time: it never runs on
# without end, holding its own sign-in open for a browser nobody is at. Then the page offers to sign in again.
SIGN_IN_WAIT = float(os.environ.get("VX_SIGN_IN_WAIT") or 600)


@contextlib.contextmanager
def locked(name: str):
    """One at a time across every process of hers that changes this (each page click is a process of its own)."""
    with private_open(LOGS / f"{name}.lock", "a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _sign_in_stamp(account_id: str) -> Path:
    return LOGS / "sign-ins" / f"{account_id}.json"


def bound_sign_in(account_id: str) -> None:
    """The sign-in of an added account, just started here, ends by itself: a small helper of its own (python -m
    settings end-sign-in) waits SIGN_IN_WAIT, then asks xPerfect whether that sign-in still runs and, if it does, ends
    it through xPerfect's own route. A newer start of the same account's sign-in replaces this one's stamp, so this
    helper never ends that newer one."""
    started = f"{time.time():.3f}"
    private_write(_sign_in_stamp(account_id), json.dumps({"started": started}))
    names = ("VX_STATE", "VX_LOGS", "VX_SETTINGS_ROOT", "VX_SETTINGS_OFFLINE", "VX_SETTINGS_BENCH", "XPERFECT_STATE",
             "XPERFECT_API", "PYTHONPATH")
    env = {**clean_env(), **{k: os.environ[k] for k in names if os.environ.get(k)}}
    subprocess.Popen([sys.executable, "-m", "settings", "end-sign-in", account_id, started, f"{SIGN_IN_WAIT:g}"], cwd=CODE,
                     env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def end_sign_in(account_id: str, started: str, wait: float) -> None:
    """The helper bound_sign_in starts: after `wait`, the sign-in it was started for, if it still runs, is ended."""
    time.sleep(max(0.0, wait))
    try:
        if json.loads(_sign_in_stamp(account_id).read_text()).get("started") != started:
            return  # (a newer start of it since: that one has its own helper)
    except (OSError, ValueError):
        return
    try:
        if xperfect("GET", f"/v1/provider-accounts/{account_id}/setup").get("status") == "connecting":
            xperfect("POST", f"/v1/provider-accounts/{account_id}/setup/cancel")
            logged("ending an unfinished sign-in", f"{account_id}: not finished in {wait:g} s; ended, to be signed in again")
    except RuntimeError as e:
        logged("ending an unfinished sign-in", f"{account_id}: {type(e).__name__}: {e}")
    with contextlib.suppress(OSError):
        _sign_in_stamp(account_id).unlink()


def xperfect(method: str, path: str, body: dict | None = None, timeout: float = 15) -> dict:
    """One call to the xPerfect her online Workers run on, whose Connections keep the accounts you add on this
    page: each its own sign-in, in its own home, apart from this Mac's own (which nothing here changes). Raises
    RuntimeError in xPerfect's own words when it refuses, or when it is not answering."""
    if OFFLINE:
        return _xperfect_stand_in(method, path, body)
    import urllib.error
    try:
        state = Path(os.environ["XPERFECT_STATE"]) if BENCH else ROOT / "brain" / "state-cloud"
        api = os.environ["XPERFECT_API"] if BENCH else XP_API
        token = json.loads((state / "secrets.json").read_text())["api_token"]
        request = urllib.request.Request(api + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        try:
            detail = str(json.loads(detail).get("detail", detail))
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(detail) from None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        raise RuntimeError("Her Workers' xPerfect is not answering.") from None


def _xperfect_stand_in(method: str, path: str, body: dict | None) -> dict:
    """Tests: xPerfect's Connections as a file (logs/xp-accounts.json); a test marks an account ready itself."""
    kept = LOGS / "xp-accounts.json"
    items = json.loads(kept.read_text()) if kept.exists() else []
    parts = path.strip("/").split("/")  # v1 provider-accounts [id [setup [input]]]
    out: dict = {}
    if parts[:2] != ["v1", "provider-accounts"]:
        raise RuntimeError("not in the stand-in")
    if len(parts) == 2 and method == "GET":
        return {"items": items}
    if len(parts) == 2 and method == "POST":
        out = {"account_id": f"acct_{len(items) + 1}", "provider": body["provider"], "label": body["label"],
               "auth_method": body["auth_method"], "status": "disconnected", "created_at": f"2026-11-13T00:00:{len(items):02d}"}
        items.append(out)
    else:
        found = next((a for a in items if a["account_id"] == parts[2]), None)
        if found is None:
            raise RuntimeError("Provider account not found for this user")
        if len(parts) == 3 and method == "DELETE":
            if found["status"] not in ("disconnected",):
                raise RuntimeError("Disconnect the provider account before forgetting it")
            items.remove(found)
        elif parts[3:] == ["disconnect"]:
            found["status"] = "disconnected"
        elif parts[3:] == ["setup", "cancel"]:
            if found["status"] != "connecting":
                raise RuntimeError("Provider account setup is not running")
            found["status"] = "action_required"  # (as xPerfect: a cancelled sign-in needs one again)
        elif parts[3:] == ["setup"] and method == "POST":
            found["status"] = "connecting"
            found.pop("ended", None)
            out = {"status": "connecting", "setup_url": "https://example.test/sign-in", "setup_code": "", "input_required": False}
        elif parts[3:] == ["setup"] and method == "GET":
            # As xPerfect: while a sign-in runs, where to finish it; once none runs (a test marks it "ended"), a
            # check of that home, which says "complete" whether or not it signed in.
            if found["status"] == "connecting" and not found.get("ended"):
                out = {"status": "connecting", "complete": False, "setup_url": "https://example.test/sign-in",
                       "setup_code": "", "input_required": False}
            else:
                found["status"] = "ready" if found["status"] == "ready" else "action_required"
                found.pop("ended", None)
                out = {"status": found["status"], "complete": True}
        elif parts[3:] == ["setup", "input"]:
            found["input"] = "given"
    private_write(kept, json.dumps(items))
    return out


def has_key(name: str, env: dict) -> bool:
    """Whether Light has this key to use: in the Keychain (or the environment), and not one you turned off."""
    if name in env.get("KEYS_OFF", "").split() or (name == "OPENAI_API_KEY" and own_is_off(name)):
        return False
    return key_kept(name, env)


def key_kept(name: str, env: dict) -> bool:
    """Whether the key is in this Mac's Keychain (or the environment), whether or not Light uses it."""
    if OFFLINE or BENCH:
        return name in os.environ.get("VX_SETTINGS_KEYS", "").split()
    return bool(os.environ.get(name)) or subprocess.run(
        ["security", "find-generic-password", "-s", key_item(name, env)], capture_output=True).returncode == 0


def add_key(name: str, value: str, env: dict) -> str:
    """Keep a key in this Mac's Keychain. It is never written to a file, a log or a process list, and never
    comes back out through the page. Returns "" or why not, in plain words."""
    if name not in catalog.KEY_NAMES:
        return "That key is not one Viventium uses."
    if not re.fullmatch(r"[A-Za-z0-9._\-]{16,300}", value or ""):
        return "That does not look like a key."
    if OFFLINE:
        return ""
    command = f'add-generic-password -U -s "{key_item(name, env)}" -a viventium-light -w "{value}"\n'
    done = subprocess.run(["security", "-i"], input=command, capture_output=True, text=True, timeout=20)
    return "" if done.returncode == 0 and not done.stderr.strip() and key_kept(name, env) else "The Keychain did not take it."


def first_run_key(value: str, env: dict, name: str = "OPENAI_API_KEY") -> str:
    """Save and turn on the key the person chose in the first-run window."""
    try:
        if why := add_key(name, value, env):
            return why
    except (OSError, subprocess.TimeoutExpired):
        return "The Keychain did not take it."
    try:
        profile = env.get("PROFILE") or "local"
        base, machine, own = store.files(profile)
        for path, sources in ((machine, (base, machine)), (own, (base, machine, own))):
            off = store.shell_values([store.read(f) for f in sources], ["KEYS_OFF"]).get("KEYS_OFF", "").split()
            if name in off:
                block = store.split(store.read(path))[1]
                block["KEYS_OFF"] = " ".join(key for key in off if key != name)
                store.save_block(path, block)
        own_off(name, False)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "The key was saved. Viventium could not turn it on. Try again."
    return ""


def signed_in(name: str) -> bool:
    """Whether a Worker harness is signed in, asked of its own CLI (remembered for a minute: the page asks often)."""
    if OFFLINE or BENCH:
        return name in os.environ.get("VX_SETTINGS_SIGNED_IN", "").split()
    cache, spec = LOGS / "settings-signins.json", catalog.SIGN_INS[name]
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    if name != "grok" and name in known and time.time() - known[name]["t"] < 60:
        return known[name]["ok"]
    ok = False
    if tool := install.tool_path(name):
        try:
            done = subprocess.run([tool, *spec["check"][1:]], capture_output=True, text=True, timeout=20, env=clean_env(), cwd=ROOT)
            ok = done.returncode == 0 and connection(name, done.returncode) == Connection.CONNECTED
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    known[name] = {"ok": ok, "t": time.time()}
    private_write(cache, json.dumps(known))
    return ok


def signed_in_as(name: str, account_id: str = "") -> str:
    """Who a subscription sign-in is, as a short hash of the person and their workspace (the address itself is never
    shown or kept): this Mac's own sign-in, or an account you added in xPerfect (its own home). Two sign-ins with the
    same hash are one account, so the second is no backup: one limit stops both. Read from each tool's own record of
    who signed in (Codex: its sign-in's identity token; Claude Code: `claude auth status`, which changes nothing);
    "" when it cannot be told (Grok, or not signed in). Remembered for a minute: the page asks often."""
    key = f"{name}:{account_id or 'own'}"
    if OFFLINE or BENCH:  # (tests say who each sign-in is, in a file)
        try:
            return str(json.loads((LOGS / "xp-identities.json").read_text()).get(key, ""))
        except (OSError, ValueError):
            return ""
    cache = LOGS / "settings-identities.json"
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    if key in known and time.time() - known[key]["t"] < 60:
        return known[key]["who"]
    home = None
    if account_id:  # (xPerfect keeps each account's home under its own state: data/provider_accounts/<tenant>/<owner>/<id>)
        home = next(iter(sorted((ROOT / "brain" / "state-cloud" / "data" / "provider_accounts").glob(f"*/*/{account_id}"))), None)
    who = "" if account_id and home is None else _who(name, home)
    known[key] = {"who": who, "t": time.time()}
    private_write(cache, json.dumps(known))
    return who


def _who(name: str, home: Path | None) -> str:
    def short(*parts: str) -> str:  # ("" unless every part is known: a guess would call two accounts one)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12] if all(parts) else ""
    if name == "codex":
        auth = home / "codex" / "auth.json" if home else Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "auth.json"
        try:
            token = (json.loads(auth.read_text()).get("tokens") or {}).get("id_token") or ""
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        except (OSError, ValueError, IndexError, AttributeError):
            return ""
        return short(str(claims.get("email") or "").lower(),
                     str((claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id") or ""))
    if name == "claude" and (tool := install.tool_path("claude")):
        env = clean_env()
        if home:  # (as xPerfect runs it for that account: its own home and its own Keychain item)
            env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / "claude"), CLAUDE_SECURESTORAGE_CONFIG_DIR=str(home / "claude"))
        try:
            said = json.loads(subprocess.run([tool, "auth", "status"], capture_output=True, text=True, timeout=20,
                                             env=env, cwd=ROOT).stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return ""
        return short(str(said.get("email") or "").lower(), str(said.get("orgId") or "")) if said.get("loggedIn") else ""
    return ""


def installed(name: str) -> bool:
    """Whether a provider's own sign-in tool is on this Mac at all (if not, it is one click: settings/install.py)."""
    return install.tool_ready(name)


OWN_FRESH = 10.0  # s what the Keychain said of a sign-in of Light's own is used for before it is asked again
OWN_WAIT = 1.0  # s the page lets the Keychain take to say it (never longer: it shows what it last knew, or "checking")
_own_now: dict = {}  # (asked once per page render: this process's answer)


def own_presence(name: str) -> tuple[bool, bool]:
    """Whether a sign-in Light makes itself (catalog.OWN_SIGN_INS: her mind's Grok) is kept in its Keychain item, and
    whether that is still being checked: asked once per render, at most OWN_WAIT seconds, remembered OWN_FRESH seconds
    (logs/settings-own-sign-in.json: never what it holds, only whether it is there). The Keychain that does not answer in
    time: what it last said, or not signed in yet with "checking". Settings never waits on it."""
    if name in _own_now:
        return _own_now[name]
    cache = LOGS / "settings-own-sign-in.json"
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    last = known.get(name) or {}
    from core import grok_sign_in
    # (a sign-in kept after what the Keychain last said: that answer is old. Before, for about 18 s after
    # its approval the page offered Connect again, from what it knew before it, even on a reload)
    kept = grok_sign_in.kept_since(float(last.get("t") or 0))
    if last and not kept and time.time() - float(last.get("t") or 0) < OWN_FRESH:
        _own_now[name] = (bool(last.get("on")), False)
        return _own_now[name]
    said = grok_sign_in.presence(OWN_WAIT)
    if said is None:  # (no answer in time: what it last said, still being checked; just kept: kept, by its own record)
        _own_now[name] = (True, False) if kept else (bool(last.get("on")), True)
        return _own_now[name]
    known[name] = {"on": said, "t": time.time()}
    with contextlib.suppress(OSError):
        private_write(cache, json.dumps(known))
    _own_now[name] = (said, False)
    return _own_now[name]


def own_known(name: str) -> None:
    """A sign-in of Light's own just changed here (made, cancelled, turned off or on): asked again at the next render."""
    _own_now.pop(name, None)
    with contextlib.suppress(OSError, ValueError):
        known = json.loads((LOGS / "settings-own-sign-in.json").read_text())
        known.pop(name, None)
        private_write(LOGS / "settings-own-sign-in.json", json.dumps(known))


def own_signed_in(name: str) -> bool:
    """Whether a sign-in Light makes itself (catalog.OWN_SIGN_INS: her mind's Grok) is kept in its Keychain item, as
    own_presence() last learned it (never a wait of more than OWN_WAIT)."""
    if name == "chatgpt_mind" and not OFFLINE:
        return chatgpt_status()["on"]
    if OFFLINE:
        return name in os.environ.get("VX_SETTINGS_SIGNED_IN", "").split()
    return own_presence(name)[0]


def own_off(name: str, off: bool) -> None:
    """The page's own switch for a sign-in of Light's own (logs/<name>.off, beside the profile marker): a call and
    Telegram read it before each request (brain/queen._turned_off), and no profile line can undo it. Off wins."""
    flag = LOGS / f"{name}.off"
    if off:
        private_write(flag, "off\n")
    else:
        flag.unlink(missing_ok=True)


def own_is_off(name: str) -> bool:
    return (LOGS / f"{name}.off").exists()


def own_sign_in(name: str) -> dict:
    """Such a sign-in, as the page shows it: {"on"}, with "checking" while the Keychain has not said yet, "setup" ({"url",
    "code"}: where to approve it, and your one-time code) while one waits for you, or "last" (how the last one ended
    when it did not: "denied", "expired", "failed", "ended"). Never a token, and never more than OWN_WAIT of waiting."""
    if name == "chatgpt_mind":
        return chatgpt_status()
    if OFFLINE:  # (tests: a sign-in under way, and whether one is kept, are a file of theirs)
        try:
            said = json.loads((LOGS / "own-sign-in.json").read_text())
        except (OSError, ValueError):
            said = {}
        return {"on": own_signed_in(name) or bool(said.get("on")), **{k: said[k] for k in ("setup", "last", "checking") if k in said}}
    on, checking = own_presence(name)
    from core import grok_sign_in
    return {**grok_sign_in.status(on=on), **({"checking": True} if checking else {})}


def chatgpt_status() -> dict:
    from core import accounts, chatgpt_sign_in as sign_in

    try:
        status = ({"state": "connected" if own_signed_in(sign_in.NEEDS) else "signed_out"} if OFFLINE
                  else sign_in.connection.status())
        registrations = [] if OFFLINE else sign_in.connection.registrations()
    except (OSError, ValueError, sign_in.SignInError):
        status, registrations = {"state": "unavailable"}, []
    health = status["state"]
    if health == "connected":
        found = accounts.states().get(accounts.route(sign_in.NEEDS), {}).get("state")
        status["state"] = {"down": "unavailable", "sign_in": "sign_in", "refused": "refused"}.get(found, health)
    return {**status, "on": health in ("connected", "limited", "refresh_unavailable", "unauthorized")
            or health == "unavailable" and bool(status.get("account")),
            "privacy": catalog.CHATGPT_PRIVACY, "registrations": registrations}


def connect_chatgpt(account: str | None) -> str:
    from core import chatgpt_sign_in

    if OFFLINE:
        return ""
    if chatgpt_status().get("pending"):
        return "Finish signing in in your browser."
    names = ("VX_STATE", "VX_LOGS", "VX_SETTINGS_ROOT", "VX_SETTINGS_BENCH", "PYTHONPATH")
    env = {**clean_env(), **{k: os.environ[k] for k in names if os.environ.get(k)}}
    if BENCH and (path := os.environ.get("VX_SIWC_CONSENT_FILE")):
        env["VX_SIWC_CONSENT_FILE"] = path
    subprocess.Popen([sys.executable, "-m", "settings", "chatgpt-connect", account or ""], cwd=CODE, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        status = chatgpt_sign_in.connection.status()
        if status["pending"] or status.get("account") and status["state"] == "connected":
            return ""
        time.sleep(0.05)
    return "ChatGPT sign-in could not start."


def finish_chatgpt(account: str) -> None:
    from core import accounts, chatgpt_sign_in as sign_in

    try:
        sign_in.browser_login(account or None,
                              consent_file=os.environ.get("VX_SIWC_CONSENT_FILE") if BENCH else None)
    except (OSError, ValueError, sign_in.SignInError):
        return
    accounts.up(sign_in.NEEDS)


def cancel_sign_in(name: str) -> None:
    """End a sign-in of Light's own that waits for you: nothing is kept from it."""
    if name not in catalog.OWN_SIGN_INS:
        return
    if name == "chatgpt_mind":
        if not OFFLINE:
            from core.chatgpt_sign_in import connection
            connection.cancel()
        return
    if OFFLINE:
        with contextlib.suppress(OSError, ValueError):
            said = json.loads((LOGS / "own-sign-in.json").read_text())
            said.pop("setup", None)
            private_write(LOGS / "own-sign-in.json", json.dumps(said))
        return
    from core import grok_sign_in
    grok_sign_in.cancel()
    own_known(name)


def own_sign_in_done(name: str) -> None:
    """A quiet helper of the page's (python -m settings own-sign-in NAME): xAI's device flow, its page opened in your
    browser, until you approve it, refuse it or it expires. Signed in: how her mind was last found is cleared, and a mind
    whose backup stood in for it comes back online at her next calm moment (as when a key is added)."""
    from core import accounts, grok_sign_in
    if grok_sign_in.login() != "signed_in":
        return
    own_known(name)  # (a running call or Telegram drops its old token at its next request: grok_sign_in's stamp)
    accounts.up(name)
    from settings import service, store
    now = service.show()
    env = store.values(now["profile"], service.KEYS)
    if env.get("WORKERS") == "signed-in" or service.stood_in(name, now, env):
        apply_when_idle(now["profile"])


def sign_in(name: str) -> str:
    """Start a harness's own sign-in (it opens your browser), or one Light makes itself (catalog.OWN_SIGN_INS: a quiet
    helper, its code on the page while it waits). Returns "" or why not."""
    if name == "chatgpt_mind":
        return "Connect ChatGPT in System."
    if name in catalog.OWN_SIGN_INS:
        if OFFLINE:
            said = {}
            with contextlib.suppress(OSError, ValueError):
                said = json.loads((LOGS / "own-sign-in.json").read_text())
            private_write(LOGS / "own-sign-in.json", json.dumps({**({"on": True} if said.get("on") else {}),
                                                                 "setup": {"url": "https://accounts.x.ai/oauth2/device?user_code=TEST-CODE",
                                                                           "code": "TEST-CODE"}}))
            return ""
        from core import grok_sign_in
        if grok_sign_in.under_way():  # (one under way, from here, another tab or a terminal: its code stands; never a second)
            return ""
        began = time.time()
        # (a test's stand-ins of xAI, loopback only, go with it: core/grok_sign_in never sends anything else there)
        env = {**clean_env(), **{k: os.environ[k] for k in ("VX_STATE", "GROK_AUTH_ISSUER", "GROK_PLAN_URL") if os.environ.get(k)}}
        subprocess.Popen([sys.executable, "-m", "settings", "own-sign-in", name], cwd=CODE, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):  # (its code, on the page as soon as xAI gives it; a result older than this start is not its)
            _own_now.pop(name, None)
            now = own_sign_in(name)
            if now.get("setup") or float(now.get("at") or 0) >= began:
                break
            time.sleep(0.25)
        now = own_sign_in(name)
        own_known(name)
        return "" if now.get("setup") or now.get("on") or grok_sign_in.under_way() else "Grok's sign-in could not start. Try again in a moment."
    spec = catalog.SIGN_INS.get(name)
    if spec is None:
        return "That sign-in does not exist."
    if not install.tool_ready(name):
        return f"Install {install.name(name)} first."
    if not OFFLINE:
        subprocess.Popen([install.tool_path(name), *spec["login"][1:]], cwd=ROOT, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        (LOGS / "settings-signins.json").unlink(missing_ok=True)  # asked again next time
    return ""


def local_models() -> set[str]:
    """The models in Ollama's store on this Mac, as name:tag."""
    return install.local_models()


def media_weights(model: str) -> bool:
    """Whether a local photo or video model can run here: its weights whole, and the program that runs it."""
    return install.media_ready(model)


# -- This Mac: start at login, the menu bar --

KEEPER_NOTE = Path.home() / "Library" / "Application Support" / "Viventium Light" / "keep.json"  # (tools/menubar/main.swift)


def system() -> dict:
    """The menu bar and starting with this Mac; and whether macOS is letting the keeper read this folder (it asks
    once when the folder is in Documents, Desktop or Downloads; until you allow it, nothing starts by itself)."""
    if BENCH:  # (his Light's, never the bench's: shown off, and a change says why: set_system)
        return {"login": False, "menubar": False, "blocked": False}
    login = "autostart: on" in vx("autostart").stdout
    if OFFLINE:
        blocked = os.environ.get("VX_SETTINGS_KEEP_BLOCKED") == "1"
    else:
        try:
            blocked = bool(json.loads(KEEPER_NOTE.read_text()).get("blocked"))
        except (OSError, ValueError):
            blocked = False
    return {"login": login, "menubar": "menubar: on" in vx("menubar").stdout, "blocked": login and blocked}


def show_privacy() -> None:
    """Open the page of System Settings where macOS lists what may read your folders (you tick it; nothing is changed here)."""
    if OFFLINE:
        with private_open(LOGS / "opened", "a") as log:
            log.write("privacy\n")
        return
    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"], check=False)


SYSTEM_FAILED = {("menubar", True): "Viventium could not put its mark in the menu bar",
                 ("menubar", False): "Viventium could not take its mark out of the menu bar",
                 ("login", True): "Viventium could not set itself to start with this Mac",
                 ("login", False): "Viventium could not stop itself starting with this Mac"}


def set_system(name: str, on: bool) -> str:
    """The menu bar or starting with this Mac, on or off. Returns "" or what did not change, in plain words."""
    if BENCH:
        return ("This is the test bench. It never changes this Mac's menu bar, what starts with this Mac or the app, "
                "so nothing changed.")
    command = {"login": "autostart", "menubar": "menubar"}[name]
    if ran(f"{command} {'on' if on else 'off'}", vx(command, "on" if on else "off", timeout=120)):
        return ""
    return f"{SYSTEM_FAILED[(name, on)]}. Try again in a moment."


# -- Channels --

def connect_telegram(value: str, env: dict) -> str:
    """Validate the bot before keeping its token in Keychain. No token in argv or returned errors."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{16,300}", value):
        return "Paste the bot token from BotFather."
    if OFFLINE:
        return "Telegram is unavailable while offline."
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{value}/getMe", timeout=6) as reply:
            body = json.load(reply)
        me = body.get("result", {})
        if (body.get("ok") is not True or me.get("is_bot") is not True or type(me.get("id")) is not int
                or str(me["id"]) != value.partition(":")[0]
                or not re.fullmatch(r"[A-Za-z0-9_]+", me.get("username", ""))):
            return "Telegram did not accept that bot token."
    except Exception:
        return "Telegram could not check that token. Try again."
    item = env.get("TELEGRAM_TOKEN_ITEM") or "viventium-light/telegram_bot_token"
    # Keychain's interactive command grammar; keep values out of the process list.
    item = item.replace("\\", "\\\\").replace('"', '\\"')
    if any(c in item for c in "\r\n"):
        return "The Keychain item name is invalid."
    command = f'add-generic-password -U -s "{item}" -a viventium-light -w "{value}"\n'
    try:
        done = subprocess.run(["security", "-i"], input=command, capture_output=True, text=True, timeout=20)
        if done.returncode or done.stderr.strip():
            return "The Keychain did not take it."
        private_write(LOGS / "telegram-bot.json", json.dumps({"bot": "@" + me["username"], "id": str(me["id"])}))
    except (OSError, subprocess.TimeoutExpired):
        return "The bot token could not be saved. Try again."
    return ""


def disconnect_telegram(env: dict) -> str:
    """Let her bot go: its token leaves the Keychain and its name leaves this Mac (logs/telegram-bot.json), so another bot
    can be connected (connect_telegram). "" or why not. Before, once a bot was connected Settings had no way to let it go,
    and turning Viventium off left its token in the Keychain."""
    if OFFLINE:
        return "Telegram is unavailable while offline."
    item = env.get("TELEGRAM_TOKEN_ITEM") or "viventium-light/telegram_bot_token"
    try:
        for _ in range(5):  # (each item of that name, however it was made: until the Keychain has none)
            done = subprocess.run(["security", "delete-generic-password", "-s", item], capture_output=True, timeout=20)
            if done.returncode == 44:  # (no such item: gone)
                break
            if done.returncode:
                return "The Keychain did not let the bot's token go."
        else:
            return "The Keychain did not let the bot's token go."
    except (OSError, subprocess.TimeoutExpired):
        return "The Keychain could not be reached. Try again."
    with contextlib.suppress(OSError):
        (LOGS / "telegram-bot.json").unlink(missing_ok=True)
    return ""


def telegram(env: dict) -> dict:
    """Whether a bot is connected, and which. The token stays in the Keychain; only its name and id come back. Off, nothing
    is asked of Telegram (offline stays offline): the name it last had, if any."""
    info = {"on": env.get("TELEGRAM", "") != "off", "connected": False, "bot": "", "id": ""}
    if OFFLINE:
        return info
    item = env.get("TELEGRAM_TOKEN_ITEM") or "viventium-light/telegram_bot_token"
    if subprocess.run(["security", "find-generic-password", "-s", item], capture_output=True).returncode != 0:
        return info
    info["connected"] = True
    cache = LOGS / "telegram-bot.json"
    try:
        known = json.loads(cache.read_text())
        fresh = time.time() - cache.stat().st_mtime < 7 * 86400
    except (OSError, ValueError):
        known, fresh = {}, False
    if isinstance(known, dict) and known and (fresh or not info["on"]):
        return {**info, **known}
    if not info["on"]:
        return info
    try:
        token = subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True).stdout.strip()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=6) as reply:
            me = json.load(reply).get("result", {})
        found = {"bot": "@" + me["username"], "id": str(me["id"])}
        private_write(cache, json.dumps(found))
        return {**info, **found}
    except Exception:  # (offline, or Telegram slow: she is still connected; the name comes next time)
        return info


def web() -> dict:
    port = os.environ.get("UI_PORT") or "3400"
    return {"on": True, "address": f"localhost:{port}", "port": port}


def phone_address() -> dict:
    """This Mac's name, address and network on your network, and the phone's two doors on them (call/phone.py)."""
    if OFFLINE:  # (tests say what the network is, in the environment)
        name = os.environ.get("VX_SETTINGS_LAN_NAME", "Test-Mac")
        host = f"{name.lower()}.local"
        ip = os.environ.get("VX_SETTINGS_LAN_IP", "")
        return {"name": name, "host": host, "ip": ip, "network": os.environ.get("VX_SETTINGS_LAN_NETWORK", "a1b2c3d4e5f60718" if ip else ""),
                "page": f"https://{host}:3443", "call": f"wss://{host}:7443"}
    from call import phone
    return phone.address()


def phone_state() -> Path:
    """Her folder for the phone (call/phone.py's HOME): the doors' certificate, the round of pairings."""
    return Path(os.environ.get("VX_STATE") or ROOT / "state") / "core" / "phone"


def phone_fingerprint() -> str:
    """The fingerprint of the certificate his phone trusts, as the phone shows it (call/phone.py), "" before there is one."""
    from call import phone
    return phone.fingerprint(phone_state())


def door_ports() -> list[int]:
    """The ports the phone's doors open on: the usual two and the ones vx last opened them on (logs/doors.ports); a test
    names its own (VX_SETTINGS_DOOR_PORTS), and a test that names none looks at none."""
    if OFFLINE:
        return [int(p) for p in os.environ.get("VX_SETTINGS_DOOR_PORTS", "").split() if p.isdigit()]
    kept = read(LOGS / "doors.ports").split()
    return sorted({3443, 7443, *(int(p) for p in kept if p.isdigit())})


def doors_answer() -> bool:
    """Whether anything listens on a door port of this Mac (on any of its addresses), as lsof sees it."""
    for port in door_ports():
        try:
            if subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                              timeout=10).stdout.strip():
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def doors_off() -> None:
    """Calling from the phone turned off: its doors close now, whatever else waits for a restart. Their pass goes first
    (the page then takes nothing as the phone's), then ./vx stops the doors by their recorded process and ports."""
    (phone_state() / "door-pass").unlink(missing_ok=True)
    ran("doors-off", vx("doors-off", timeout=60))


def phone_renewed() -> bool:
    """Whether a phone paired on this Mac trusts a root of Viventium's other than the one now (the page keeps which root each
    paired phone trusts: call/ui/app/api/token/pairing.ts): that phone can load nothing over the new certificate until it
    trusts the new root, so this Mac says so."""
    now = phone_fingerprint().replace(" ", "")[:16]
    try:
        kept = json.loads((phone_state() / "trusted.json").read_text())
    except (OSError, ValueError):
        return False
    return bool(now) and isinstance(kept, dict) and any(str(mark) != now for mark in kept.values())


def forget_phones() -> str:
    """Unpair every phone at once: a new round of pairings (not a secret), which the page reads at every request
    (call/ui/app/api/token/pairing.ts), so every phone paired before is refused from its next request on, with no
    restart; a code waiting to be typed is void too. Returns "" or why not. The Keychain is not touched."""
    import secrets
    try:
        private_write(phone_state() / "paired", secrets.token_hex(16))
        (phone_state().parent / "phone-pairing.json").unlink(missing_ok=True)
        (phone_state() / "trusted.json").unlink(missing_ok=True)  # (no phone paired: none to tell of a new root)
    except OSError:
        return "Viventium could not keep that on this Mac."
    return ""


# -- Applying a change that needs her restarted --

def tests_running() -> bool:
    return (LOGS / "tests.lock").is_dir() and alive(LOGS / "tests.lock" / "pid")


def busy() -> str:
    """Why she cannot be restarted this second: "" (free), "call" or "work". Asked of her own state (VX_STATE: the
    bench's on the bench, so a bench call is never cut either); a test may say it in a file instead."""
    if OFFLINE and (LOGS / "busy").exists():  # (so it can change while the helper waits)
        return read(LOGS / "busy").strip()
    env = {**clean_env(), **({"VX_STATE": os.environ["VX_STATE"]} if os.environ.get("VX_STATE") else {})}
    code = ("from core import state, jobs\n"
            "print('call' if state.call_live() else 'work' if any('result' not in j for j in jobs.open_jobs()) else '')")
    try:
        return subprocess.run([sys.executable, "-c", code], cwd=CODE, env=env, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


RESTART_FAILED = "Your change is saved, but Viventium could not switch over to it."
RESTART_AGAIN = " Turn Viventium off and open it again to start with it."  # (the app starts her on what is saved: ./vx up)
# She did switch over, and her mind then gave no word (vx mind_answers: exit 3 or 4). What is said is always the latest
# result's: her verdict (logs/mind-answer, which only a start's own check writes) says which, and a start after this
# switch-over (its verdict newer than this record) decides it alone: heard, and nothing is said; not heard, said as it is
# now (no answer in time may pass by asking again; anything else needs another mind, chosen right here under Brain).
RESTART_MIND = "Your change is saved, but Viventium's mind did not answer. Choose another one under Brain."
RESTART_SILENT = "Your change is saved, but Viventium's mind did not answer in time. Turn Viventium off and open it again to ask it again."


def applying() -> dict:
    """How the last saved change is doing: idle, waiting (for you to finish choosing, a call, or her work),
    restarting, or failed, said in plain words (vx's own words are in her settings log and logs/settings-restart.log)."""
    try:
        pending = json.loads((LOGS / "settings-pending.json").read_text())
    except (OSError, ValueError):
        pending = None
    if pending and alive(LOGS / "settings-apply.pid"):
        return {"state": pending.get("state", "waiting"), "for": pending.get("for", ""), "profile": pending.get("profile", "")}
    record, verdict = LOGS / "settings-restart.code", LOGS / "mind-answer"
    code = read(record).split()[:1]  # (written last, so it settles the question; an older record has words after its number)
    heard = read(verdict).split()[:1]
    if not code or code == ["0"]:  # (switched over, and heard: what a later start finds is the app's and the menu bar's to say)
        return {"state": "idle"}
    later = bool(heard) and verdict.stat().st_mtime > record.stat().st_mtime
    if later or code in (["3"], ["4"]):  # (her mind's own latest result)
        if heard == ["answered"]:
            return {"state": "idle"}
        return {"state": "failed", "why": RESTART_SILENT if heard == ["silent"] else RESTART_MIND}
    return {"state": "failed", "why": RESTART_FAILED + ("" if BENCH else RESTART_AGAIN)}


def apply_when_idle(profile: str) -> None:
    """Note that she must restart on this profile, and make sure one quiet helper is waiting to do it."""
    private_write(LOGS / "settings-pending.json", json.dumps({"profile": profile, "at": time.time(), "state": "waiting", "for": "settling"}))
    (LOGS / "settings-restart.code").unlink(missing_ok=True)
    if alive(LOGS / "settings-apply.pid"):
        return
    env = {**clean_env(), **{k: os.environ[k] for k in ("VX_SETTINGS_ROOT", "VX_SETTINGS_OFFLINE", "VX_SETTINGS_SETTLE",
                                                         "VX_STATE") if k in os.environ}}
    child = subprocess.Popen([sys.executable, "-m", "settings", "applier"], cwd=Path(__file__).resolve().parents[1], env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    private_write(LOGS / "settings-apply.pid", str(child.pid))


def applier() -> None:
    """The quiet helper: waits for a calm moment, restarts her once, and goes. A change saved meanwhile is
    picked up before it leaves."""
    pending_file = LOGS / "settings-pending.json"
    while True:
        try:
            pending = json.loads(pending_file.read_text())
        except (OSError, ValueError):
            return
        wait = "settling" if time.time() - pending["at"] < SETTLE else busy()
        if wait:
            if pending.get("for") != wait:
                private_write(pending_file, json.dumps({**pending, "state": "waiting", "for": wait}))
            time.sleep(0.5 if wait == "settling" else 3)
            continue
        private_write(pending_file, json.dumps({**pending, "state": "restarting", "for": ""}))
        # The call page marks a call as it starts and then reads this state (call/ui/app/api/token); looking once
        # more after saying "restarting" means a call that began in between is seen by one side or the other.
        if busy():
            continue
        with private_open(LOGS / "settings-restart.log") as log:
            code = subprocess.run(["/bin/bash", str(ROOT / "vx"), "restart", pending["profile"]], cwd=ROOT,
                                  env={**clean_env(), "VX_NO_OPEN": "1", "VX_KEEP_UI": "1"}, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT).returncode
        try:
            newer = json.loads(pending_file.read_text())
        except (OSError, ValueError):
            newer = pending
        if newer.get("at") != pending["at"]:  # another choice was saved while she restarted: once more, for it
            continue
        if code != 0:  # (its own words, whole, stay in settings-restart.log; their end goes to her settings log too)
            logged(f"switching over to {pending['profile']}", f"exit {code}\n" + "\n".join(read(LOGS / "settings-restart.log").splitlines()[-12:]))
        private_write(LOGS / "settings-restart.code", str(code))
        pending_file.unlink(missing_ok=True)
        (LOGS / "settings-apply.pid").unlink(missing_ok=True)
        return
