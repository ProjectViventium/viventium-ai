"""Her Grok subscription, signed in by Light itself, for her conscious mind (QUEEN=xai_plan).

How (the route measured and picked): xAI's device flow at auth.x.ai, in
your browser, once; then every model call goes to api.x.ai/v1 with that sign-in's access token, as Light (its own
User-Agent; never presenting as another app). xAI has no way for an app to register a client of its own, so the
sign-in uses Grok Build's public client, as every app that offers a Grok subscription does: the consent page may say
"Grok Build".

Kept. One item in this Mac's Keychain, Light's own (item()), holding the refresh token, the access token it last got
with its end, when and how it was got, and the optional profile display name. A token stays out of files, logs, process
lists and environments. The Grok Worker helper can pass just the current access token to Grok Build on its private
stdout pipe. Another tool's sign-in (the Grok CLI's) is never read. Written in one update of that one item through
`security -i` on its input (never its command line), and read back. Measured: a refresh token and an
access token of about a thousand characters together make a line a third of what `security -i` reads in one
(4,096); an access token too long for it is left out (kept in memory only), never the refresh token.

Refreshed. Under one lock per user on this Mac (place(), opened without following a link; if it cannot be opened, her
backup answers at once), whichever process asks first: it reads the refresh token, asks auth.x.ai, and writes the new
one before anything uses it. The one window no OAuth client closes: a crash, or a Keychain that refuses the write,
between auth.x.ai's answer and that write leaves a rotated-away refresh token kept; she then asks you to sign in again.
A token within REFRESH seconds of its end is refreshed behind the request (it goes with the token it has); only one
within SOON seconds waits for it. A token another process already refreshed is read, never refreshed again. A refresh
that cannot be done now (no answer, a limit, a server error, discovery failing) is not asked again for a while, by any
process (BACKOFF, doubling to BACKOFF_MOST). A readiness check (checking()) reads, and refreshes only a token whose time
is already up; it never forces a refresh and never signs her out.

Refused. A model call refused with 401 or 403 (api.x.ai answers 403 for a token that no longer validates, and also for
an account xAI does not allow) forces one refresh of the token that call used (refused()): the token endpoint decides,
by its own OAuth error code (invalid_grant and the other final codes: the sign-in ended; its item goes). Refused again
with a token refreshed less than FRESH seconds ago, or one from such a forced refresh less than HOLD seconds ago: the
refusal is real and no refresh is forced for it; the page then offers to sign in again. Never decided by a provider's
wording.

Only xAI. auth.x.ai and api.x.ai (https, x.ai hosts) are the only places it goes. A test that names a stand-in of either
on this Mac (GROK_AUTH_ISSUER, GROK_PLAN_URL, loopback only) gets a stand-in item and stand-in locks, and the other one
is nowhere (a port with nothing on it), never xAI: a sign-in never reaches a stand-in model, nor a stand-in's token xAI.

    python -m core.grok_sign_in login    sign in from a terminal (vx): says the page and code, waits for you
    python -m core.grok_sign_in start    the same, quietly (the settings page starts it; the page shows the code)
    python -m core.grok_sign_in cancel   end a sign-in that waits
    python -m core.grok_sign_in status   signed in or not (exit 0 when signed in); nothing secret is printed

One sign-in at a time on this Mac (a second one, from another tab or vx, is "busy"). A sign-in under way is kept in her
state (PENDING: the page's link and your one-time code, the helper's process and its start, how it ended), never its
device code. Nothing is kept after its code's own time is up or once it is cancelled: an approval that comes in while
it is being cancelled is put back as it was.
"""
import base64
import contextlib
import fcntl
import ipaddress
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core.state import STATE_ROOT, closed_file

log = logging.getLogger("grok_sign_in")

# Grok Build's public OAuth client: the one every app offering a Grok subscription uses (OpenClaw, Hermes, Kilo Code,
# Agno, Zed). Light's own, once xAI offers one, is this one line and one new sign-in.
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"  # (the set those apps sign in with)
ISSUER = "https://auth.x.ai"
API = "https://api.x.ai/v1"
NOWHERE = "http://127.0.0.1:9"  # (a stand-in's other endpoint when a test names only one: nothing listens there)
UA = "Viventium-Light/0.5"  # what Light calls itself to xAI
ITEM, ACCOUNT = "viventium-light/grok_sign_in", "viventium-light"
STAND_IN_ITEM = "viventium-light/grok_sign_in.stand-in"  # (a test's stand-in endpoints: never his item)
NEEDS = "grok_mind"  # the settings catalog's `needs` for it, and its name in KEYS_OFF and core/accounts
REFRESH = 300.0  # s before its end a token is refreshed, behind the request that asked
SOON = 30.0  # s before its end the request itself waits for the refresh (within her mind's own deadline: brain/queen)
FRESH = 60.0  # s: a token this new that is refused is not refreshed again for it
HOLD = 1800.0  # s: the same for a token a refusal already refreshed (a standing refusal: one refresh per half hour)
AUTH_WAIT = 10.0  # s for one request to auth.x.ai while a turn may wait on it
SIGN_IN_WAIT = 30.0  # s for one request of a sign-in
LOCK_WAIT = 4.0  # s a process waits for another's refresh before using what it has, or giving up for now
BACKOFF, BACKOFF_MOST = 30.0, 600.0  # s a refresh that could not be done now is not asked again for (doubling)
LINE = 4000  # characters of one `security -i` line kept (it reads 4,096)
AFTER_REFUSAL = 3.0  # s, all told, a refused refresh looks again for another holder's new one before it signs her out
FINAL = {"invalid_grant", "invalid_client", "unauthorized_client", "invalid_request", "access_denied", "invalid_scope"}
ENDED = ("denied", "expired", "failed", "ended", "keychain_locked")  # status "last"
KEYCHAIN_LOCKED = -25308  # errSecInteractionNotAllowed
UNLOCK_KEYCHAIN = "Your Mac’s Keychain is locked. Unlock it by logging in to your Mac, then try again."
PENDING = STATE_ROOT / "core" / "grok-sign-in.json"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class KeychainLocked(OSError):
    """The save returned errSecInteractionNotAllowed."""


class NotSignedIn(Exception):
    """No sign-in of hers to use: never made, or ended (its refresh refused by auth.x.ai). Sign in (again)."""


class _Moved(Exception):
    """Her lock's file is no longer the one at its place: taken again, and what is kept read again, before anything is
    sent (never the same refresh token twice)."""


class Unavailable(Exception):
    """No token to use just now (auth.x.ai not answering, limited, a server error, a lock that cannot be had): her
    backup answers meanwhile; tried again later."""


# -- Where: xAI's own hosts only (a stand-in on this Mac for tests, with stand-in places of its own) --

def _loopback(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _override(name: str) -> str:
    url = os.environ.get(name, "").strip().rstrip("/")
    return url if url and _loopback(url) else ""


def stand_in() -> bool:
    """A test named stand-ins of auth.x.ai or api.x.ai on this Mac: then nothing of his and nothing of xAI's is used."""
    return bool(_override("GROK_AUTH_ISSUER") or _override("GROK_PLAN_URL"))


def issuer() -> str:
    return _override("GROK_AUTH_ISSUER") or (NOWHERE if stand_in() else ISSUER)


def api_url() -> str:
    """Where her mind's requests go: api.x.ai/v1."""
    return _override("GROK_PLAN_URL") or (NOWHERE + "/v1" if stand_in() else API)


def item() -> str:
    """The Keychain item her sign-in is kept in: Light's own, or a stand-in's when a test named stand-in endpoints."""
    return STAND_IN_ITEM if stand_in() else ITEM


def place() -> Path:
    """Where her sign-in's locks and backoff are: one place per user on this Mac, whatever a process's TMPDIR or state
    (the Keychain item is per user too); a test's own state for a test's stand-ins."""
    return STATE_ROOT / "core" if stand_in() else Path.home() / "Library" / "Caches" / "viventium-light"


def trusted(url: str) -> bool:
    """An address of xAI's (https, x.ai or one of its hosts), or the stand-in a test named on this Mac."""
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and (host == "x.ai" or host.endswith(".x.ai")):
        return not stand_in()
    return bool(_override("GROK_AUTH_ISSUER")) and _loopback(url) and parts.hostname == urllib.parse.urlsplit(issuer()).hostname


def _ask(url: str, form: dict | None = None, wait: float = AUTH_WAIT) -> tuple[int, dict]:
    """One request to auth.x.ai: (status, its JSON or {}). 0 when it could not be reached in time."""
    if not trusted(url):
        raise ValueError("not an address of xAI's")
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if form is not None else "GET", headers={
        "Accept": "application/json", "User-Agent": UA,
        **({"Content-Type": "application/x-www-form-urlencoded"} if form is not None else {})})
    try:
        with urllib.request.urlopen(request, timeout=wait) as answer:
            status, raw = answer.status, answer.read(1 << 20)
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read(1 << 20)
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}
    try:
        said = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        said = {}
    return status, said if isinstance(said, dict) else {}


_found: dict = {}


def discovery(wait: float = AUTH_WAIT) -> dict:
    """auth.x.ai's own discovery document (its device and token endpoints), once per process."""
    if not _found or _found.get("_issuer") != issuer():
        if not trusted(issuer() + "/"):
            raise Unavailable("no auth.x.ai here")
        status_, said = _ask(issuer() + "/.well-known/openid-configuration", wait=wait)
        if status_ != 200 or not all(trusted(str(said.get(k, ""))) for k in ("device_authorization_endpoint", "token_endpoint")):
            raise Unavailable(f"discovery {status_}")
        _found.clear()
        _found.update(said, _issuer=issuer())
    return _found


# -- The Keychain: one item of hers, through /usr/bin/security (as her keys are: vx, settings/runtime.py) --

def _security(*args: str, given: str | None = None, wait: float = 20.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["security", *args], input=given, capture_output=True, text=True, timeout=max(0.1, wait))
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(["security", *args], 124, "", "")


def _raw(wait: float = 20.0, *, report_failure: bool = False) -> str | None:
    done = _security("find-generic-password", "-s", item(), "-a", ACCOUNT, "-w", wait=wait)
    if report_failure and done.returncode not in (0, 44):
        raise Unavailable("could not read the sign-in from Keychain")
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _decode(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        kept = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
    except (ValueError, UnicodeDecodeError):
        return None
    return kept if isinstance(kept, dict) and kept.get("refresh") else None


def _kept(wait: float = 20.0, *, report_failure: bool = False) -> dict | None:
    """Her sign-in as kept, or None. Raise Unavailable on a Keychain read failure when requested."""
    kept = _decode(_raw(wait, report_failure=report_failure))
    if kept:
        _seen(kept.get("access", ""), kept["refresh"])
    return kept


def _line(value: str) -> str:
    return f"add-generic-password -U -s {item()} -a {ACCOUNT} -w {value}\n"


def _put(value: str) -> None:
    """One update of her one item, on security's input, read back: else OSError."""
    if len(_line(value)) > LINE:
        raise OSError("her sign-in is too long for one Keychain line")
    for _ in range(2):  # (once more at once if the Keychain did not take it: never later, never blind)
        done = _security("-i", given=_line(value))
        # Interactive security reports the full OSStatus here. Its process exit status holds only eight bits.
        if f"add-generic-password: returned {KEYCHAIN_LOCKED}" in done.stderr.splitlines():
            raise KeychainLocked
        if done.returncode == 0 and _raw() == value:
            return
    raise OSError("the Keychain did not keep her sign-in")


def _encode(tokens: dict) -> str:
    """Her sign-in as one value: with its access token when that fits one line, else without it (memory only)."""
    whole = base64.urlsafe_b64encode(json.dumps(tokens, separators=(",", ":")).encode()).decode()
    if len(_line(whole)) <= LINE:
        return whole
    lean = {k: v for k, v in tokens.items() if k not in ("access", "expires")}
    return base64.urlsafe_b64encode(json.dumps(lean, separators=(",", ":")).encode()).decode()


def _keep(tokens: dict) -> None:
    _put(_encode(tokens))


def _forget() -> None:
    _security("delete-generic-password", "-s", item(), "-a", ACCOUNT)


def signed_in() -> bool:
    """Whether her sign-in is kept here (it may still be refused when used: core/accounts says how it was last found)."""
    return _kept() is not None


def profile_name() -> str:
    """Only the display name supplied at sign-in, with no refresh or profile request."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        return str((_kept(wait=1.0) or {}).get("name") or "")
    return ""


def presence(wait: float = 1.0) -> bool | None:
    """Whether her item is there, asked of the Keychain without reading what it holds, in at most `wait` seconds: None
    when the Keychain did not say in time (the page shows "checking", or what it last knew: settings/runtime)."""
    try:
        done = subprocess.run(["security", "find-generic-password", "-s", item(), "-a", ACCOUNT], capture_output=True,
                              timeout=wait)
    except subprocess.TimeoutExpired:
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    return True if done.returncode == 0 else False if done.returncode == 44 else None


# -- Which sign-in a process holds: a stamp, changed by each new sign-in and each sign-out, read before each request --

def _generation() -> str:
    try:
        fd = _opened(place() / "grok-sign-in.generation", os.O_RDONLY)
    except OSError:
        return ""
    with os.fdopen(fd) as f:
        return f.read(64).strip()


def _bump() -> None:
    """A new sign-in, or none: every process drops the token it holds at its next request (also on a profile with no
    backup, where nothing restarts)."""
    with contextlib.suppress(OSError):
        fd = _opened(_folder() / "grok-sign-in.generation", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        with os.fdopen(fd, "w") as out:
            out.write(os.urandom(8).hex())


# -- The lock and the backoff: one place per user --

def _folder() -> Path:
    folder = place()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(folder)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise OSError("not a folder of hers")
    if st.st_mode & 0o077:
        os.chmod(folder, 0o700)
    return folder


def _opened(path: Path, flags: int) -> int:
    return os.open(path, flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)


@contextlib.contextmanager
def _locked(name: str = "grok-sign-in.lock", wait: float = LOCK_WAIT):
    """The per-user lock, held by its open file for the whole of what it guards: never through a link; one that cannot
    be opened is Unavailable at once; taken only while the file it locks is still the one at its place (a folder removed
    meanwhile is locked again), and it gives still() to ask that again before anything is sent."""
    until = time.monotonic() + max(0.0, wait)
    while True:
        try:
            path = _folder() / name
            fd = _opened(path, os.O_RDWR | os.O_CREAT)
        except OSError:
            raise Unavailable("her sign-in's lock cannot be opened") from None
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise Unavailable("another process is refreshing her sign-in") from None
                    time.sleep(0.05)
            def still() -> bool:  # (the file this lock holds is still the one at its place)
                try:
                    return os.fstat(fd).st_ino == os.lstat(path).st_ino
                except OSError:
                    return False
            if still():
                yield still
                return
        finally:
            os.close(fd)
        if time.monotonic() >= until:
            raise Unavailable("her sign-in's lock moved")


def _backing_off() -> bool:
    try:
        return float(json.loads((place() / "grok-sign-in.backoff").read_text()).get("until") or 0) > time.time()
    except (OSError, ValueError, AttributeError):
        return False


def _back_off() -> None:
    path = place() / "grok-sign-in.backoff"
    try:
        step = float(json.loads(path.read_text()).get("step") or 0)
    except (OSError, ValueError, AttributeError):
        step = 0.0
    step = min(BACKOFF_MOST, max(BACKOFF, step * 2))
    with contextlib.suppress(OSError):
        fd = _opened(_folder() / "grok-sign-in.backoff", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        with os.fdopen(fd, "w") as out:
            out.write(json.dumps({"until": round(time.time() + step, 1), "step": step}))
    log.warning("her Grok sign-in could not be refreshed now: not asked again for %d s", step)


def _backed() -> None:
    with contextlib.suppress(OSError):
        (place() / "grok-sign-in.backoff").unlink()


# -- Never in a log: every record of a process that uses her sign-in is looked through for its tokens --

_secrets: list = []  # (this process's own tokens, newest last: never written anywhere)
_keys: set[str] = set()  # configured API keys are kept in the guard for the life of the process


def _seen(*tokens: str) -> None:
    for token in tokens:
        if token and token not in _secrets:
            _secrets.append(token)
    del _secrets[:-12]


def redacting(*keys: str) -> None:
    """Keep the minds' credentials out of library logs, including echoed request IDs."""
    _keys.update(key for key in keys if key)
    if getattr(logging, "_grok_redacting", False):
        return
    made = logging.getLogRecordFactory()

    def record(*args, **kwargs):
        out = made(*args, **kwargs)
        secrets = (*_keys, *_secrets)
        if secrets:
            try:
                text = out.getMessage()
            except Exception:  # noqa: BLE001 (a record that cannot be formatted is left to logging itself)
                return out
            if any(secret in text for secret in secrets):
                for secret in secrets:
                    text = text.replace(secret, "<redacted>")
                out.msg, out.args = text, ()
        return out
    logging.setLogRecordFactory(record)
    logging._grok_redacting = True


# -- Her token, for each request --

_memory: dict = {}  # this process's copy: {"access", "expires", "saved"} (never written anywhere but her item)
_mem = threading.Lock()  # (held only to read or set _memory: never across a request)
_refreshing = threading.Lock()  # (one refresh behind the requests at a time in this process)
_checking = {"on": False}


def checking() -> None:
    """This process only checks that her mind answers (./vx ready, settings.probe): it reads, refreshes only a token whose
    time is already up, never forces a refresh for a refusal and never signs her out."""
    _checking["on"] = True


def _remember(kept: dict, generation: str | None = None) -> str:
    _seen(kept.get("access", ""), kept.get("refresh", ""))
    with _mem:
        _memory.clear()
        _memory.update({k: kept[k] for k in ("access", "expires", "saved") if k in kept}, generation=_generation() if generation is None else generation)
    return kept["access"]


def _has(tokens: dict | None, margin: float) -> bool:
    return bool(tokens and tokens.get("access") and float(tokens.get("expires") or 0) - time.time() > margin)


def _tokens(said: dict, before: dict | None, forced: bool = False) -> dict:
    access, refresh = str(said.get("access_token") or ""), str(said.get("refresh_token") or "")
    if not access:
        raise ValueError("no access token")
    try:
        lifetime = float(said.get("expires_in") or 3600)
    except (TypeError, ValueError):
        lifetime = 3600.0
    name = (before or {}).get("name", "")
    with contextlib.suppress(ValueError, IndexError, AttributeError, TypeError):
        part = said.get("id_token", "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        name = claims.get("name") or claims.get("given_name") or name
    return {"refresh": refresh or (before or {}).get("refresh", ""), "access": access, "expires": round(time.time() + lifetime, 1),
            "saved": round(time.time(), 1), **({"forced": True} if forced else {}),
            **({"name": " ".join(name.split())[:120]} if isinstance(name, str) and name.strip() else {})}


def _refresh(kept: dict, forced: bool = False, still=lambda: True) -> dict:
    """With the lock held: a new token, written at once (before anything uses it). NotSignedIn when auth.x.ai refuses it
    for good; Unavailable (and a backoff for every process) when it cannot be done now. still(): the lock is still the
    one at its place; asked right before the refresh token is sent, and before a refusal signs her out (a lock split by a
    removed folder never sends one refresh token twice, nor signs out because another holder used it first)."""
    if not still():
        raise _Moved()
    try:
        status_, said = _ask(discovery()["token_endpoint"], {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                                             "refresh_token": kept["refresh"]})
    except (Unavailable, ValueError):
        _back_off()
        raise Unavailable("auth.x.ai cannot be asked now") from None
    if 400 <= status_ < 500 and str(said.get("error") or "") in FINAL:
        newer = _kept(wait=AFTER_REFUSAL)  # (rotated by another process all the same, its lock split: that one, never a sign-out)
        if newer is not None and newer["refresh"] != kept["refresh"]:
            if _has(newer, SOON):
                return newer
            kept, (status_, said) = newer, _ask(discovery()["token_endpoint"], {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                                                                  "refresh_token": newer["refresh"]})
    if status_ == 200:
        _seen(str(said.get("access_token") or ""), str(said.get("refresh_token") or ""))
        try:
            fresh = _tokens(said, kept, forced)
        except ValueError:
            _back_off()
            raise Unavailable("refresh 200 without a token") from None
        try:
            _keep(fresh)
        except OSError:  # (the one window: her new refresh token is in this process only, used until it ends)
            log.error("her Grok sign-in was refreshed but the Keychain did not take it: when this token ends, sign in again")
        _backed()
        log.info("her Grok sign-in was refreshed")
        return fresh
    if 400 <= status_ < 500 and str(said.get("error") or "") in FINAL:
        if _checking["on"]:  # (a readiness check never signs her out)
            raise NotSignedIn("ended")
        if not still():
            raise Unavailable("her sign-in's lock moved")
        until = time.monotonic() + AFTER_REFUSAL
        while time.monotonic() < until:  # (another holder's new one, landing now: that one, never a sign-out; a few s in all)
            newer = _kept(wait=until - time.monotonic())
            if newer is not None and newer["refresh"] != kept["refresh"] and _has(newer, 5):
                return newer
            time.sleep(0.1)
        log.warning("her Grok sign-in ended (auth.x.ai refused its refresh: %s)", said.get("error"))
        _forget()
        _bump()
        _pending(state="ended")
        raise NotSignedIn("ended")
    _back_off()
    raise Unavailable(f"refresh {status_}")


def _now(margin: float) -> str:
    """Refresh now, under the lock: what another process already refreshed is read and used instead. A lock whose file
    moved before the refresh token is sent is taken again and what is kept read again."""
    for _ in range(3):
        stamp = _generation()  # (before the Keychain is read: a sign-in landing meanwhile is read again, never cached as new)
        with _locked() as still:
            kept = _kept(report_failure=True)
            if kept is None:
                with _mem:
                    _memory.clear()
                raise NotSignedIn("none")
            if _has(kept, margin):
                return _remember(kept, stamp)
            if _backing_off():
                raise Unavailable("backing off")
            try:
                return _remember(_refresh(kept, still=still), stamp)
            except _Moved:
                continue
    raise Unavailable("her sign-in's lock kept moving")


def _behind() -> None:
    """The refresh of a token that still has time, in a thread the process waits for at its exit (a rotation is never cut
    off by it): the requests go on with the token they have meanwhile."""
    if not _refreshing.acquire(blocking=False):
        return
    try:
        _now(REFRESH)
    except (NotSignedIn, Unavailable, OSError, ValueError) as e:
        log.info("her Grok sign-in's refresh behind the requests did not finish (%s)", type(e).__name__)
    finally:
        _refreshing.release()


def token(*, cached_for: float | None = None) -> str:
    """Her access token now. Within REFRESH seconds of its end it is refreshed behind this request (which goes with the
    token it has); within SOON seconds, first. A readiness check refreshes only one whose time is up. NotSignedIn,
    Unavailable. A cached-only caller requires that much remaining life and never starts a refresh."""
    stamp = _generation()
    with _mem:
        mine = dict(_memory) if _memory.get("generation") == stamp else {}
    if cached_for is not None:
        if _has(mine, cached_for) and stamp == _generation():
            return mine["access"]
        # The helper has two seconds, including the supervisor's peer and profile checks.
        kept = _kept(wait=1.0, report_failure=True)
        if stamp != _generation():
            raise Unavailable("sign-in changed while reading cached access")
        if kept is None:
            raise NotSignedIn("none")
        if not _has(kept, cached_for):
            raise Unavailable("cached access is not ready")
        return _remember(kept, stamp)
    if _has(mine, REFRESH):
        return mine["access"]
    soon = 5.0 if _checking["on"] else SOON
    if not _has(mine, soon):
        stamp = _generation()  # (before the Keychain is read: a sign-in landing meanwhile is read again, never cached as new)
        kept = _kept(report_failure=True)  # (another process may have refreshed it: read, never refreshed again)
        if kept is None:
            raise NotSignedIn("none")
        if _has(kept, 5) and float(kept.get("expires") or 0) > float(mine.get("expires") or 0):
            mine = dict(kept)
            _remember(kept, stamp)
    if _has(mine, soon):
        if not _checking["on"] and not _has(mine, REFRESH) and not _backing_off() and not _refreshing.locked():
            threading.Thread(target=_behind, name="grok-refresh", daemon=False).start()
        return mine["access"]
    try:
        return _now(soon)
    except Unavailable:
        if _has(mine, 5):
            return mine["access"]
        raise


def remaining_lifetime(access: str) -> int:
    """Whole seconds remaining for the access token returned to this process."""
    stamp = _generation()
    with _mem:
        if _memory.get("access") == access and _memory.get("generation") == stamp:
            return max(0, int(float(_memory["expires"]) - time.time()))
    return 0


def refused(used: str) -> str | None:
    """A model call made with this token was refused (401 or 403): a new token, to ask once more with, or None when the
    refusal is real (the token in use is new: refused again, it is the account, not the sign-in). NotSignedIn when its
    refresh is refused for good; Unavailable when a new one cannot be had now."""
    if _checking["on"]:
        return None
    for _ in range(3):
        stamp = _generation()
        with _locked() as still:
            kept = _kept()
            if kept is None:
                with _mem:
                    _memory.clear()
                raise NotSignedIn("none")
            if kept.get("access") and kept["access"] != used and _has(kept, SOON):
                return _remember(kept, stamp)  # (another request or process refreshed it meanwhile)
            if time.time() - float(kept.get("saved") or 0) < (HOLD if kept.get("forced") else FRESH) or _backing_off():
                return None  # (refused with a new one: the account, not the sign-in)
            try:
                return _remember(_refresh(kept, forced=True, still=still), stamp)
            except _Moved:
                continue
    raise Unavailable("her sign-in's lock kept moving")


# -- Signing in: xAI's device flow, in your browser, one at a time --

def _pending(unless_cancelled_since: float | None = None, **state) -> bool:
    """Write how a sign-in stands, under a short lock of its own, so a cancel and the helper's next state never cross: with
    unless_cancelled_since, nothing is written if it was cancelled since then (False)."""
    with closed_file(PENDING.with_name("grok-sign-in.pending.lock"), "w") as held:  # (never the refresh lock's own file)
        fcntl.flock(held, fcntl.LOCK_EX)
        if unless_cancelled_since is not None:
            said = _said()
            if said.get("state") == "cancelled" and float(said.get("at") or 0) >= unless_cancelled_since:
                return False
        with closed_file(PENDING.with_suffix(".tmp"), "w") as out:
            out.write(json.dumps({**state, "at": round(time.time(), 3)}))
        PENDING.with_suffix(".tmp").replace(PENDING)
    return True


def _said() -> dict:
    try:
        said = json.loads(PENDING.read_text())
        return said if isinstance(said, dict) else {}
    except (OSError, ValueError):
        return {}


def kept_since(t: float) -> bool:
    """Whether a sign-in of hers was kept after `t` (its own record: _approved's last step), never read from the Keychain:
    what the page last learned before then is no longer true (settings/runtime own_presence)."""
    said = _said()
    return said.get("state") == "signed_in" and float(said.get("at") or 0) > t


def _start_of(pid) -> str:
    """When a process started, as the system says it ("" when it is not there): with its pid, which process it is."""
    try:
        return subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return ""


def _alive(said: dict) -> bool:
    """The helper a sign-in names still runs: its pid, and its start (a pid the system gave another process is not it)."""
    return bool(said.get("pid")) and bool(said.get("started")) and _start_of(said["pid"]) == said["started"]


def status(on: bool | None = None) -> dict:
    """For the page: {"on": kept here, "setup": {"url", "code"} while a sign-in waits for you, "last": how the last one
    ended when it did not (see ENDED), "at": when that was}. Never a token. on: what the page
    already knows of the item (settings/runtime asks it once, briefly); else it is read here."""
    out: dict = {"on": signed_in() if on is None else on}
    said = _said()
    if said.get("state") == "waiting" and float(said.get("until") or 0) > time.time() and _alive(said):
        out["setup"] = {"url": str(said.get("url") or ""), "code": str(said.get("code") or "")}
    elif said.get("state") in ENDED and (not out["on"] or said["state"] == "keychain_locked"):
        out.update(last=said["state"], at=float(said.get("at") or 0))
    return out


def under_way() -> dict:
    """The sign-in starting or waiting now, as kept: {"state", "pid", "started", "at"} ({} when none is)."""
    said = _said()
    return said if said.get("state") in ("starting", "waiting") and _alive(said) else {}


def cancel() -> bool:
    """End a sign-in that waits (yours, from the page or a terminal): its helper sees it within a quarter of a second
    and keeps nothing (no signal is sent to any process). Whether one was waiting."""
    said = under_way()
    _pending(state="cancelled")
    return bool(said)


def begin() -> dict:
    """Ask auth.x.ai for a device code: {"device_code", "code", "url", "page", "until", "every"}."""
    status_, said = _ask(discovery(SIGN_IN_WAIT)["device_authorization_endpoint"], {"client_id": CLIENT_ID, "scope": SCOPE},
                         wait=SIGN_IN_WAIT)
    device, code, page = (str(said.get(k) or "") for k in ("device_code", "user_code", "verification_uri"))
    full = str(said.get("verification_uri_complete") or page)
    if status_ != 200 or not (device and code and page) or not trusted(page) or not trusted(full):
        raise Unavailable(f"device code {status_}")
    try:
        lasts, every = float(said.get("expires_in") or 600), max(1.0, float(said.get("interval") or 5))
    except (TypeError, ValueError):
        lasts, every = 600.0, 5.0
    return {"device_code": device, "code": code, "url": full, "page": page, "until": time.time() + lasts, "every": every}


def login(show=None, open_page: bool = True, sleep=None) -> str:
    """Sign her in: a code from auth.x.ai, its page opened in your browser (the code filled in), then asked every few
    seconds until you approve, refuse, cancel or its time is up. "signed_in", "denied", "expired", "failed", "cancelled",
    "keychain_locked" or "busy" (another sign-in is under way on this Mac). show(url, code): where a terminal says them."""
    try:
        device_lock = _locked("grok-sign-in.device.lock", wait=0)
        device_lock.__enter__()
    except Unavailable:
        return "busy"
    try:
        return _login(show, open_page, sleep)
    finally:
        device_lock.__exit__(None, None, None)


def _login(show, open_page: bool, sleep) -> str:
    me = {"pid": os.getpid(), "started": _start_of(os.getpid())}
    _pending(state="starting", **me)
    started = _said()["at"]

    def cancelled() -> bool:
        said = _said()
        return said.get("state") == "cancelled" and float(said.get("at") or 0) >= started

    def nap(seconds: float) -> None:  # (a quarter of a second at a time: a cancel ends it at once)
        end = time.monotonic() + seconds
        while time.monotonic() < end and not cancelled():
            time.sleep(min(0.25, max(0.0, end - time.monotonic())))

    try:
        flow = begin()
    except (Unavailable, ValueError) as e:
        if cancelled():
            return "cancelled"
        log.warning("her Grok sign-in could not start (%s)", e)
        _pending(state="failed")
        return "failed"
    if cancelled() or not _pending(unless_cancelled_since=started, state="waiting", url=flow["url"], code=flow["code"],
                                   until=round(flow["until"], 1), **me):  # (cancelled while its code was asked for: it stays so)
        return "cancelled"
    if show:
        show(flow["page"], flow["code"])
    if open_page:
        subprocess.run(["open", flow["url"]], capture_output=True, timeout=20, check=False)
    every, token_endpoint = flow["every"], discovery(SIGN_IN_WAIT)["token_endpoint"]
    while True:
        left = flow["until"] - time.time()
        if left <= 0 or cancelled():
            break
        (sleep or nap)(min(every, left))
        if time.time() >= flow["until"] or cancelled():  # (its time up, or ended: never asked, never kept)
            break
        status_, said = _ask(token_endpoint, {"grant_type": DEVICE_GRANT, "client_id": CLIENT_ID, "device_code": flow["device_code"]},
                             wait=min(SIGN_IN_WAIT, max(1.0, flow["until"] - time.time())))
        error = str(said.get("error") or "")
        if status_ == 200 and said.get("access_token") and said.get("refresh_token"):
            return _approved(said, flow["until"], cancelled)
        if error == "authorization_pending" or status_ == 0:
            continue
        if error == "slow_down":
            every += 5
            continue
        how = {"access_denied": "denied", "authorization_denied": "denied", "expired_token": "expired"}.get(error, "failed")
        log.warning("her Grok sign-in did not finish (%s %s)", status_, error or "no code")
        _pending(state=how)
        return how
    if cancelled():
        return "cancelled"
    _pending(state="expired")
    return "expired"


def _approved(said: dict, until: float, cancelled) -> str:
    """You approved it: kept, unless its time is up or it was cancelled meanwhile (then whatever was kept before stays,
    or is put back as it was)."""
    try:
        with _locked(wait=max(0.0, min(SIGN_IN_WAIT, until - time.time()))):
            before = _raw()
            if time.time() >= until or cancelled():  # (right before it is kept: its time, or a cancel)
                raise Unavailable("past its time")
            try:
                _keep(_tokens(said, None))
            except KeychainLocked:
                _pending(state="keychain_locked")
                return "keychain_locked"
            except (OSError, ValueError) as e:
                log.warning("her Grok sign-in was approved but could not be kept (%s)", type(e).__name__)
                _pending(state="failed")
                return "failed"
            if time.time() >= until or cancelled():  # (its time ran out, or it was cancelled, while it was kept: put back)
                if before:
                    with contextlib.suppress(OSError):
                        _put(before)
                else:
                    _forget()
                if cancelled():
                    return "cancelled"
                raise Unavailable("past its time")
    except Unavailable:
        if cancelled():
            return "cancelled"
        _pending(state="expired")
        return "expired"
    with _mem:
        _memory.clear()
    _bump()
    _backed()
    _pending(state="signed_in")
    log.info("her Grok sign-in is kept")
    return "signed_in"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "status":
        print("signed in" if signed_in() else "not signed in")
        sys.exit(0 if signed_in() else 1)
    if action == "cancel":
        sys.exit(0 if cancel() else 1)
    if action in ("login", "start"):
        terminal = action == "login"
        said = login(show=(lambda page, code: print(f"Open {page} and enter the code {code} (it opens in your browser now).",
                                                    flush=True)) if terminal else None)
        if terminal:
            print({"signed_in": "Signed in: her mind can use your Grok subscription.", "denied": "The sign-in was refused.",
                   "expired": "The code expired before it was approved. Run this again.",
                   "failed": "The sign-in could not finish. Try again in a moment.", "cancelled": "The sign-in was cancelled.",
                   "keychain_locked": UNLOCK_KEYCHAIN,
                   "busy": "Another sign-in is waiting for approval on this Mac: finish or cancel that one first."}[said])
        else:
            print(said)
        sys.exit(0 if said == "signed_in" else 1)
    sys.exit(2)
