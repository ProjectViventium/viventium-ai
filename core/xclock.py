"""xPerfect's clock, as Light uses it: one webhook destination (Light's doorbell) and one recurring schedule per
moment. xPerfect computes every time, keeps to it across restarts, retries a notice that was not taken, and stops
trying when a moment's window has passed. Light only says what it wants kept (push, retire, sync).

Which xPerfect: this profile's own (XPERFECT_API, XPERFECT_STATE). A schedule is tagged with the moment's id and
with whose state it belongs to, so two states that share an instance (yours, and a test's) never touch each
other's. On only where vx says so (see on()).

Proven on the pinned xPerfect (tests/xclock_test.py): the notice is signed (Standard Webhooks) and
on time; late inside the window it still comes; past it xPerfect records `expired`; a doorbell that was down gets
it on retry.
"""
import datetime as dt
import hashlib
import json
import os
import zoneinfo
from pathlib import Path

import httpx

from core.state import STATE_ROOT

PORT = int(os.environ.get("DOORBELL_PORT") or 8869)
NAME = "Viventium AI"
TAG = hashlib.sha256(str(STATE_ROOT.resolve()).encode()).hexdigest()[:12]  # whose moments these are
TIMING = ("recurrence_type", "local_time", "timezone_name", "cron_expression")  # the time a repeating moment keeps


def on() -> bool:
    """Only where vx says so (XCLOCK=on, the real setup). Never from a test's own state (VX_STATE): a test must not
    put its moments into your xPerfect. (XCLOCK=force: a test that brings its own throwaway xPerfect.)"""
    if not os.environ.get("XPERFECT_API") or not os.environ.get("XPERFECT_STATE"):
        return False
    how = os.environ.get("XCLOCK")
    return how == "force" or (how == "on" and not os.environ.get("VX_STATE"))


def _api() -> httpx.Client:
    token = json.loads((Path(os.environ["XPERFECT_STATE"]) / "secrets.json").read_text())["api_token"]
    return httpx.Client(base_url=os.environ["XPERFECT_API"], headers={"Authorization": f"Bearer {token}"}, timeout=5)


def _call(api: httpx.Client, method: str, path: str, body: dict | None = None):
    response = api.request(method, path, json=body)
    if response.is_error:
        raise RuntimeError(f"xPerfect {response.status_code}: {response.text[:200]}")
    return response.json()


def _named(name: str) -> str:
    """A zone name xPerfect can keep (IANA, e.g. "Europe/Paris"), or "" when it is none."""
    name = str(name or "").strip().lstrip(":").split("zoneinfo/")[-1]
    if not name:
        return ""
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return ""
    return name


def zone() -> str:
    """This Mac's time zone by name: TZ when it names one (a process told its zone), else the system's
    (/etc/localtime). xPerfect keeps a daily time through daylight saving."""
    return _named(os.environ.get("TZ", "")) or _named(os.path.realpath("/etc/localtime")) or "UTC"


def zone_of(item: dict) -> str:
    """The zone a repeating moment keeps: its own (item["zone"], when it was set in a named zone: "7:00, Paris time"),
    else this Mac's, so it follows the Mac when he travels."""
    return _named(item.get("zone", "")) or zone()


def destination(api: httpx.Client, secret: str = "") -> str:
    """The doorbell, as xPerfect knows it. Made once; with `secret`, its signing secret is set to ours (Light
    chooses the secret and keeps it in the Keychain: core/doorbell.py)."""
    url = f"http://127.0.0.1:{PORT}/due"
    mine = hashlib.sha256(url.encode()).hexdigest()
    for found in _call(api, "GET", "/v1/webhook-destinations")["items"]:
        if found.get("url_sha256") == mine and found.get("enabled", True):
            if secret:
                _call(api, "PATCH", f"/v1/webhook-destinations/{found['destination_id']}", {"secret": secret})
            return found["destination_id"]
    if not secret:
        raise RuntimeError("the doorbell is not known to xPerfect yet (core/doorbell.py makes it)")
    made = _call(api, "POST", "/v1/webhook-destinations", {"idempotency_key": f"light-doorbell-{PORT}-{mine[:16]}", "name": NAME,
                                                           "url": url, "secret": secret})
    return made["destination_id"]


def _when(item: dict) -> dict:
    """A moment's time, in xPerfect's terms. A late one is still told inside its window, the latest turn only. A
    repeating one is its wall-clock time in the zone it keeps (zone_of): Light keeps it as a wall time; one written
    with an offset is read in that zone, as Light reads it."""
    from core import schedules
    at = dt.datetime.fromisoformat(item["when"])
    late = {"misfire_grace_seconds": schedules.WINDOW[item["repeat"]], "catch_up_policy": "coalesce"}
    if not item["repeat"]:
        return {"recurrence_type": "once", "first_run_at": at.astimezone(dt.timezone.utc).isoformat(), **late}
    place = zone_of(item)
    if at.tzinfo is not None:
        at = at.astimezone(zoneinfo.ZoneInfo(place))
    if item["repeat"] == "daily":
        return {"recurrence_type": "daily", "local_time": at.strftime("%H:%M"), "timezone_name": place, **late}
    if item["repeat"] == "every":  # a beat: every so many minutes through her awake hours (Light drops one outside them)
        start, end = (list(map(int, item[k].split(":"))) for k in ("from", "to"))
        if item["every"] <= 60:
            minutes = ",".join(str(m) for m in sorted({(start[1] + k * item["every"]) % 60 for k in range(60 // item["every"])}))
            hours = f"{start[0]}-{end[0]}"
        else:
            minutes, hours = str(start[1]), f"{start[0]}-{end[0]}/{item['every'] // 60}"
        return {"recurrence_type": "cron", "cron_expression": f"{minutes} {hours} * * *", "timezone_name": place, **late}
    days = "1-5" if item["repeat"] == "weekdays" else str((at.weekday() + 1) % 7)  # (cron: 0 is Sunday)
    return {"recurrence_type": "cron", "cron_expression": f"{at.minute} {at.hour} * * {days}", "timezone_name": place, **late}


def _mine(api: httpx.Client, dest: str) -> dict:
    """This state's schedules at xPerfect, by moment id (a retired one is not listed)."""
    found = _call(api, "GET", f"/v1/recurring-schedules?destination_id={dest}&include_inactive=true")["items"]
    return {d["target"]["request_data"]["light"]: d for d in found
            if d["target"].get("request_data", {}).get("state") == TAG and not d.get("retired_at")}


def _make(api: httpx.Client, dest: str, item: dict) -> None:
    """A moment made at xPerfect. Its creation key names this body (a generation of the moment): made again after its
    old definition was retired, with another time or zone, it is a new creation, never xPerfect's 409 for a key whose
    body changed; the same body sent again stays the one schedule (a retry, a restart)."""
    body = {"target": {"kind": "webhook", "destination_id": dest, "request_data": {"light": item["id"], "state": TAG}},
            "instruction": "", "schedule_text": "A moment Viventium was asked to keep",  # (never its words: Light has them)
            "enabled": not item.get("paused"), **_when(item)}
    generation = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:10]
    body["idempotency_key"] = f"light-{TAG}-{item['id']}-{generation}"
    made, key = _call(api, "POST", "/v1/recurring-schedules", body), body["idempotency_key"]
    for generation in range(2, 50):  # (its key made a schedule that was retired since: the next generation's key, the
        if not made.get("retired_at"):  # same for a retry or a second try at once, so xPerfect keeps one schedule)
            break
        made = _call(api, "POST", "/v1/recurring-schedules", {**body, "idempotency_key": f"{key}-g{generation}"})


def _changed(known: dict, item: dict) -> bool:
    """Whether xPerfect keeps another time for this moment than Light has. A repeating moment: its time of day, its
    pace and hours, or the zone it keeps (a night routine set to another time, the heartbeat's pace, travel). It keeps
    its own named zone (item["zone"]), else this Mac's: a daily 07:00 is 07:00 where the Mac is now, unless it names
    a zone, which wins. A one-off is an instant: the one Light has is compared with the one xPerfect keeps, and the
    Mac's zone never moves it."""
    if known.get("clock_finished"):
        return False
    if not item["repeat"]:  # (a one-off: its instant against the one xPerfect keeps)
        kept = known.get("next_run_at") or known.get("starts_at") or ""
        try:
            there = dt.datetime.fromisoformat(str(kept).replace("Z", "+00:00"))
        except ValueError:
            return False
        here = dt.datetime.fromisoformat(_when(item)["first_run_at"])
        return there.tzinfo is not None and abs((there - here).total_seconds()) > 60
    want = _when(item)  # (xPerfect lists each field, "" where its kind has none; one it does not list is not compared)
    return any(key in known and (known[key] or "") != want.get(key, "") for key in TIMING)


def _retime(api: httpx.Client, known: dict, item: dict) -> None:
    """xPerfect keeps this moment at Light's time again, through its own update of the schedule it has (its version
    checked): never retired and made again, which xPerfect refuses under the same key (409) and which would lose it."""
    when = _when(item)
    if item["repeat"]:
        change = {k: when[k] for k in TIMING if k in when}
    else:
        change = {"starts_at": when["first_run_at"]}
    change["enabled"] = not item.get("paused")  # (a pause made at the same moment stays: one update carries both)
    _call(api, "PATCH", f"/v1/recurring-schedules/{known['definition_id']}",
          {**change, **({"expected_version": known["version"]} if known.get("version") else {})})


def _local_zone() -> None:
    """This process sees this Mac's time zone as it is now (a long-running process keeps the one it started with)."""
    import time
    if hasattr(time, "tzset"):
        time.tzset()


def push(item: dict) -> None:
    """This moment, kept by xPerfect as Light has it (made if new; paused or resumed if that changed)."""
    _local_zone()
    with _api() as api:
        dest = destination(api)
        have = _mine(api, dest).get(item["id"])
        if have is not None and _changed(have, item):  # (its time, pace, hours or zone changed: xPerfect's own one updated)
            _retime(api, have, item)
            return
        if have is None:
            _make(api, dest, item)
        elif have.get("enabled") != (not item.get("paused")) and not have.get("clock_finished"):
            _call(api, "PATCH", f"/v1/recurring-schedules/{have['definition_id']}", {"enabled": not item.get("paused")})


def retire(schedule_id: str) -> None:
    with _api() as api:
        have = _mine(api, destination(api)).get(schedule_id)
        if have is not None:
            _call(api, "DELETE", f"/v1/recurring-schedules/{have['definition_id']}")


def sync(items: list[dict], secret: str = "") -> dict:
    """xPerfect made to match Light's list: what is missing is made, what Light no longer has is retired, a pause
    is passed on. Run by the doorbell when it starts and every few minutes, so anything xPerfect did not hear at
    the time (it was stopped, or this profile's xPerfect is another one) is put right, and so is a moment kept in
    the time zone this Mac was in before (_changed)."""
    _local_zone()
    made, retired, switched = [], [], []
    with _api() as api:
        dest = destination(api, secret)
        have = _mine(api, dest)
        wanted = {i["id"]: i for i in items}
        refused = []
        for item_id, item in wanted.items():
            known = have.get(item_id)
            try:  # (one moment xPerfect will not take never stops the others; Light rings that one itself)
                if known is not None and _changed(known, item):
                    _retime(api, known, item)
                    switched.append(item_id)
                    continue
                if known is None:
                    _make(api, dest, item)
                    made.append(item_id)
                elif known.get("enabled") != (not item.get("paused")) and not known.get("clock_finished"):
                    _call(api, "PATCH", f"/v1/recurring-schedules/{known['definition_id']}", {"enabled": not item.get("paused")})
                    switched.append(item_id)
            except RuntimeError:
                refused.append(item_id)
        for item_id, known in have.items():
            if item_id not in wanted:
                _call(api, "DELETE", f"/v1/recurring-schedules/{known['definition_id']}")
                retired.append(item_id)
    return {"made": made, "retired": retired, "switched": switched, "refused": refused, "kept": len(wanted)}
