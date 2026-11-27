"""Light's doorbell: where xPerfect's clock rings when a moment has come.

    .venv/bin/python -m core.doorbell        (./vx up starts it, on every profile)

A small always-on receiver on this Mac only (127.0.0.1). xPerfect sends a signed `schedule.due` notice
(Standard Webhooks: an id, a timestamp and an HMAC over both and the body); the doorbell checks who sent it,
keeps it (core/schedules.arrived) and only then answers 200. So a notice is never lost: xPerfect retries until it
is taken, and the same occurrence is kept once. It never wakes anyone itself: the always-on channel takes what
arrived at its next look (core/schedules.due).

It also keeps xPerfect's list like Light's (core/xclock.sync), and her own routines on the clock as they are set
(core/routines.ensure): when it starts, and every few minutes.

The signing secret is Light's own, made once and kept in the macOS Keychain (never in a file); xPerfect is told
it when the doorbell is first made known there.
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import routines, schedules, xclock

log = logging.getLogger("doorbell")
ITEM = ("viventium-light", "schedule-doorbell")  # the Keychain item: service, account
TOLERANCE = 300  # s a notice's own timestamp may differ from now (Standard Webhooks' own)
LIMIT = 262_144  # bytes (xPerfect's own largest body)
LOOK = 300  # s between looks at xPerfect's list


def secret() -> tuple[str, bool]:
    """The signing secret, and whether it was made just now (then xPerfect must be told it)."""
    if given := os.environ.get("DOORBELL_SECRET"):  # (a test's own)
        return given, True
    found = subprocess.run(["security", "find-generic-password", "-s", ITEM[0], "-a", ITEM[1], "-w"], capture_output=True, text=True)
    if found.returncode == 0 and found.stdout.strip():
        return found.stdout.strip(), False
    made = "whsec_" + base64.b64encode(os.urandom(32)).decode()
    # (through security's own input, never its command line, where any process could read it: as settings keeps keys)
    subprocess.run(["security", "-i"], input=f'add-generic-password -U -s "{ITEM[0]}" -a "{ITEM[1]}" -w "{made}"\n',
                   check=True, capture_output=True, text=True, timeout=20)
    return made, True


def signed(key: str, headers: dict, body: bytes, now: float | None = None) -> bool:
    """Whether xPerfect sent this, as it is, just now (Standard Webhooks: HMAC-SHA256 over "id.timestamp.body")."""
    try:
        sent = int(headers["webhook-timestamp"])
        if abs((now or time.time()) - sent) > TOLERANCE:
            return False
        ours = base64.b64encode(hmac.new(base64.b64decode(key.removeprefix("whsec_")),
                                         f'{headers["webhook-id"]}.{sent}.'.encode() + body, hashlib.sha256).digest()).decode()
        return any(hmac.compare_digest(part.partition(",")[2], ours) for part in headers["webhook-signature"].split() if part.startswith("v1,"))
    except (KeyError, ValueError):
        return False


def take(key: str, headers: dict, body: bytes) -> int:
    """One notice: the HTTP status it is answered with. 200 means kept, or not ours to keep (never sent again)."""
    if not signed(key, headers, body):
        return 401
    try:
        notice = json.loads(body)
        if notice.get("type") != "schedule.due":
            return 200
        data = notice.get("request_data") or {}
        if data.get("state") != xclock.TAG:  # another state's moment on the same xPerfect (a test's): not ours
            return 200
        kept = schedules.arrived(str(data["light"]), dt.datetime.fromisoformat(notice["scheduled_at"]), str(notice.get("occurrence_id", "")))
    except (KeyError, ValueError, TypeError):
        return 400
    log.info("due: %s (%s)", data["light"], "kept" if kept else "not ours to keep")  # (never its words)
    return 200


def serve(key: str, port: int = xclock.PORT) -> ThreadingHTTPServer:
    class Bell(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("content-length") or 0)
            if self.path != "/due" or size > LIMIT:
                self.send_response(404 if self.path != "/due" else 413); self.end_headers(); return
            code = take(key, {k.lower(): v for k, v in self.headers.items()}, self.rfile.read(size))
            self.send_response(code); self.end_headers()

        def do_GET(self):  # (./vx status and the keeper ask whether it is up)
            self.send_response(200 if self.path == "/" else 404); self.end_headers()

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Bell)
    threading.Thread(target=server.serve_forever, daemon=True, name="doorbell").start()
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    key, fresh = secret()
    serve(key)
    log.info("ready on 127.0.0.1:%s (xPerfect's clock: %s)", xclock.PORT, "on" if xclock.on() else "off; Light rings its moments itself")
    told = not fresh
    while True:
        try:  # her own routines, as they are set (the heartbeat's beat), also when the Scheduling page was never opened
            routines.ensure()
        except Exception:
            log.exception("routines")
        if xclock.on():
            try:
                did = xclock.sync(schedules.upcoming(True), "" if told else key)
                told = True
                if did["made"] or did["retired"] or did["switched"] or did["refused"]:
                    log.info("xPerfect's list put right: %s", {k: len(v) if isinstance(v, list) else v for k, v in did.items()})
            except Exception as e:  # (xPerfect is starting, or stopped: Light rings its moments itself meanwhile)
                if "not known to xPerfect" in str(e):
                    told = False
                log.warning("xPerfect's clock could not be reached: %s", type(e).__name__)
        time.sleep(LOOK if told else 20)


if __name__ == "__main__":
    main()
