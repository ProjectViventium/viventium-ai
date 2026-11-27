"""Light's own Sign in with ChatGPT grant, stored by account and registration.

Protocol: https://developers.openai.com/siwc/token-sharing-open-source/sign-in
Session lifecycle: https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
"""
from __future__ import annotations

import base64
import ctypes as ct
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
import webbrowser
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

from core.state import STATE_ROOT, closed_dir, closed_file

NAME = "Viventium AI"
ITEM = "viventium-light/chatgpt_sign_in"
NEEDS = "chatgpt_mind"
MODEL = "gpt-6.1-sol"
ISSUER = "https://auth.openai.com"
API = "https://api.openai.com/v1"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
REVOKE = ISSUER + "/api/accounts/oauth/revoke"  # OpenAI's advertised revocation_endpoint
JWKS = ISSUER + "/.well-known/jwks.json"
USAGE = "https://chatgpt.com/settings/usage"
DYNAMIC = "dynamic_agent_client"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN = frozenset(("offline_access", "resource.invoke", "chatgpt.tokens.use.direct"))
CALLBACK = "/auth/callback"
TERMINAL_REFRESH = frozenset(("invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                               "refresh_token_invalidated", "refresh_token_reused"))
WAIT = 8.0
STOP_WORDS = {
    "limited": "The ChatGPT plan limit was reached.",
    "refused": "ChatGPT refused the plan request.",
    "unauthorized": "ChatGPT rejected the sign-in during the request.",
    "refresh_unavailable": "ChatGPT sign-in could not refresh.",
    "unavailable": "ChatGPT could not be reached.",
    "timeout": "ChatGPT did not answer in time.",
    "stale_session": "This request belongs to an earlier ChatGPT session.",
    "session_expired": "The ChatGPT session expired.",
    "grant_changed": "The ChatGPT grant changed.",
    "consent_changed": "The ChatGPT consent choice changed.",
    "account_changed": "The ChatGPT account changed.",
    "authorization_required": "Light could not authorize this ChatGPT request.",
    "signed_out": "Sign in to ChatGPT in Settings.",
    "scope_missing": "This ChatGPT connection is missing plan access.",
    "off": "ChatGPT plan use is off in Settings.",
    "revoking": "The ChatGPT connection is disconnecting.",
    "revoked": "The ChatGPT connection was revoked.",
    "revocation_unconfirmed": "Light cleared the ChatGPT connection. OpenAI did not confirm revocation.",
    "stream_ended": "The ChatGPT reply ended before it completed.",
    "model_unavailable": "This model is unavailable on the selected ChatGPT account.",
}


class SignInError(Exception):
    """A safe, local description. Provider-supplied text stays out of this exception."""


class NotSignedIn(SignInError):
    """The selected grant cannot authorize this use."""

    def __init__(self, state: str):
        self.state = state
        super().__init__(state)


class Unavailable(SignInError):
    """The provider or Keychain is temporarily unavailable."""


class Limited(Unavailable):
    """The selected plan route is paused."""


class NotEntitled(SignInError):
    """The selected model is absent from the account's catalog."""


def stop_state(error):
    if isinstance(error, NotSignedIn):
        return error.state
    if isinstance(error, Limited):
        return "limited"
    if isinstance(error, NotEntitled):
        return "model_unavailable"
    return "refresh_unavailable" if isinstance(error, Unavailable) else "unavailable"


def _redact(*values):
    from core import grok_sign_in

    grok_sign_in.redacting(*(value for value in values if isinstance(value, str) and value))


def _post(url, form):
    try:
        with httpx.Client(timeout=WAIT, follow_redirects=False, trust_env=False) as client:
            reply = client.post(url, data=form)
        return reply.status_code, _body(reply)
    except httpx.HTTPError:
        raise Unavailable("OpenAI sign-in could not be reached") from None


def _body(reply):
    try:
        value = reply.json()
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    return {}


def _identity(token, audience, nonce):
    try:
        with httpx.Client(timeout=WAIT, follow_redirects=False, trust_env=False) as client:
            reply = client.get(JWKS)
            reply.raise_for_status()
        keys = jwt.PyJWKSet.from_dict(reply.json())
        header = jwt.get_unverified_header(token)
        key = keys[header["kid"]]
        identity = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER, audience=audience,
                              options={"require": ["exp", "iss", "aud", "sub", "nonce"]})
        if identity["nonce"] == nonce and identity["sub"] and (
            isinstance(identity["aud"], str) or identity["aud"] == [audience] or identity.get("azp") == audience
        ):
            return identity
    except (KeyError, ValueError, TypeError, httpx.HTTPError, jwt.PyJWTError):
        pass
    raise SignInError("OpenAI signed identity could not be verified")


class Keychain:
    """Generic-password items. Use Security.framework so credentials never enter argv or a shell."""

    @staticmethod
    @cache
    def _framework():
        security = ct.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer, count = ct.c_void_p, ct.c_uint32
        security.SecKeychainFindGenericPassword.argtypes = [
            pointer, count, ct.c_char_p, count, ct.c_char_p, ct.POINTER(count), ct.POINTER(pointer), ct.POINTER(pointer)]
        security.SecKeychainAddGenericPassword.argtypes = [
            pointer, count, ct.c_char_p, count, ct.c_char_p, count, ct.c_char_p, pointer]
        security.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, count, ct.c_char_p]
        security.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
        security.SecKeychainSetUserInteractionAllowed.argtypes = [ct.c_ubyte]
        security.SecKeychainSetUserInteractionAllowed(0)  # A locked Keychain returns an error instead of holding the UI.
        core = ct.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        core.CFRelease.argtypes = [pointer]
        core.CFRelease.restype = None
        return security, core

    @contextmanager
    def _find(self, account):
        security, core = self._framework()
        label = ITEM.encode()
        name = account.encode()
        count, data, item = ct.c_uint32(), ct.c_void_p(), ct.c_void_p()
        status = security.SecKeychainFindGenericPassword(None, len(label), label, len(name), name,
                                                         ct.byref(count), ct.byref(data), ct.byref(item))
        try:
            if status not in (0, -25300):  # errSecItemNotFound
                raise Unavailable("Light could not read its ChatGPT item in Keychain")
            yield security, item, ct.string_at(data, count.value) if data else None
        finally:
            if data:
                security.SecKeychainItemFreeContent(None, data)
            if item:
                core.CFRelease(item)

    def get(self, account):
        with self._find(account) as (_, _, value):
            return json.loads(value) if value else {}

    def put(self, account, value):
        content = json.dumps(value, separators=(",", ":")).encode()
        with self._find(account) as (security, item, _):
            if item:
                status = security.SecKeychainItemModifyAttributesAndData(item, None, len(content), content)
            else:
                service, name = ITEM.encode(), account.encode()
                status = security.SecKeychainAddGenericPassword(None, len(service), service, len(name), name,
                                                                len(content), content, None)
            if status:
                raise Unavailable("Light could not update its ChatGPT item in Keychain")


def _credentials(reply, before=None):
    _redact(*(reply.get(name) for name in ("access_token", "refresh_token", "id_token")))
    before = before or {}
    scope = reply.get("scope", " ".join(before.get("scope", ())))
    if not isinstance(scope, str):
        raise SignInError("OpenAI returned an invalid scope")
    scopes = scope.split()
    if not PLAN.issubset(scopes):
        renewable = reply.get("refresh_token", before.get("refresh"))
        return {"state": "scope_missing", "scope": scopes,
                **({"refresh": renewable} if isinstance(renewable, str) and renewable else {})}
    access = reply.get("access_token")
    refresh = reply.get("refresh_token", before.get("refresh"))
    expires = reply.get("expires_in")
    if not (isinstance(access, str) and access and isinstance(refresh, str) and refresh
            and type(expires) in (int, float) and 0 < expires < 86400 * 365
            and str(reply.get("token_type", "")).lower() == "bearer"):
        raise SignInError("OpenAI did not return usable plan credentials")
    return {"state": "connected", "scope": scopes, "access": access, "refresh": refresh,
            "expires": time.time() + expires}


@dataclass(frozen=True)
class Authorization:
    account: str
    session: str
    token: str = field(repr=False)
    expires: float = 0
    revision: str = ""


class Connection:
    def __init__(self, folder: Path, keys=None):
        self.folder = folder
        self.file = folder / "connection.json"
        self.keys = Keychain() if keys is None else keys

    @contextmanager
    def _locked(self):
        with closed_file(self.folder / "connection.lock", "a") as lock:
            until = time.monotonic() + WAIT
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise Unavailable("Light's ChatGPT connection is busy") from None
                    time.sleep(0.03)
            data = self._read()
            before = json.dumps(data, sort_keys=True)
            yield data
            after = json.dumps(data, sort_keys=True)
            if before != after:
                tmp = self.file.with_suffix(".tmp")
                with closed_file(tmp) as f:
                    f.write(after)
                tmp.replace(self.file)

    def _read(self):
        try:
            return json.loads(self.file.read_text())
        except FileNotFoundError:
            return {}

    def _get(self, account):
        kept = self.keys.get(account) if account else {}
        _redact(kept.get("access"), kept.get("refresh"), kept.get("id"))
        return kept

    @contextmanager
    def begin(self, account=None, *, wait=300, consent=False, callback_allowed=None, exclusive=False):
        """Start a new account, or reauthorize the selected registration. Browser opens after bind."""
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        with _QuietHTTPServer(("127.0.0.1", 0), _Callback) as server:
            server.timeout = 0.25
            redirect = f"http://127.0.0.1:{server.server_port}{CALLBACK}"
            with self._locked() as data:
                if exclusive and data.get("pending") and data.get("pending_until", 0) > time.time():
                    raise SignInError("ChatGPT sign-in is already open")
                if account is not None and account not in data.get("accounts", []):
                    raise SignInError("This ChatGPT registration is unknown")
                known = self._get(account)
                host = data.setdefault("host", f"urn:uuid:{uuid.uuid4()}")
                data.update(pending=state, pending_until=time.time() + wait)
                data.pop("last", None)
            query = dict(client_id=known.get("client", DYNAMIC), ext_agent_host_id=host, response_type="code",
                         redirect_uri=redirect, scope=SCOPE, resource=API, state=state, nonce=nonce,
                         code_challenge_method="S256",
                         code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))
            if not known:
                query["agent_name_hint"] = NAME
            if consent:
                query["prompt"] = "consent"
            # The documented returning flow also works via the account selector, with no identity token in a URL.
            attempt = _Attempt(self, server, query, verifier, account, known, time.monotonic() + wait)
            attempt.callback_allowed = callback_allowed
            server.attempt = attempt
            try:
                yield attempt
            finally:
                self.cancel(state)

    def cancel(self, state=None):
        with self._locked() as data:
            if state is None or data.get("pending") == state:
                data.pop("pending", None)
                data.pop("pending_until", None)

    def login(self, account=None, *, show=webbrowser.open, wait=300, consent=False,
              callback_allowed=None, exclusive=False):
        with self.begin(account, wait=wait, consent=consent,
                        callback_allowed=callback_allowed, exclusive=exclusive) as attempt:
            show(attempt.url)
            while not attempt.done and time.monotonic() < attempt.until:
                if self._read().get("pending") != attempt.state:
                    raise SignInError("ChatGPT sign-in was cancelled")
                attempt.server.handle_request()
            if attempt.result is None:
                with self._locked() as data:
                    if data.get("pending") == attempt.state:
                        data["last"] = ("denied" if attempt.error == "ChatGPT consent was denied" else
                                        "failed" if attempt.error else "expired")
                raise SignInError(attempt.error or "ChatGPT sign-in expired")
            return attempt.result

    def status(self):
        data = self._read()
        account = data.get("active")
        kept = self._get(account)
        state = kept.get("state", "signed_out")
        if state == "connected" and kept.get("expires", 0) <= time.time() and not kept.get("refresh"):
            state = "session_expired"
        if state == "connected" and data.get("limits", {}).get(self._owner(kept), 0) > time.time():
            state = "limited"
        if state == "connected" and kept.get("refresh_after", 0) > time.time():
            state = "refresh_unavailable"
        elif state == "connected" and kept.get("access_refused"):
            state = "unauthorized"
        catalog = data.get("catalog", {})
        return {"account": account, "state": state,
                "email": kept.get("email"), "name": kept.get("name"),
                "models": catalog.get("models") if catalog.get("session") == kept.get("session") else None,
                "usage": USAGE, "last": data.get("last"),
                "pending": bool(data.get("pending")) and data.get("pending_until", 0) > time.time()}

    def registrations(self):
        return [{"account": account, "email": kept.get("email"),
                 "workspace": kept.get("workspace") or f"Workspace {position}"}
                for position, account in enumerate(self._read().get("accounts", []), 1)
                if (kept := self._get(account))]

    def save_catalog(self, grant, models):
        with self._locked() as data:
            self._selected(data, using=grant)
            data["catalog"] = {"session": grant.session, "models": list(models)}

    def refresh_catalog(self):
        """Get account metadata without submitting an inference request."""
        grant = self.authorization()
        try:
            with httpx.Client(timeout=WAIT, follow_redirects=False, trust_env=False) as client:
                reply = client.get(API + "/models", headers={"Authorization": f"Bearer {grant.token}"})
                if not reply.is_success:
                    return
                self.save_catalog(grant, model_slugs(_body(reply)))
        except httpx.HTTPError:
            raise Unavailable("ChatGPT model catalog could not be reached") from None

    def _selected(self, data, using=None):
        from core.provider_switch import turned_off
        from core.state import logs

        if turned_off(NEEDS, marker=logs() / f"{NEEDS}.off"):
            raise NotSignedIn("off")
        account = data.get("active")
        kept = self._get(account)
        if kept.get("state") != "connected":
            raise NotSignedIn(kept.get("state", "signed_out"))
        if using and (account, kept["session"]) != (using.account, using.session):
            raise NotSignedIn("account_changed")
        return account, kept

    def authorization(self, refused: Authorization | None = None, *, admitted=None):
        with self._locked() as data:
            account, kept = self._selected(data, using=refused)
            if admitted and (account, kept["session"], kept.get("revision", "")) != (
                    admitted.account, admitted.session, admitted.revision):
                raise NotSignedIn("stale_session")
            if data.get("limits", {}).get(self._owner(kept), 0) > time.time():
                raise Limited("ChatGPT plan use is temporarily limited")
            failed = kept.get("access_refused") or (refused is not None and kept["access"] == refused.token)
            if kept.get("refresh_after", 0) > time.time() and (failed or kept["expires"] < time.time() + 30):
                raise Unavailable("ChatGPT plan sign-in could not be refreshed")
            error = None
            if failed or kept["expires"] < time.time() + 30:
                if kept.get("refresh"):
                    kept, error = self._refresh(account, kept)
                elif failed or kept["expires"] <= time.time():
                    raise NotSignedIn("session_expired")
            if error is None:
                return Authorization(account, kept["session"], kept["access"], kept["expires"], kept.get("revision", ""))
        raise error

    def _refresh(self, account, kept):
        try:
            status, body = _post(TOKEN, {"grant_type": "refresh_token", "client_id": kept["client"],
                                         "refresh_token": kept["refresh"], "resource": API})
        except Unavailable:
            status, body = 503, {}
        if status == 200:
            updated = _credentials(body, kept)
            if updated["state"] == "connected":
                kept.update(updated, refresh_after=0, access_refused=False)
                self.keys.put(account, kept)
                return kept, None
            self.keys.put(account, {**{k: kept.get(k) for k in ("subject", "client", "email", "workspace")}, **updated})
            return kept, NotSignedIn("scope_missing")
        if body.get("error") in TERMINAL_REFRESH:
            self._clear(account, kept, "revoked")
            return kept, NotSignedIn("revoked")
        kept["refresh_after"] = time.time() + 30
        self.keys.put(account, kept)
        return kept, Unavailable("ChatGPT plan sign-in could not be refreshed")

    def ensure_current(self, grant: Authorization):
        _, kept = self._selected(self._read(), using=grant)
        if kept.get("revision", "") != grant.revision:
            raise NotSignedIn("consent_changed")
        if kept["access"] != grant.token:
            raise NotSignedIn("grant_changed")
        if kept.get("access_refused"):
            raise NotSignedIn("unauthorized")
        if grant.expires <= time.time():
            raise NotSignedIn("session_expired")
        return kept

    def mark_refused(self, grant: Authorization):
        with self._locked() as data:
            account, kept = self._selected(data, using=grant)
            if kept["access"] == grant.token:
                self.keys.put(account, {**kept, "access_refused": True})

    @staticmethod
    def _owner(kept):
        return hashlib.sha256(kept["subject"].encode()).hexdigest()

    def pause(self, grant: Authorization, seconds=60):
        with self._locked() as data:
            _, kept = self._selected(data, using=grant)
            limits = data.setdefault("limits", {})
            owner = self._owner(kept)
            limits[owner] = max(limits.get(owner, 0), time.time() + max(1, seconds))

    def disconnect(self):
        """Stop this registration. Return whether OpenAI confirmed remote revocation."""
        with self._locked() as data:
            data.pop("pending", None)
            data.pop("pending_until", None)
            data.pop("last", None)
            account = data.get("active")
            kept = self._get(account)
            if not kept:
                return True
            if not kept.get("refresh"):
                confirmed = kept.get("state") != "revocation_unconfirmed"
            else:
                self.keys.put(account, {**kept, "state": "revoking"})
                form = {"token": kept["refresh"], "token_type_hint": "refresh_token", "client_id": kept["client"]}
                status = 503
                for _ in range(2):
                    with suppress(Unavailable):
                        status, _ = _post(REVOKE, form)
                    if status < 500:
                        break
                    time.sleep(0.2)
                confirmed = status == 200
            self._clear(account, kept, "revoked" if confirmed else "revocation_unconfirmed")
            return confirmed

    def _clear(self, account, kept, state):
        self.keys.put(account, {**{k: kept.get(k) for k in ("subject", "client", "email", "workspace")}, "state": state})


class _Attempt:
    def __init__(self, connection, server, query, verifier, account, known, until):
        self.connection, self.server, self.query, self.verifier = connection, server, query, verifier
        self.account, self.known, self.until = account, known, until
        self.done, self.result, self.error = False, None, None
        self.state = query["state"]

    @property
    def url(self):
        return f"{AUTHORIZE}?{urlencode(self.query)}"

    def complete(self, query):
        values = parse_qs(query, keep_blank_values=True, max_num_fields=20)
        if any(len(v) != 1 for v in values.values()):
            raise SignInError("Invalid ChatGPT callback")
        params = {key: v[0] for key, v in values.items()}
        if not hmac.compare_digest(params.get("state", "").encode(), self.state.encode()):
            raise SignInError("ChatGPT callback state did not match")
        if self.callback_allowed is not None and not self.callback_allowed():
            raise SignInError("Waiting for bench approval")
        with self.connection._locked() as data:
            self._current(data)
        self.done = True
        if params.get("error"):
            raise SignInError("ChatGPT consent was denied" if params["error"] == "access_denied" else "ChatGPT sign-in failed")
        client = params.get("client_id", self.known.get("client", ""))
        code = params.get("code")
        if not code or client == DYNAMIC or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", client) or (
            self.account and client != self.known["client"]
        ):
            raise SignInError("ChatGPT did not return the expected registration")
        _redact(code)
        status, reply = _post(TOKEN, {"grant_type": "authorization_code", "client_id": client, "code": code,
                                     "code_verifier": self.verifier, "redirect_uri": self.query["redirect_uri"],
                                     "resource": API})
        _redact(*(reply.get(key) for key in ("id_token", "access_token", "refresh_token")))
        if status != 200 or not isinstance(reply.get("id_token"), str):
            raise SignInError(f"ChatGPT code exchange returned HTTP {status}" if status != 200
                              else "ChatGPT code exchange did not return an ID token")
        identity = _identity(reply["id_token"], client, self.query["nonce"])
        subject = identity["sub"]
        if self.account and subject != self.known["subject"]:
            raise SignInError("ChatGPT returned a different account")
        kept = _credentials(reply)
        if not kept["scope"] or "openid" not in kept["scope"]:
            raise SignInError("ChatGPT did not grant identity scope")
        host = self.query["ext_agent_host_id"]
        account = hashlib.sha256(f"{host}\0{client}\0{subject}".encode()).hexdigest()
        with self.connection._locked() as data:
            self._current(data, exchanged=True)
            previous = self.connection._get(account)
            self.connection.keys.put(account, {**kept, "id": reply["id_token"], "client": client, "subject": subject,
                                               "email": identity.get("email"), "name": identity.get("name"),
                                               "workspace": identity.get("workspace_name") or previous.get("workspace"),
                                               "session": uuid.uuid4().hex})
            entries = data.setdefault("accounts", [])
            if account not in entries:
                entries.append(account)
            data["active"] = account
            data.pop("pending", None)
            data.pop("pending_until", None)
        return account

    def _current(self, data, *, exchanged=False):
        if time.monotonic() >= self.until or data.get("pending") != self.state or (self.done and not exchanged):
            raise SignInError("ChatGPT sign-in expired")


class _Callback(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def do_GET(self):
        url = urlsplit(self.path)
        attempt = self.server.attempt
        status, message = 400, "This ChatGPT sign-in callback is invalid or expired."
        if url.path == CALLBACK and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}":
            try:
                attempt.result = attempt.complete(url.query)
                status, message = 200, "Sign-in finished. Return to Viventium AI."
            except SignInError as error:
                if attempt.done:
                    attempt.error = str(error)
                    message = attempt.error
            except (ValueError, OSError):
                attempt.error = "ChatGPT sign-in could not be saved"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(message.encode())

    def log_message(self, *_):
        pass  # Callback URLs contain one-use codes. Never log a request or its arguments.


class _QuietHTTPServer(HTTPServer):
    def handle_error(self, request, client_address):
        pass  # A failed socket or callback must not dump a traceback or request data.


connection = Connection(STATE_ROOT / "core" / "chatgpt-sign-in")


def model_slugs(body):
    rows = body.get("models")
    if not isinstance(rows, list):
        raise Unavailable("Unexpected ChatGPT model catalog")
    return tuple(row["slug"] for row in rows if isinstance(row, dict)
                 and row.get("visibility") == "list" and isinstance(row.get("slug"), str))


def browser_login(account=None, *, consent_file=None, wait=300, consent=False):
    """Open the system browser or hand consent to whoever runs an isolated bench."""
    if consent_file is None:
        saved = connection.login(account, wait=wait, consent=consent, exclusive=True)
        with suppress(OSError, SignInError):
            connection.refresh_catalog()
        return saved
    path = Path(consent_file)

    def publish(url):
        with closed_file(path) as out:
            out.write(url + "\n")

    def approved():
        try:
            return path.with_name("approved").stat().st_mtime_ns > path.stat().st_mtime_ns
        except OSError:
            return False

    saved = connection.login(account, show=publish, wait=wait, consent=consent,
                             callback_allowed=approved, exclusive=True)
    with suppress(OSError, SignInError):
        connection.refresh_catalog()
    return saved


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Connect Viventium AI to ChatGPT")
    parser.add_argument("action", choices=("login", "status", "accounts", "cancel", "disconnect"))
    parser.add_argument("--account")
    parser.add_argument("--consent", action="store_true", help="Ask again for permission to use the selected plan")
    parser.add_argument("--consent-file", type=Path, help="Send a new browser URL to the bench consent handoff")
    parser.add_argument("--wait", type=float, default=300)
    args = parser.parse_args()

    try:
        if args.action == "login":
            account = browser_login(args.account, wait=args.wait, consent=args.consent,
                                    consent_file=args.consent_file)
            print(json.dumps({"account": account, "state": connection.status()["state"]}))
        elif args.action == "status":
            print(json.dumps(connection.status()))
        elif args.action == "accounts":
            print(json.dumps(connection.registrations()))
        elif args.action == "cancel":
            connection.cancel()
        else:
            print(json.dumps({"revocation_confirmed": connection.disconnect()}))
    except SignInError as error:
        print(str(error))
        raise SystemExit(1) from None
    except OSError:
        print("ChatGPT sign-in action could not finish on this Mac.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
