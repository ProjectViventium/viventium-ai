"""./vx doctor: what is wrong, in plain words, and what to do about it. "Nothing is wrong" when that is true.

vx gathers what only it knows (which parts this profile needs and which are not running, what `./vx ready`
says, whether it was stopped on purpose, whether it starts with this Mac) and hands it over; this file looks
at the rest (disk, memory, macOS holding the keeper back, reminders, backups and optional writes) and says
it all in one place.

The optional-write report reads counts for fixed failure kinds.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from core import backup, resources, state
from core.harness_status import Connection, connection

KEEPER_NOTE = Path.home() / "Library" / "Application Support" / "Viventium Light" / "keep.json"  # (tools/menubar/main.swift)
LOW_DISK_GB, NO_WORK_DISK_GB = 20, 5   # an install always leaves 20 GB; under about 4 GB her Workers refuse new work
KEEPER_QUIET = 600                     # s without a word from the keeper (it looks every 120) before saying so

# What a part of Viventium is called in plain words (vx's own names for them on the left).
PARTS = {"agent": "the part that answers calls", "telegram": "Telegram", "clock": "the clock for reminders",
         "doors": "the doors for your phone", "phone-address": "the call server at this Mac's new address for your phone",
         "doorbell": "the doorbell for reminders",
         "livekit": "the call server", "ui": "the page", "workers": "the Workers",
         "workers-on-this-mac": "the Workers on this Mac",
         "embed-model": "memory by meaning", "model": "the model on this Mac", "worker-model": "the helper model on this Mac",
         "stt": "listening on this Mac", "tts": "the voice on this Mac"}


def errors(logs: Path, now: float | None = None) -> Counter:
    """Counts from the last 24 hourly buckets in the optional-write record."""
    try:
        buckets = state.recent_optional_failures(logs / state.OPTIONAL_FAILURES_FILE,
                                                int((time.time() if now is None else now) // 3600))
    except OSError:
        return Counter()
    found = Counter()
    for counts in buckets.values():
        found.update(counts)
    return found


def pressure() -> int:
    """macOS's own verdict on memory this minute: 1 normal, 2 short, 4 critical. (How much has been pushed to
    disk says nothing by itself: it stays high long after a squeeze has passed. 16 GB there, level 1.)"""
    try:
        return int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 1


def memory_gb() -> float:
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout) / 2**30
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def report(facts: dict) -> tuple[list[str], list[str]]:
    """The lines to say, and the things that need the owner (empty: nothing is wrong).

    facts: profile, missing [part names], stopped, ready_code, ready_text, autostart, local_models, telegram,
    free_gb, memory_gb, pressure, keeper (ok | blocked | silent), reminders, clock_running, last_backup (datetime or None),
    errors (as errors() returns)."""
    lines, wrong = [], []

    def say(ok: bool, good: str, bad: str = "", fix: str = "") -> None:
        lines.append(("  ok   " if ok else "  !!   ") + (good if ok else bad))
        if not ok:
            if fix:
                lines.append("         " + fix)
            wrong.append(bad)

    name = str(facts.get("profile") or "").capitalize() or "Viventium"
    missing = facts.get("missing") or []
    # (vx keep look: the parts gone, then "held:" and the ones whose port another program holds, so they cannot start)
    held = missing[missing.index("held:") + 1:] if "held:" in missing else []
    missing = missing[:missing.index("held:")] if "held:" in missing else missing
    if facts.get("stopped"):
        lines.append("  --   Viventium is stopped, because you stopped it. Start it: ./vx up")
    else:
        parts = ", ".join(PARTS.get(m, m) for m in missing)
        say(not missing, f"Running: everything {name} needs is up.", f"Not running: {parts}.",
            "Start it: ./vx up   (with \"Start when this Mac starts\" on, it comes back by itself within two minutes)")
        if held:
            say(False, "", f"Cannot start: another program holds the port of {', '.join(PARTS.get(m, m) for m in held)}.",
                "Quit that program (./vx status names the port), then ./vx up.")
    ready = (facts.get("ready_text") or "").strip()
    say(facts.get("ready_code", 0) == 0, f"Can start: {name} has what it needs on this Mac.",
        "Cannot start as it is set: " + (ready.splitlines()[-1] if ready else "it did not say why."),
        "\n         ".join(ready.splitlines()[:-1]))
    free = facts.get("free_gb", 0.0)
    say(free >= LOW_DISK_GB, f"Disk: {free:.0f} GB free.",
        f"Disk: only {free:.0f} GB free." + (" The Workers refuse new work under about 4 GB." if free < NO_WORK_DISK_GB else ""),
        "Free some space (a full disk can break things).")
    have = facts.get("memory_gb", 0.0)
    need = facts.get("resources") or resources.requirements(str(facts.get("profile") or "local"))
    say(have >= need.memory_gb, f"Memory: {have:.0f} GB; this profile needs {need.memory_gb}.",
        f"Memory: this Mac has {have:.0f} GB and this profile needs {need.memory_gb}.", resources.recovery(have))
    say(facts.get("pressure", 1) < 2, "Memory right now: not under pressure.",
        "Memory right now: macOS says this Mac is " + ("critically " if facts.get("pressure", 1) >= 4 else "") + "short. Viventium will be slow.",
        "Close other heavy programs.")
    if facts.get("autostart"):
        keeper = facts.get("keeper", "ok")  # what the keeper last wrote: let in, held back, or nothing for a while
        if keeper == "blocked":
            say(False, "", "Starting with this Mac: on, but macOS is holding it back, so nothing starts by itself.",
                "System Settings › Privacy & Security › Files and Folders: allow Viventium (macOS asks once).")
        else:
            say(keeper == "ok", "Starting with this Mac: on, and macOS lets it.",
                "Starting with this Mac: on, but its keeper has not been heard from (it looks every two minutes).",
                "Turn it off and on again in Settings › System, or: ./vx autostart on")
    else:
        lines.append("  --   Starting with this Mac: off. (Settings › System turns it on.)")
    count = facts.get("reminders", 0)
    if count and not facts.get("stopped"):
        who = "Telegram" if facts.get("telegram") else "this Mac's clock"
        say(bool(facts.get("clock_running")), f"Reminders: {count} set; {who} will say them when they come.",
            f"Reminders: {count} set, but nothing is watching the time.", "./vx up brings the clock back.")
    else:
        lines.append(f"  --   Reminders: {count} set." if count else "  --   Reminders: none set.")
    last = facts.get("last_backup")
    if last is None:
        lines.append("  --   Backups: none yet. Make one: ./vx backup")
    else:
        days = (dt.datetime.now() - last).days
        lines.append(f"  --   Backups: the last one is from {'today' if days == 0 else f'{days} day(s) ago'}. Another: ./vx backup")
    lines.extend((facts.get("source") or "").splitlines())
    found = facts.get("errors") or Counter()
    if found:
        lines.append(f"  --   Optional writes: {sum(found.values())} failure(s) in the last day.")
        for kind, count in found.most_common():
            lines.append(f"         {count} × {state.OPTIONAL_FAILURES[kind]}.")
    else:
        lines.append("  ok   Optional write failures in the last day: none.")
    return lines, wrong


# -- After a restore: what this Mac still lacks (keys, sign-ins, a bot, a paired phone never travel in a backup) --

KEY_NAMES = {"ASSEMBLYAI_API_KEY": "AssemblyAI", "XAI_API_KEY": "SpaceXSI", "OPENAI_API_KEY": "OpenAI", "ANTHROPIC_API_KEY": "Anthropic"}
# Each native status command is read by its exit contract. Grok models cannot prove a sign-in.
SIGN_INS = {"claude-code": ("Claude", ["claude", "auth", "status"]), "codex-cli": ("ChatGPT", ["codex", "login", "status"]),
            "grok-build": ("Grok", ["grok", "models"])}


def key_item(name: str, env: dict) -> str:
    """Where vx keeps a key in the Keychain (NAME_ITEM in a private profile file overrides): vx's key_item()."""
    provider = name.removesuffix("_API_KEY").lower()
    return env.get(f"{name}_ITEM") or f"viventium/{'x_ai' if provider == 'xai' else provider}_api_key"


def in_keychain(item: str) -> bool:
    """Whether the Keychain holds an item (its name asked; never its value)."""
    try:
        return subprocess.run(["security", "find-generic-password", "-s", item], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def signed_in(harness: str, run=subprocess.run) -> bool:
    """Whether the native status contract proves this harness is signed in."""
    name, command = SIGN_INS[harness]
    try:
        done = run(command, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return connection(harness, done.returncode) == Connection.CONNECTED


def reconnect(env: dict, has=in_keychain, signed=signed_in) -> list[str]:
    """What to connect again on this Mac for the profile just restored, in plain words, each with where to do it: the keys
    it uses, the sign-ins its Workers run on, its Telegram bot, a phone paired before. A backup never holds a key, a
    sign-in or a pairing; none when everything is here. has / signed: how the Keychain and a sign-in are asked."""
    keys = []
    if env.get("STT") == "assemblyai":
        keys.append("ASSEMBLYAI_API_KEY")
    if env.get("TTS") == "xai" or env.get("QUEEN") == "xai":
        keys.append("XAI_API_KEY")
    if env.get("QUEEN") in ("openai", "anthropic"):
        keys.append(f"{env['QUEEN'].upper()}_API_KEY")
    off = env.get("KEYS_OFF", "").split()
    lines = [f"Your {KEY_NAMES[k]} key: Settings, System, Add API key." for k in dict.fromkeys(keys)
             if k not in off and not env.get(k) and not has(key_item(k, env))]
    from core.grok_sign_in import ITEM as GROK_ITEM, NEEDS as GROK
    grok_asked = env.get("QUEEN") == "xai_plan" and GROK not in off and not has(GROK_ITEM)
    if grok_asked:  # (her mind on your Grok subscription)
        lines.append("Your Grok sign-in for the conscious mind: Settings, System, SpaceXSI, Sign in.")
    if env.get("WORKERS") == "signed-in":
        for harness in dict.fromkeys([env.get("WORKER_PROFILE", ""), *env.get("WORKER_FALLBACK", "").split(",")]):
            if harness == "grok-build":  # vx shares Light's sign-in with this Worker, never the CLI's model list
                if GROK not in off and not has(GROK_ITEM) and not grok_asked:
                    lines.append("Your Grok sign-in for the Workers: Settings, System, SpaceXSI, Sign in.")
                    grok_asked = True
                continue
            if harness in SIGN_INS and not signed(harness):
                lines.append(f"Your {SIGN_INS[harness][0]} sign-in for the Workers: Settings, System, Log in to subscription.")
    if env.get("TELEGRAM", "on") != "off" and not has(env.get("TELEGRAM_TOKEN_ITEM") or "viventium-light/telegram_bot_token"):
        lines.append("Your Telegram bot, if you used one: ./vx telegram.")
    if env.get("VX_LAN_ORIGIN"):
        lines.append("Your phone, if you call from it: pair it again (Settings, Channels, Phone).")
    return lines


def gather(args) -> dict:
    logs = state.logs()
    try:  # (the keeper writes this each round, every two minutes: tools/menubar/main.swift)
        note = json.loads(Path(os.environ.get("VX_KEEPER_NOTE") or KEEPER_NOTE).read_text())
        keeper = "blocked" if note.get("blocked") else "ok" if time.time() - float(note.get("at", 0)) < KEEPER_QUIET else "silent"
    except (OSError, ValueError, TypeError):
        keeper = "silent"
    try:
        from core import schedules
        reminders = len(schedules.upcoming())
    except (OSError, ValueError):
        reminders = 0
    kept = backup.backups()
    try:
        last = dt.datetime.fromisoformat(json.loads((kept[0] / backup.MANIFEST).read_text())["made"]) if kept else None
    except (OSError, ValueError, KeyError):
        last = None
    missing = args.missing.split()
    return {"profile": args.profile, "missing": missing, "stopped": args.stopped, "ready_code": args.ready_code,
            "ready_text": Path(args.ready_file).read_text() if args.ready_file and Path(args.ready_file).exists() else "",
            "resources": resources.requirements(args.profile or "local"),
            "autostart": args.autostart, "local_models": args.local_models, "telegram": args.telegram,
            "free_gb": shutil.disk_usage(Path.home()).free / 1e9, "memory_gb": memory_gb(), "pressure": pressure(),
            "keeper": keeper, "reminders": reminders,
            "clock_running": not ({"telegram", "clock"} & set(missing)), "last_backup": last,
            "errors": errors(logs)}


def main(argv: list[str]) -> int:
    if argv[:1] == ["--reconnect"]:  # (./vx restore, after a restore: the profile it restored is in the environment)
        lines = reconnect(dict(os.environ))
        print("\nTo use everything again on this Mac:\n" + "\n".join(f"  - {line}" for line in lines) if lines
              else "\nNothing to connect again on this Mac.")
        return 0
    ask = argparse.ArgumentParser()
    ask.add_argument("--profile", default="")
    ask.add_argument("--missing", default="")
    ask.add_argument("--ready-code", type=int, default=0)
    ask.add_argument("--ready-file", default="")
    ask.add_argument("--source", default="")
    for flag in ("stopped", "autostart", "local-models", "telegram"):
        ask.add_argument(f"--{flag}", action="store_true")
    args = ask.parse_args(argv)
    lines, wrong = report({**gather(args), "source": args.source})
    print(f"Viventium, checked {dt.datetime.now():%A %H:%M}\n")
    print("\n".join(lines))
    print("\nNothing is wrong." if not wrong else f"\n{len(wrong)} thing(s) need you (marked !!).")
    return 0 if not wrong else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
