"""The two calls the settings page makes: show() what she runs on, and apply() one change.

Every change saves by itself; there is nothing to confirm. What a change touches decides how it lands:

    a personality, a Feelings band, the call mode, your sentence for the Workers             at once, no restart
    her voice (talking), on its own                                                         at once, no restart
    start at login, the menu bar                                                            at once (vx)
    what a part runs on, Telegram on or off                                                 checked first
        (./vx ready: keys, sign-ins, memory), then she restarts when no call and no job is running

A profile (Local, Hybrid, Cloud) says where each part runs: on this Mac or online. The option itself is the
one you last chose for that place, never a default we fixed; your choices are remembered per place.
"""
import os
import re
import time
from dataclasses import asdict

from core import resources, telegram_approvals
from settings import catalog, files, install, runtime, store
from settings.catalog import PARTS

NATURES = [p["id"] for p in catalog.PERSONALITIES]
ON_MAC = next(o["id"] for o in PARTS["hands"]["options"] if o["where"] == "mac")  # the Worker on this Mac
PRIVATE = ("QUEEN_URL", "OPENAI_API_KEY_ITEM", "ANTHROPIC_API_KEY_ITEM", "XAI_API_KEY_ITEM", "ASSEMBLYAI_API_KEY_ITEM", "STT_MODEL")
HANDS_KEYS = ["WORKERS", "WORKERS_LOCAL", "WORKER_PROFILE", "WORKER_FALLBACK", "XPERFECT_STATE", "WORKER_MODEL_GROK_BUILD"] \
    + [f"WORKER_EFFORT_{name}" for name in catalog.HARNESS_ENV.values()]
MANAGER_KEYS = ["MANAGER_PROFILE", "MANAGER_EFFORT"]
KEYS = sorted({k for part in PARTS.values() for o in part["options"] for k in o.get("env", {})} | set(HANDS_KEYS) | set(PRIVATE)
              | set(MANAGER_KEYS)
              | {"QUEEN_EFFORT", "FEELINGS", "TELEGRAM", "TELEGRAM_TOKEN_ITEM", "KEYS_OFF", "QUEEN_FALLBACK", "MISSING_KEY",
                 "VX_LAN_ORIGIN", "VX_LAN_LIVEKIT_URL", "VX_LAN_NETWORK", "VX_PHONE", "MEMORY_MODEL", "SMALL_MAC_TIER",
                 "WORKERS_OPTIONAL", "STT_AUTO"})
PHONE_KEYS = ("VX_LAN_ORIGIN", "VX_LAN_LIVEKIT_URL", "VX_LAN_NETWORK", "VX_PHONE")  # (this Mac's lines for the phone)
# A subscription, as the Worker that runs on it (catalog.ACCOUNTS plan ids, PARTS hands option ids)
PLAN_WORKER = {"claude": "claude", "codex": "codex", "grok": "grok-build"}
# ...its harness (a route: this Mac's own sign-in), and its provider in xPerfect's Connections (your other accounts)
PLAN_HARNESS = {"claude": "claude-code", "codex": "codex-cli", "grok": "grok-build"}
PLAN_PROVIDER = {"claude": "claude", "codex": "codex", "grok": "grok"}


def connected() -> list[dict]:
    """The accounts you added (xPerfect's Connections), oldest first; none when it cannot be asked."""
    try:
        return sorted(runtime.xperfect("GET", "/v1/provider-accounts").get("items") or [], key=lambda a: str(a.get("created_at") or ""))
    except RuntimeError:
        return []


def turned_off() -> list[str]:
    """The ways her Workers run that you turned off (a route: "codex-cli", or "codex-cli@<account>")."""
    off = store.remembered().get("accounts_off") or []
    return [str(t) for t in off] if isinstance(off, list) else []


# -- Reading: which option a running setup is --

def read_choice(part: str, env: dict) -> dict:
    """The option these settings amount to, in the page's terms ({"id": "other"} when set by hand to something
    the page does not offer: shown as it is, never rewritten)."""
    if part == "hands":
        if env.get("WORKERS") == "local":
            return {"use": [ON_MAC], "effort": {}}
        by_harness = {o["harness"]: o for o in PARTS["hands"]["options"] if o["where"] != "mac"}
        named = [env.get("WORKER_PROFILE", "")] + [h for h in env.get("WORKER_FALLBACK", "").split(",") if h]
        use = [by_harness[h]["id"] for h in dict.fromkeys(named) if h in by_harness]
        effort = {by_harness[h]["id"]: env.get(f"WORKER_EFFORT_{catalog.HARNESS_ENV[h]}") or by_harness[h].get("effort", "")
                  for h in dict.fromkeys(named) if h in by_harness}
        if not use:
            return {"use": ["other"], "effort": {}}
        # The Worker on this Mac beside the online ones (WORKERS_LOCAL): preferred ("first"), or one of them ("also").
        beside = env.get("WORKERS_LOCAL", "")
        return {"use": [ON_MAC, *use] if beside == "first" else [*use, ON_MAC] if beside == "also" else use, "effort": effort}
    if part == "manager":  # unset, the one that manages is the first Worker's harness
        if env.get("WORKERS") == "local":
            return {"id": "qwen-local"}
        harness = env.get("MANAGER_PROFILE") or env.get("WORKER_PROFILE", "")
        option = next((o for o in PARTS["manager"]["options"] if o.get("harness") == harness and o["where"] != "mac"), None)
        if option is None:
            return {"id": "other"}
        level = env.get("MANAGER_EFFORT") or env.get(f"WORKER_EFFORT_{catalog.HARNESS_ENV[harness]}") or option.get("effort", "")
        return {"id": option["id"], "effort": level}
    match = {"listen": ("STT",), "talk": ("TTS",), "mind": ("QUEEN", "QUEEN_MODEL")}[part]
    for option in PARTS[part]["options"]:
        if all(env.get(key, "") == option["env"][key] for key in match):
            chosen = {"id": option["id"]}
            if option.get("efforts"):
                chosen["effort"] = env.get(PARTS[part]["effort"]) or option["effort"]
            return chosen
    return {"id": "other"}


def choices(env: dict) -> dict:
    return {part: read_choice(part, env) for part in PARTS}


def first(part: str, choice: dict) -> str:
    return choice["use"][0] if part == "hands" else choice["id"]


def place(part: str, choice: dict) -> str:
    """Where a choice runs: "mac" or "cloud" ("" for one set by hand); "both" for Workers on this Mac beside
    online ones, which no profile says (the page shows that as your own mix)."""
    ids = choice["use"] if part == "hands" else [choice["id"]]
    kinds = {catalog.kind(option["where"]) if (option := catalog.option(part, i)) else "" for i in ids}
    return kinds.pop() if len(kinds) == 1 else "" if "" in kinds else "both"


# -- Writing: the exact lines a choice needs --

def lines(part: str, choice: dict) -> dict:
    if part == "hands":
        chosen = [catalog.option("hands", option_id) for option_id in choice["use"]]
        options = [o for o in chosen if o["where"] != "mac"]  # the online ones, in your order
        if not options:  # every Worker on this Mac
            return {"WORKERS": "local", "WORKERS_LOCAL": "", "WORKER_PROFILE": chosen[0]["harness"], "WORKER_FALLBACK": "",
                    "XPERFECT_STATE": "brain/state-local"}
        # Online Workers, and with them the one on this Mac if you ticked it too: preferred ("first") or not ("also").
        # It runs on its own xPerfect beside the online one (brain/xperfect.py), so it is never a backup of theirs.
        out = {"WORKERS": "signed-in", "WORKER_PROFILE": options[0]["harness"], "XPERFECT_STATE": "brain/state-cloud",
               "WORKER_FALLBACK": ",".join(o["harness"] for o in options[1:]),
               "WORKERS_LOCAL": "" if len(options) == len(chosen) else "first" if chosen[0]["where"] == "mac" else "also"}
        for option in options:
            level = choice.get("effort", {}).get(option["id"]) or option.get("effort", "")
            out[f"WORKER_EFFORT_{catalog.HARNESS_ENV[option['harness']]}"] = level if level != option.get("effort") else ""
        return out
    option = catalog.option(part, choice["id"])
    if part == "manager":
        if option["where"] == "mac":
            return {"MANAGER_PROFILE": "", "MANAGER_EFFORT": ""}
        return {"MANAGER_PROFILE": option["harness"], "MANAGER_EFFORT": choice.get("effort") or option.get("effort", "")}
    out = dict(option["env"])
    if option.get("efforts"):
        out[PARTS[part]["effort"]] = choice.get("effort") or option["effort"]
    return out


def private_keys(part: str, option: dict | None) -> tuple:
    """The private lines an online option may need: the Keychain item its key lives in, and for her mind your own
    endpoint (for listening, its model). None for what runs on this Mac."""
    if not option or option.get("where") == "mac" or part not in ("listen", "talk", "mind"):
        return ()
    need = str(option.get("needs", ""))
    return tuple(([f"{need}_ITEM"] if need.endswith("_API_KEY") else [])
                 + (["QUEEN_URL"] if part == "mind" else ["STT_MODEL"] if part == "listen" else []))


def private_lines(part: str, choice: dict, profile: str, plains: dict, running: dict, tracked: dict, saved: dict) -> tuple:
    """An online option's private lines (your own endpoint, the Keychain item your key lives in), each on its own, a
    line set empty as much as one with a value: (the ones in force by your own hand, the ones the page keeps for you).
    A line is yours as written when this profile's own files set it and choose this option. Else, while this profile
    runs this option and its block keeps any of its lines, those are its lines (an update that makes that option the
    shipped default never drops them; one kept empty stays empty). Else it comes from the first that has it: what this
    profile had for this option when it was last chosen here (kept in her settings when you chose another), your own
    lines in another profile where the same option runs. Only the lines of that option:
    choosing a voice never brings a mind's endpoint, and another mind never inherits one written for GPT-6.1 Sol.
    plains: each profile without the page's blocks; running: as vx loads it; tracked: its tracked file alone."""
    option_id = choice.get("id", "")
    keys = private_keys(part, catalog.option(part, option_id))
    if not keys:
        return {}, {}

    def chooses(values: dict) -> bool:
        return choices(values)[part].get("id") == option_id

    def his(values: dict, other: str) -> dict:  # (set in his own files: unlike what the tracked profile says)
        return {k: values[k] for k in keys if values.get(k, "") != tracked[other].get(k, "")}
    # (his own lines here: any he wrote, one set empty too: empty is his choice, never a gap to fill from elsewhere)
    hand = {k: plains[profile].get(k, "") for k in store.assigned(profile, list(keys))} if chooses(plains[profile]) else {}
    block = store.block(profile) if chooses(running[profile]) else {}
    kept = {k: block[k] for k in keys if k in block}  # (any of them kept here for this option: these are its lines)
    places = [kept] if kept else [saved.get("private", {}).get(profile, {}).get(part, {}).get(option_id, {}),
                                  *[his(values, other) for other, values in running.items() if other != profile and chooses(values)]]
    found = {}
    for k in keys:
        if k in hand:
            continue
        if place := next((p for p in places if k in p), None):
            found[k] = str(place[k])
    return hand, found


def leaving(target: str, chosen: dict, running: dict) -> dict:
    """The private lines the page keeps in this profile's block for an option you are leaving now, by part and option:
    kept in her settings, they come back when you choose it here again (private_lines)."""
    block, out = store.block(target), {}
    for part in ("listen", "talk", "mind"):
        was = choices(running[target])[part].get("id", "")
        if was and was != chosen[part].get("id"):
            if mine := {k: block[k] for k in private_keys(part, catalog.option(part, was)) if k in block}:
                out.setdefault(part, {})[was] = mine
    return out


# -- What an option still needs before it can run here --

def needs(part: str, option: dict, env: dict) -> str:
    """"" (ready), "key:NAME", "signin:NAME" or "model" (not downloaded)."""
    need = option.get("needs", "")
    if need.endswith("_API_KEY"):
        return "" if runtime.has_key(need, env) else f"key:{need}"
    if need in catalog.OWN_SIGN_INS:  # (Light's own sign-in, in its Keychain item; turned off as a key is, and off wins)
        return "" if runtime.own_signed_in(need) and need not in env.get("KEYS_OFF", "").split() and not runtime.own_is_off(need) else f"signin:{need}"
    if need:
        return "" if runtime.signed_in(need) else f"signin:{need}"
    if option.get("local_model") and option["local_model"] not in runtime.local_models():
        return "model"
    if option.get("local_media") and not runtime.media_weights(option["local_media"]):
        return "model"
    return ""


def describe(part: str, option: dict, env: dict) -> dict:
    out = {k: option[k] for k in ("id", "provider", "model", "title", "detail", "mark", "where", "words", "speed", "smart",
                                  "timed", "efforts", "effort", "sample", "backup", "pick") if k in option}
    out["tried"] = option.get("tried", True)
    if part == "mind":  # (it decides itself when work goes to a Worker, or a quick check beside it does: brain/queen)
        out["decides"] = bool(option.get("decides"))
    out["needs"] = needs(part, option, env)
    if out["needs"] == "model":  # not on this Mac yet: one click gets it (settings/install.py)
        out["install"] = install.status(option.get("local_media") or option["local_model"])
    if need := option.get("needs", ""):
        out["needs_name"] = sign_in_name(need)
        out["account"] = next((a["id"] for a in catalog.ACCOUNTS if need in (a.get("plan"), a.get("mind"), a.get("key"))), "")
    if option.get("backup"):
        out["backup_name"] = next(o for o in PARTS[part]["options"] if o["id"] == option["backup"])["provider"]
        if part == "talk" and option["id"] in ("eve", "eve-plan") and env.get("SMALL_MAC_TIER") in ("8", "16"):
            out.update(backup="mac-speech", backup_name="Apple")
    return out


def sign_in_name(need: str) -> str:
    """A key's or a sign-in's name, as the page says it."""
    return catalog.KEY_NAMES.get(need) or (catalog.OWN_SIGN_INS.get(need) or catalog.SIGN_INS.get(need) or {}).get("name", need)


# -- Her own Feelings (brain/feelings.py owns them; this only asks) --

def feeling(env: dict):
    os.environ["FEELINGS"] = env.get("FEELINGS") or "off"
    from brain import feelings
    return feelings


BOUNDS = [20, 40, 60, 80]  # where levels 1 to 4 begin, as the engine has always had them (0-19 ... 80-100)
LEAST = 5  # points each level keeps, so every level can still be reached


def character(env: dict) -> dict:
    """Personality and Feelings as the page draws them: each band's level now, where it rests, how fast it comes
    back, its recent path (the trail), where each of its five levels begins, and what each says (main Viventium's words,
    or yours in their place, and your own words added). `tune`: the engine keeps thresholds and level words of yours
    (its state carries levelBounds and levelWords: brain/feelings); without it they are as shipped."""
    from brain import feelings_kernel as kernel
    state = feeling(env).state()
    nature = state.get("nature") or (env.get("FEELINGS") if env.get("FEELINGS") in NATURES else "warm")
    trail, yours = state.get("trail") or [], state.get("additions") or {}
    says = kernel.policy()["levels"] if state.get("bands") else {}
    words = {band.id: band.words for band in kernel.BANDS}
    bounds, worded = state.get("levelBounds") or {}, state.get("levelWords") or {}
    bands = [{"id": band_id, "name": b["name"], "low": b["low"], "high": b["high"], "color": b["color"], "word": b["word"],
              "now": round(b["current"]), "rest": round(b["nature"]), "on": bool(b["enabled"]), "pace": round(b["halfLifeMinutes"]),
              "trail": [{"t": e["timestamp"], "from": round(e["before"]), "to": round(e["after"])} for e in trail if e["band"] == band_id][-16:],
              "bounds": [round(x) for x in bounds.get(band_id) or BOUNDS],
              "levels": [{"word": words[band_id][n], "text": (worded.get(band_id) or {}).get(level_id) or says[band_id][level_id],
                          "original": says[band_id][level_id], "yours": yours.get(band_id, {}).get(level_id, "")}
                         for n, level_id in enumerate(kernel.LEVEL_IDS)]}
             for band_id, b in (state.get("bands") or {}).items()]
    inner = state.get("innerState") or {}
    return {"on": bool(state.get("enabled")), "nature": nature, "manner": state.get("manner") or "", "bands": bands, "as_of": state.get("asOf", ""),
            "natures": [{**p, "rests": [kernel.PROFILES[p["id"]][band_id] for band_id in kernel.BAND_IDS]} for p in catalog.PERSONALITIES],
            "inner": {"text": inner.get("text", ""), "at": inner.get("generatedAt", "")} if inner.get("text") else None,
            "module": (env.get("FEELINGS") or "off") != "off", "tune": "levelBounds" in state and "levelWords" in state}


def bounds_why(at) -> str:
    """"" when these four thresholds can be kept (whole numbers, rising, each level keeping LEAST points), else why not."""
    try:
        at = [int(x) for x in at]
    except (TypeError, ValueError):
        return "Those are not thresholds."
    if len(at) != 4 or any(b - a < LEAST for a, b in zip([0, *at], [*at, 101])):
        return f"Each level keeps at least {LEAST} points."
    return ""


def keep_media(kind: str, option: dict) -> None:
    """Remember which tool makes photos or videos, as the Workers need to hear it (read per job, no restart)."""
    def keep(s: dict) -> None:
        s.setdefault("media", {})[kind] = option["id"]
        if option.get("local_media"):  # a model on this Mac: any Worker runs tools/media/make. A tool online leaves the
            s.setdefault("media_local", {})[kind] = option["local_media"]  # choice for this Mac as it was (kept apart)
        if kind == "photos":  # (the Worker whose own tool makes pictures; "" when every Worker can)
            s["photos_by"] = option.get("harness", "")
    store.remember(keep)


def media(env: dict, saved: dict) -> dict:
    """Photos and videos: what can make them here, and the one chosen for each (the first that can run, until
    you choose)."""
    parts, chosen = {}, {}
    for kind, spec in catalog.MEDIA.items():
        options = [describe(kind, option, env) for option in spec["options"]]
        ready = [o["id"] for o in options if not o["needs"]]
        kept = (saved.get("media") or {}).get(kind, "")
        chosen[kind] = kept if kept in ready else (ready[0] if ready else "")
        parts[kind] = {"name": spec["name"], "hint": spec["hint"], "options": options}
    return {"parts": parts, "choices": chosen}


def accounts(env: dict) -> list[dict]:
    """Each provider once: its subscription on this Mac (signed in, used by her Workers or turned off), the other
    accounts you added for it (xPerfect's Connections: each its own sign-in), its key (in the Keychain and used,
    never the key itself), and how each was last found (core/accounts: limited, a log-in needed, not answering).
    Turning one off only stops Light using it: this Mac's sign-in and the Keychain item stay, since main
    Viventium and other tools share them. An account you added is xPerfect's own, and removing it removes only
    that."""
    from core import accounts as found
    states, off, added = found.states(), set(turned_off()), connected()
    setup = {row["id"]: row for row in catalog.setup_accounts()}
    out = []
    for account in catalog.ACCOUNTS:
        name = account["key"]
        row = {"id": account["id"], "name": account["name"], "product": account["product"], "mark": account["mark"],
               "key": {"name": name, "on": runtime.key_kept(name, env), "use": name not in env.get("KEYS_OFF", "").split()
                       and not (name == "OPENAI_API_KEY" and runtime.own_is_off(name)),
                       "state": states.get(f"key:{name}", {}).get("state", "")}}
        if spec := setup.get(account["id"]):
            row.update(connect=spec["connect"], background=spec["background"])
        if plan := account.get("plan"):
            harness = PLAN_HARNESS.get(plan, "")
            row["plan"] = {"id": plan, "name": catalog.SIGN_INS[plan]["name"], "on": runtime.signed_in(plan),
                           "installed": runtime.installed(plan), "use": harness not in off,
                           "state": states.get(f"plan:{plan}", {}).get("state", ""),
                           "accounts": same(plan, [other(a, harness, off, states) for a in added
                                                   if a.get("provider") == PLAN_PROVIDER.get(plan)])}
            if not row["plan"]["installed"]:  # its own tool is not on this Mac yet: one click gets it
                row["plan"]["install"] = install.status(plan)
        if mind := account.get("mind"):  # (her mind on your subscription: Light's own sign-in, apart from the Workers')
            row["mind"] = {"id": mind, "use": mind not in env.get("KEYS_OFF", "").split() and not runtime.own_is_off(mind),
                           "state": states.get(found.route(mind), {}).get("state", ""), **runtime.own_sign_in(mind)}
        out.append(row)
    return out


def setup_accounts(env: dict) -> list[dict]:
    """Status for the native rows, without installing, starting or refreshing a provider."""
    result = []
    for row in catalog.setup_accounts():
        connect = row["connect"]
        own = connect in catalog.OWN_SIGN_INS
        status = runtime.own_sign_in(connect) if own else {}
        chatgpt_roles = {"limited": "Plan limit reached", "unavailable": "Not responding", "sign_in": "Log in again",
                         "refresh_unavailable": "Sign-in could not refresh", "unauthorized": "Sign-in rejected",
                         "scope_missing": "Plan access missing", "revoked": "Disconnected"}.get(status.get("state"))
        result.append({
            **row, "installed": own or runtime.installed(connect),
            "signedIn": runtime.own_signed_in(connect) if own else runtime.signed_in(connect),
            "keySaved": bool(row["key"]) and runtime.has_key(row["key"], env),
            "signingIn": bool(status.get("setup") or status.get("pending")), "outcome": status.get("last") or "",
            **({"roles": chatgpt_roles or "Conversation mind",
                "privacy": status["privacy"]} if connect == "chatgpt_mind" else {}),
        })
    return result


def setup_mind(env: dict) -> bool:
    """Select the first available online mind once during setup, using the regular profile choices."""
    profile = env["PROFILE"]
    fields = ["QUEEN", "QUEEN_MODEL", "QUEEN_URL", "QUEEN_EFFORT"]
    block = store.block(profile)
    if set(fields).intersection(block) or store.assigned(profile, fields):
        return env.get("QUEEN") not in ("", "ollama")
    for option in PARTS["mind"]["options"]:
        if option["where"] == "mac" or needs("mind", option, env):
            continue
        # Prefer the subscription over the same provider's key when both are present.
        if option["where"] == "key" and any(
            plan["where"] == "plan" and plan["mark"] == option["mark"] and not needs("mind", plan, env)
            for plan in PARTS["mind"]["options"]
        ):
            continue
        if profile == "hybrid":
            block.setdefault("WORKERS_OPTIONAL", "1")
        picked = lines("mind", {"id": option["id"]})
        if env.get("SMALL_MAC_TIER") and picked.get("QUEEN") == "chatgpt_plan":
            picked["QUEEN_FALLBACK"] = "openai" if runtime.has_key("OPENAI_API_KEY", env) else ""
        store.save_block(store.files(profile)[2], {**block, **picked})
        return True
    return False


def same(plan: str, mine: list[dict]) -> list[dict]:
    """Each account you added that is signed in as the same account as this Mac's own sign-in, or as one you added
    before it, says so ("same": whose): it is no backup, since one limit stops both. Sign in with another account
    for one. Asked only when one is signed in."""
    if not any(row["status"] == "ready" for row in mine):
        return mine
    seen = {who: "yours"} if (who := runtime.signed_in_as(plan)) else {}
    for row in mine:
        if row["status"] == "ready" and (who := runtime.signed_in_as(plan, row["id"])):
            if who in seen:
                row["same"] = seen[who]
            else:
                seen[who] = row["label"]
    return mine


def other(added: dict, harness: str, off: set, states: dict) -> dict:
    """An account you added, as the page shows it: while its sign-in runs, where to finish it; when that sign-in
    ended without finishing (closed, or xPerfect restarted under it), or its provider later signed it out, a way to
    sign in again. Never shown as signed in unless xPerfect says ready."""
    account_id = str(added.get("account_id") or "")
    row = {"id": account_id, "label": str(added.get("label") or "Another account"), "status": str(added.get("status") or ""),
           "use": f"{harness}@{account_id}" not in off, "state": states.get(f"account:{account_id}", {}).get("state", "")}
    if row["status"] == "connecting":  # (asked only then: with no sign-in running, its answer is a check of that home)
        try:
            setup = runtime.xperfect("GET", f"/v1/provider-accounts/{account_id}/setup")
        except RuntimeError:
            setup = {}
        if setup.get("status") == "connecting":
            row["setup"] = {"url": str(setup.get("setup_url") or ""), "code": str(setup.get("setup_code") or ""),
                            "input": bool(setup.get("input_required"))}
        elif setup.get("status"):  # (it ended, signed in or not: "complete" says only that it ended)
            row["status"] = str(setup["status"])
    if row["status"] not in ("ready", "connecting"):
        row["setup"] = {"url": "", "code": "", "input": False, "again": True}
    return row


def backup(env: dict, now: dict) -> str:
    """The mind's declared backup, as the page names it ("" for none): this Mac's model, for an online mind."""
    if place("mind", now["mind"]) != "cloud":
        return ""
    if env.get("QUEEN") == "chatgpt_plan" and env.get("SMALL_MAC_TIER") and not (
            env.get("QUEEN_FALLBACK") == "openai" and runtime.has_key("OPENAI_API_KEY", env)):
        return "No backup available"
    if env.get("QUEEN_FALLBACK") == "openai":
        if now["mind"].get("id") == "openai-sol":
            return ""
        return "OpenAI" if runtime.has_key("OPENAI_API_KEY", env) else "OpenAI (key needed)"
    if env.get("QUEEN_FALLBACK") != "local":
        return ""
    if env.get("SMALL_MAC_TIER") and (model := install.MODELS.get(env.get("MEMORY_MODEL"))):
        return f"{model['name']} on this Mac"
    local = next((o for o in PARTS["mind"]["options"] if o["where"] == "mac"), None)
    return f"{local['model']} on this Mac" if local and local.get("model") else "This Mac's model"


def backup_now(env: dict, now: dict) -> str:
    """Whether the backup is answering for her online mind right now, and why: "key" when this Mac has no key for it to
    use (missing, or turned off: it is not built at all, and on Hybrid it runs as Local runs it, vx stand_in), else how
    its key was last found (core/accounts: "limited", "sign_in", "down"; LiveKit set it aside and brain/queen recorded
    it), "" while the mind itself answers."""
    if env.get("SMALL_MAC_TIER"):
        return ""  # the page shows the recorded reply
    option = catalog.option("mind", now["mind"].get("id", ""))
    need = str((option or {}).get("needs", ""))
    if not backup(env, now) or not option or not (need.endswith("_API_KEY") or need in catalog.OWN_SIGN_INS):
        return ""
    if env.get("QUEEN_FALLBACK") == "openai" and not runtime.has_key("OPENAI_API_KEY", env):
        return ""
    if needs("mind", option, env):  # (no key, or no sign-in of Light's, to use: its backup answers alone)
        return "key" if need.endswith("_API_KEY") else "sign_in"
    from core import accounts
    return str(accounts.states().get(accounts.route(option["needs"]), {}).get("state", ""))


def backup_attempt(env: dict, now: dict) -> dict:
    """Which choice backup_now is about, and when its account was last found so: the page says it only for that choice,
    in its own words (before: right after a subscription was chosen, the line still carried the key's 'refused'
    and worded it as the subscription's, though nothing had asked the subscription yet)."""
    if not backup_now(env, now):
        return {"backup_of": ""}
    option = catalog.option("mind", now["mind"].get("id", "")) or {}
    from core import accounts
    seen = accounts.states().get(accounts.route(str(option.get("needs", ""))), {}).get("seen")
    return {"backup_of": option.get("id", ""), **({"backup_seen": seen} if isinstance(seen, (int, float)) else {})}


def paused(env: dict, now: dict) -> bool:
    """Whether her replies pause: her mind runs on a sign-in of Light's own (your Grok subscription) that is turned off or
    missing, with no backup declared to answer meanwhile. Your choice holds; the page says so, plainly."""
    option = catalog.option("mind", now["mind"].get("id", "")) or {}
    ready = bool(backup(env, now))
    if env.get("QUEEN_FALLBACK") == "openai":
        ready = ready and runtime.has_key("OPENAI_API_KEY", env)
    return option.get("needs") in catalog.OWN_SIGN_INS and bool(needs("mind", option, env)) and not ready


def account(want: dict, env: dict, chosen: dict) -> str | dict:
    """One account turned off or on. A key: not loaded into anything (KEYS_OFF, this Mac's line). A subscription
    on this Mac, or an account you added: her Workers stop running on it (accounts_off, read by each job), and
    the next account of that provider, or the next Worker you chose, does the work; the manager moves when its
    own sign-in is turned off. Returns why not, or what to apply."""
    entry = next((a for a in catalog.ACCOUNTS if a["id"] == want.get("id")), None)
    if entry is None or want.get("line") not in ("plan", "key", "account", "mind") or (want["line"] == "mind" and not entry.get("mind")):
        return "That account does not exist."
    use = bool(want.get("use"))
    if want["line"] in ("key", "mind"):  # (her mind's own sign-in is turned off as a key is: nothing signed out)
        name = entry["key"] if want["line"] == "key" else entry["mind"]
        off = [k for k in env.get("KEYS_OFF", "").split() if k != name] + ([] if use else [name])
        return {"keys_off": " ".join(off)}
    harness = PLAN_HARNESS.get(entry.get("plan", ""))
    if harness is None:
        return "That account has no subscription."
    added = [a for a in connected() if a.get("provider") == PLAN_PROVIDER[entry["plan"]] and str(a.get("status")) == "ready"]
    if want["line"] == "account" and not any(str(a.get("account_id")) == str(want.get("account")) for a in connected()):
        return "That account does not exist."
    token = harness if want["line"] == "plan" else f"{harness}@{want['account']}"
    off = [t for t in turned_off() if t != token] + ([] if use else [token])
    # Her Workers keep at least one way to run: a Worker you chose, on this Mac's sign-in or an account left on.
    ways = []
    for worker in chosen["hands"]["use"]:
        option = catalog.option("hands", worker)
        if option is None or option["where"] == "mac":
            ways.append(worker)
            continue
        mine = [a for a in connected() if a.get("provider") == PLAN_PROVIDER.get(next(
            (plan for plan, h in PLAN_HARNESS.items() if h == option["harness"]), ""), "") and str(a.get("status")) == "ready"]
        ways += [t for t in [option["harness"], *(f"{option['harness']}@{a['account_id']}" for a in mine)] if t not in off]
    if not ways:
        return "Keep at least one way for your Workers to run."
    out = {"accounts_off": off}
    manager = catalog.option("manager", chosen["manager"]["id"])
    if want["line"] == "plan" and not use and manager and manager.get("harness") == harness:
        left = [w for w in chosen["hands"]["use"] if (o := catalog.option("hands", w)) and o["where"] != "mac" and o["harness"] not in off]
        if left:  # (the manager ran on this Mac's sign-in of it: the first Worker whose own sign-in is on manages)
            out["manager"] = {"id": left[0]}
    del added
    return out


def add_account(want: dict) -> str:
    """Another account of a provider for her Workers: xPerfect makes its own home for it and starts that
    provider's own sign-in (it opens in your browser, or gives a code). Returns why not, or ""."""
    entry = next((a for a in catalog.ACCOUNTS if a["id"] == want.get("id")), None)
    if entry is None or entry.get("plan") not in PLAN_PROVIDER:
        return "That provider has no subscription to add."
    provider = PLAN_PROVIDER[entry["plan"]]
    with runtime.locked("add-account"):  # (one add at a time: a second click while one is made waits, then sees it)
        accounts = [a for a in connected() if a.get("provider") == provider]
        if any(a.get("status") == "connecting" for a in accounts):  # (one of them is still signing in: finish that first)
            return (f"Another {entry['product']} account is still signing in. Finish it in your browser, or it ends by "
                    "itself in a few minutes.")
        try:
            made = runtime.xperfect("POST", "/v1/provider-accounts", {"provider": provider, "label": f"{entry['product']} {len(accounts) + 2}",
                                                                      "auth_method": "subscription", "platform_support": "supported"})
            runtime.xperfect("POST", f"/v1/provider-accounts/{made['account_id']}/setup")
        except (RuntimeError, KeyError) as e:  # (xPerfect's own words go to her settings log, never to the page)
            runtime.logged(f"adding a {provider} account", f"{type(e).__name__}: {e}")
            return f"Another {entry['product']} account could not be added. Try again in a moment."
    runtime.bound_sign_in(str(made["account_id"]))
    return ""


def sign_in_again(want: dict) -> str:
    """An account you added whose sign-in ended without finishing, or that its provider signed out: its own sign-in
    again, in its own home (it opens in your browser, or gives a code). Returns why not, or ""."""
    account_id = str(want.get("account") or "")
    if not any(str(a.get("account_id")) == account_id for a in connected()):
        return "That account does not exist."
    try:
        runtime.xperfect("POST", f"/v1/provider-accounts/{account_id}/setup")
    except RuntimeError as e:
        runtime.logged("signing an added account in again", f"{type(e).__name__}: {e}")
        return "Its sign-in could not start, so nothing changed. Try again in a moment."
    runtime.bound_sign_in(account_id)
    return ""


def remove_account(want: dict) -> str:
    """An account you added, removed from xPerfect (its own home and sign-in only; nothing of this Mac's)."""
    account_id = str(want.get("account") or "")
    if not any(str(a.get("account_id")) == account_id for a in connected()):
        return "That account does not exist."
    try:  # (xPerfect forgets an account only once it is disconnected: its sign-in in that home is ended first)
        try:
            runtime.xperfect("POST", f"/v1/provider-accounts/{account_id}/setup/cancel")
        except RuntimeError:
            pass  # (no sign-in running)
        try:
            runtime.xperfect("POST", f"/v1/provider-accounts/{account_id}/disconnect")
        except RuntimeError:
            pass  # (already disconnected)
        runtime.xperfect("DELETE", f"/v1/provider-accounts/{account_id}")
    except RuntimeError as e:
        runtime.logged("removing an added account", f"{type(e).__name__}: {e}")
        return "That account could not be removed, so it is still there. Try again in a moment."
    store.remember(lambda s: s.__setitem__("accounts_off", [t for t in turned_off() if not t.endswith(f"@{account_id}")]))
    return ""


# -- Calling from your phone on the same Wi-Fi (call/phone.py; who may: call/ui/app/api/token) --

def phone(env: dict) -> dict:
    """Whether calling from the phone is on (this Mac's VX_LAN_ORIGIN, unless VX_PHONE=off says otherwise), where the
    phone opens it, whether this Mac is on a network a phone could reach it on now, and on the one it was turned on in,
    and the fingerprint of the certificate the phone trusts (to check on the phone, once)."""
    where = runtime.phone_address()
    on = bool(env.get("VX_LAN_ORIGIN")) and env.get("VX_PHONE") != "off"
    moved = on and env.get("VX_LAN_ORIGIN") != where["page"]  # (this Mac was renamed since: turn it on again)
    return {"on": on, "page": (env.get("VX_LAN_ORIGIN") if on else where["page"]) + "/pair", "network": bool(where["ip"]),
            "moved": moved, "elsewhere": on and bool(where["ip"]) and where.get("network", "") != env.get("VX_LAN_NETWORK", ""),
            "fingerprint": runtime.phone_fingerprint() if on else "",
            "renewed": on and runtime.phone_renewed(),  # (a paired phone trusts the old root: it needs the new one)
            "still": not on and runtime.doors_answer()}  # (off, yet something answers where its doors were: said plainly)


def phone_lines(mine: dict, on: dict | None, plain: dict) -> dict:
    """This Mac's own lines for calling from the phone: on, its address, doors and network; off, none of the page's, and
    VX_PHONE=off when a line of your own would still turn it on (vx then sets the phone's lines empty, whatever any
    file says)."""
    for key in PHONE_KEYS:
        mine.pop(key, None)
    if on:
        mine.update(on)
    elif plain.get("VX_LAN_ORIGIN") or plain.get("VX_LAN_LIVEKIT_URL"):
        mine["VX_PHONE"] = "off"
    return mine


def phone_off(always: bool = False) -> bool:
    """Calling from the phone off in this Mac's own lines, its doors closed, at once and with no restart (Off on the page,
    whatever comes after it; or ./vx restore, whose phone was paired on another Mac or before and whose pairing never
    travels). True when it was on."""
    was = phone(store.values(runtime.profile_now(), KEYS))["on"]
    if not was and not always:
        return False
    machine = store.files("local")[1]
    head = store.split(store.read(machine))[0]
    plain = {p["id"]: store.values(p["id"], KEYS, blocks=False) for p in profiles(runtime.profile_now())}
    hand = {k: v for values in plain.values() for k, v in values.items() if k in PHONE_KEYS and v}
    runtime.doors_off()  # (first: nothing after this can leave a door open)
    store.write(machine, store.join(head, phone_lines(dict(store.machine_block()), None, hand)))
    return was


# -- show --

def profiles(active: str) -> list[dict]:
    small = [p for p in catalog.SMALL_PROFILES if p["id"] == active and store.files(active)[0].exists()]
    return [{**p, "resources": asdict(resources.requirements(p["id"]))}
            for p in (small or [p for p in catalog.PROFILES if store.files(p["id"])[0].exists()])]


def available_option(part: str, option: dict, env: dict) -> bool:
    if part == "mind" and option.get("needs") == "chatgpt_mind" and not runtime.OFFLINE:
        return option["env"]["QUEEN_MODEL"] in (runtime.chatgpt_status().get("models") or [])
    if not env.get("SMALL_MAC_TIER"):
        return True
    if option.get("local_model"):
        return False
    if env["SMALL_MAC_TIER"] == "8" and option["id"] == "whisper":
        return False
    if env["SMALL_MAC_TIER"] != "24" and option["id"] == "chatterbox":
        return False
    return True


def voice_available(env: dict) -> bool:
    return env.get("STT") != "off" or (
        env.get("STT_AUTO") == "1" and any(runtime.has_key(key, env) for key in ("XAI_API_KEY", "OPENAI_API_KEY"))
    )


def show() -> dict:
    from core import accounts as found

    applying = runtime.applying()
    profile = applying.get("profile") or runtime.profile_now()  # (a saved change she has not restarted into yet)
    env = store.values(profile, KEYS)
    places = profiles(profile)
    plains = {p["id"]: store.values(p["id"], KEYS, blocks=False) for p in places}
    defaults = {p: choices(plain) for p, plain in plains.items()}
    now = choices(env)
    saved = store.remembered()
    telegram = runtime.telegram(env)
    return {
        "profile": profile,
        "profiles": places,
        "mix": any(place(part, now[part]) != place(part, defaults[profile][part]) for part in PARTS),
        "choices": now,
        "parts": {part: {"name": spec["name"], "region": spec["region"], "many": spec.get("many", False),
                         "absent": spec.get("absent", {}),
                         # (Workers on this Mac beside online ones: the manager you choose manages the online work)
                         "hint": catalog.MANAGER_BESIDE if part == "manager" and place("hands", now["hands"]) == "both" else spec["hint"],
                         "options": [describe(part, o, env) for o in spec["options"] if available_option(part, o, env)]}
                  for part, spec in PARTS.items()},
        "voice_available": voice_available(env),
        **({"voice_need": "Voice needs a Grok or ChatGPT API key."} if env.get("STT_AUTO") == "1" and not voice_available(env) else {}),
        "ask": catalog.ASK, "accounts": accounts(env), "media": media(env, saved), "backup": backup(env, now),
        "backup_now": backup_now(env, now), **backup_attempt(env, now), "paused": paused(env, now),
        **({"last_mind": found.last_mind(profile)} if env.get("SMALL_MAC_TIER") else {}),
        "where": catalog.WHERE, "speed": catalog.SPEED, "smart": catalog.SMART, "effort_names": catalog.EFFORT,
        "workers_note": saved.get("workers_note", ""),
        "call_mode": saved.get("call_mode", "talk"), "call_modes": catalog.CALL_MODES,
        "presence": presence(saved),
        # (the voice switch: a voice message gets a voice reply unless it is off; read by chat/telegram.py
        # at each voice note, so a change needs no restart)
        "channels": {"telegram": {**telegram, "voice": saved.get("telegram_voice", True) is not False,
                                  "approvals": telegram_approvals.ready(telegram["id"]) if telegram["id"] else False,
                                  "paired": telegram_approvals.paired(telegram["id"]) if telegram["id"] else False},
                     "web": runtime.web(), "phone": phone(env)},
        "character": character(env),
        "system": runtime.system(),
        "files": files.listed(),
        "applying": applying,
        "installing": install.running(),
    }


def set_presence(shown) -> str:
    """The dots, or Soulface: asking for Soulface adds it first when it is not here (one click). Returns why not, or ""."""
    if shown not in ("dots", "soulface"):
        return "That choice does not exist."
    if shown == "soulface" and not install.installed("soulface"):
        if why := install.start("soulface"):
            return why
    store.remember(lambda s: s.__setitem__("presence", shown))
    return ""


def set_call_mode(mode, at=None) -> str:
    """Talk, Wing or Listen only: the next call's, and the open conversation's at once (core/live.py). at: when it was
    chosen, from a page that saves its choice after the fact; one older than the last choice written is not kept (a page's
    save can arrive after a later choice from the menu bar's panel, and must not undo it). Unsaid, or later than now: now."""
    if mode not in [m["id"] for m in catalog.CALL_MODES]:
        return "That call mode does not exist."
    now = time.time()
    when = min(float(at), now) if isinstance(at, (int, float)) and not isinstance(at, bool) and at == at else now

    def keep(saved: dict) -> None:  # (with when it was chosen: chosen again while a call had switched itself, every open
        if float(saved.get("call_mode_at") or 0) <= when:  # call still follows; an older choice changes nothing)
            saved.update(call_mode=mode, call_mode_at=round(when, 3))
    store.remember(keep)
    return ""


def presence(saved: dict) -> dict:
    """How she shows above the conversation: the dots (built in), or Soulface, an add-on that is on this Mac only once
    asked for (settings/install.py ADDONS). "soulface" is what the page loads; "chosen" is what was asked for, kept
    while it is still being added."""
    chosen = saved.get("presence", "dots")
    here = install.installed("soulface")
    return {"chosen": chosen, "shown": "soulface" if chosen == "soulface" and here else "dots",
            "soulface": {"here": here, "install": None if here else install.status("soulface"),
                         "entry": install.addon_manifest("soulface").get("entry") if here else None}}


# -- The menu bar's panel (tools/menubar/main.swift, through ./vx settings menu) --

def stands_in(env: dict) -> bool:
    """Whether this profile lets an online part whose key is missing start on its declared backup (MISSING_KEY=backup:
    Hybrid; vx stand_in does the same when she starts)."""
    return env.get("MISSING_KEY") == "backup"


def stood_in(key: str, now: dict, env: dict) -> bool:
    """Whether a part of her chosen setup needs this key and its backup answers for it while it is missing."""
    if key == "grok_mind" and env.get("QUEEN") == "xai_plan" and env.get("QUEEN_FALLBACK") == "openai":
        return True
    if not stands_in(env):
        return False
    for part in ("talk", "mind"):
        option = catalog.option(part, now["choices"][part].get("id", "")) or {}
        if option.get("needs") == key and (option.get("backup") or (part == "mind" and env.get("QUEEN_FALLBACK") == "local")):
            return True
    return False


def picks(target: str, env: dict, saved: dict, defaults: dict) -> dict:
    """The options a profile chosen by name runs on: for each part, the one last chosen for its place when it can run
    here, else the profile's own (as apply() chooses them)."""
    chosen = {}
    for part in PARTS:
        where = place(part, defaults[target][part])
        last = saved.get("last", {}).get(part, {}).get(where)
        chosen[part] = last if last and not check(part, last, env) else defaults[target][part]
    return chosen


def reach(target: str, saved: dict, defaults: dict) -> dict:
    """What a place (Local, Hybrid, Cloud) still needs on this Mac before it can start, as ./vx ready decides it, in a few
    words, and what fixes it: {} when it can start. On a profile that lets a backup stand in, a key whose part has a
    declared backup on this Mac is no need; one subscription signed in is enough for the Workers and their manager (vx
    sign_in). {"need": "signin", "plans": [...]} (the sign-ins that would do), {"need": "key", "keys": [...]},
    {"need": "model"}."""
    env = store.values(target, KEYS)
    chosen = picks(target, env, saved, defaults)
    plans, keys, model = [], [], False
    workers = [o for i in chosen["hands"]["use"] if (o := catalog.option("hands", i))]
    grok = catalog.option("hands", "grok-build")
    if (env.get("WORKERS_OPTIONAL") != "1"
            and not any(o["where"] == "mac" or not needs("hands", o, env) for o in workers)
            and needs("hands", grok, env)):
        plans = [o["needs"] for o in workers if o.get("needs") in catalog.SIGN_INS or o.get("needs") in catalog.OWN_SIGN_INS]
    for part in ("listen", "talk", "mind"):  # (the manager runs on a Worker's sign-in when its own is missing: vx sign_in)
        options = [o for o in [catalog.option(part, chosen[part].get("id", ""))] if o]
        for option in options:
            need = needs(part, option, env)
            backed = option.get("backup") or (part == "mind" and env.get("QUEEN_FALLBACK") == "local")
            if part == "mind" and env.get("QUEEN_FALLBACK") == "openai" and runtime.has_key("OPENAI_API_KEY", env):
                continue
            if need.startswith("key:") and not (stands_in(env) and backed):
                keys.append(need[4:])
            elif need.startswith("signin:") and not (stands_in(env) and backed):
                plans.append(need[7:])
            elif need == "model":
                model = True
    if plans:  # (the Workers' sign-ins first: what one click starts; then her mind's own)
        plans = list(dict.fromkeys(plans))
        names = list(dict.fromkeys(sign_in_name(p) for p in plans))
        return {"need": "signin", "plans": plans, "say": f"Sign in to {' or '.join(names)}"}
    if keys:
        keys = list(dict.fromkeys(keys))
        names = [catalog.KEY_NAMES.get(k, k) for k in keys]
        return {"need": "key", "keys": keys,
                "say": f"Needs your {', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else names[0]} key{'s' if len(names) > 1 else ''}"}
    if model:
        return {"need": "model", "say": "Its model is not on this Mac yet"}
    return {}


def menu() -> dict:
    """What the menu bar's panel shows, read quickly (no Feelings, accounts list or installs): where she runs and what
    each place still needs here; the open conversation's ears and mode (core/live.py), else the next call's mode; her
    eyes (Soulface) when this Mac can add or show them; a change of place still being applied."""
    from core import live
    applying = runtime.applying()
    profile = applying.get("profile") or runtime.profile_now()
    saved = store.remembered()
    places = profiles(profile)
    plains = {p["id"]: store.values(p["id"], KEYS, blocks=False) for p in places}
    defaults = {p: choices(plain) for p, plain in plains.items()}
    talk = live.conversation()
    adding = install.status("soulface") or {}
    return {
        "profile": profile,
        "applying": applying,
        "places": [{"id": p["id"], "name": p["name"], **reach(p["id"], saved, defaults)} for p in places],
        "voice_available": voice_available(store.values(profile, KEYS)),
        "open": bool(talk),
        "ears": bool(talk.get("ears")),
        "mode": talk.get("mode") or saved.get("call_mode", "talk"),
        "modes": catalog.CALL_MODES,
        "eyes": {"can": install.installed("soulface") or bool(install.addon_source("soulface")),
                 "on": saved.get("presence", "dots") == "soulface", "adding": adding.get("state") == "running"},
    }


def menu_apply(want: dict) -> dict:
    """One change from the menu bar's panel, then the panel as it is now ({"ok", "why"?, "menu"}). Her ears, the mode
    and her eyes at once (the open conversation follows them: core/live.py); a place the way the settings page applies
    it (checked first, then she switches over when she is free)."""
    if runtime.tests_running():
        return {"ok": False, "why": "Viventium is being tested right now.", "menu": menu()}
    why = ""
    if "ears" in want:  # (an ask, not a setting: one page claims it, the open one or the next to open: core/live.py)
        from core import live
        if not voice_available(store.values(runtime.profile_now(), KEYS)):
            why = "Voice needs an API key."
        else:
            live.ask_ears(bool(want["ears"]))
    elif "mode" in want:
        why = set_call_mode(want["mode"])
    elif "eyes" in want:
        why = set_presence("soulface" if want["eyes"] else "dots")
    elif "profile" in want:
        done = apply({"profile": want["profile"]})
        why = "" if done.get("ok") else done.get("why", "")
    else:
        why = "That is not something the menu bar can change."
    return {"ok": not why, **({"why": why} if why else {}), "menu": menu()}


# -- apply --

def no(why: str, **more) -> dict:
    return {"ok": False, "why": why, **more}


def check(part: str, choice: dict, env: dict) -> str:
    """"" when this choice exists and can run here, else why not in plain words (never changes anything)."""
    ids = choice.get("use") if part == "hands" else [choice.get("id")]
    if not ids or len(set(ids)) != len(ids):
        return "Choose at least one."
    for option_id in ids:
        option = catalog.option(part, option_id)
        if option is None:
            return "That choice does not exist."
        if not available_option(part, option, env):
            if option.get("local_model"):
                return "This choice needs more memory."
            if part == "mind":
                return "OpenAI is the backup on this Mac."
            return "This voice option is unavailable on this Mac."
        level = (choice.get("effort", {}).get(option_id) if part == "hands" else choice.get("effort")) or option.get("effort")
        if level and level not in option.get("efforts", []):
            return "That effort level does not exist for it."
        need = needs(part, option, env)
        if need.startswith("key:"):
            return f"{option['provider']} needs your key first."
        if need.startswith("signin:"):
            return f"Sign in to {sign_in_name(need[7:])} first."
        if need == "model":
            return f"Install {option['model']} first."
    return ""


def keep_left(saved: dict, target: str, left: dict) -> None:
    """What leaving() found, kept in her settings by profile, part and option (private_lines brings it back)."""
    for part, options in left.items():
        saved.setdefault("private", {}).setdefault(target, {}).setdefault(part, {}).update(options)


def remember_choice(saved: dict, part: str, choice: dict) -> None:
    if (where := place(part, choice)) in ("mac", "cloud"):  # (what a profile puts back; never a mix of both places)
        saved.setdefault("last", {}).setdefault(part, {})[where] = choice


def apply(want: dict) -> dict:
    now = show()
    if runtime.tests_running():
        return no("Viventium is being tested right now. Try again when it ends.")
    profile, env = now["profile"], store.values(now["profile"], KEYS)
    saved = store.remembered()

    # At once, no restart: these are hers, or this Mac's.
    if "telegram_token" in want:
        why = runtime.connect_telegram(want["telegram_token"], env)
        if why:
            return no(why)
        bot = runtime.telegram(env)
        if now["channels"]["telegram"]["id"] != bot["id"]:
            telegram_approvals.revoke()
        if not bot["on"]:
            return apply({"telegram": True})
        runtime.apply_when_idle(profile)
        return {"ok": True, "state": show()}
    if want.get("telegram_revoke") is True:
        try:
            telegram_approvals.revoke()
        except (OSError, ValueError, TypeError):
            return no("Viventium could not forget the Telegram chat.")
        return {"ok": True, "state": show()}
    if want.get("telegram_approvals") is True:
        bot = now["channels"]["telegram"]
        if not (bot["on"] and bot["connected"] and bot["id"] and re.fullmatch(r"@[A-Za-z0-9_]+", bot["bot"])):
            return no("Turn on your connected Telegram bot first.")
        try:
            link = telegram_approvals.pairing_link(bot["id"], bot["bot"])
        except (OSError, ValueError, TypeError):
            return no("Viventium could not read the Telegram owner settings.")
        return {"ok": True, "telegram_approval_link": link}
    if "key" in want:  # (kept in the Keychain; nothing of it is written or returned)
        key = str(want["key"].get("name", ""))
        why = runtime.add_key(key, str(want["key"].get("value", "")), env)
        if why:
            return no(why)
        if (stood_in(key, now, env) or (key == "OPENAI_API_KEY" and env.get("QUEEN_FALLBACK") == "openai")
                or (env.get("STT_AUTO") == "1" and key in ("XAI_API_KEY", "OPENAI_API_KEY"))):
            runtime.apply_when_idle(profile)
        return {"ok": True, "state": show()}
    if "chatgpt" in want:
        from core import accounts, chatgpt_sign_in as sign_in
        choice = want["chatgpt"]
        if not isinstance(choice, dict):
            return no("Choose a ChatGPT action.")
        action, registration = choice.get("action"), choice.get("account")
        if action == "connect" and (registration is None or isinstance(registration, str)):
            if registration is not None and not any(r["account"] == registration for r in runtime.chatgpt_status()["registrations"]):
                return no("That ChatGPT account does not exist.")
            why = runtime.connect_chatgpt(registration)
            return no(why) if why else {"ok": True, "state": show()}
        try:
            if action == "cancel":
                runtime.cancel_sign_in(sign_in.NEEDS)
            elif action == "disconnect" and not runtime.OFFLINE:
                sign_in.connection.disconnect()
                accounts.down(sign_in.NEEDS, "provider_auth_missing")
            else:
                return no("Choose a ChatGPT action.")
        except (OSError, sign_in.SignInError):
            return no("ChatGPT could not apply that change.")
        return {"ok": True, "state": show()}
    if "sign_in" in want:
        why = runtime.sign_in(str(want["sign_in"]))
        return no(why) if why else {"ok": True, "state": show()}
    if "sign_in_cancel" in want:  # (a sign-in of Light's own that waits: ended, nothing kept from it)
        runtime.cancel_sign_in(str(want["sign_in_cancel"]))
        return {"ok": True, "state": show()}
    if "install" in want:  # something not on this Mac yet: a quiet helper gets it, and the page shows how far it is
        why = install.start(str(want["install"]))
        return no(why) if why else {"ok": True, "state": show()}
    if "workers_note" in want:
        store.remember(lambda s: s.__setitem__("workers_note", str(want["workers_note"])[:600].strip()))
    if "media" in want:  # which tool makes photos and videos: kept with the Workers' sentence, read per job
        kind, option_id = str(want["media"].get("kind")), str(want["media"].get("id"))
        option = next((o for o in catalog.MEDIA.get(kind, {}).get("options", []) if o["id"] == option_id), None)
        if option is None:
            return no("That choice does not exist.")
        if why := needs(kind, option, env):
            return no("Log in to its subscription first." if why.startswith("signin") else f"Install {option['provider']} {option['model']} first.")
        keep_media(kind, option)
    if "presence" in want and (why := set_presence(want["presence"])):
        return no(why)
    if "call_mode" in want and (why := set_call_mode(want["call_mode"], want.get("call_mode_at"))):
        return no(why)
    if "telegram_voice" in want:  # the voice switch for voice replies on Telegram (chat/telegram.py VOICE_SWITCH)
        if not isinstance(want["telegram_voice"], bool):
            return no("Voice replies are on or off.")
        store.remember(lambda s: s.__setitem__("telegram_voice", want["telegram_voice"]))
    if want.get("show") == "privacy":  # where macOS lists what may read your folders (you tick it there yourself)
        runtime.show_privacy()
    if want.get("phone") is False:  # (off at once and for good: its doors closed and its lines written first, so nothing
        # that comes after it, a check that fails included, turns it back on; her parts drop it at their next start)
        phone_off(always=True)
        runtime.apply_when_idle(profile)
        want = {k: v for k, v in want.items() if k != "phone"}
        if not want:
            return {"ok": True, "state": show()}
    if want.get("forget_phones"):  # every paired phone unpaired at once: a new round of pairings, no restart
        why = runtime.forget_phones()
        return no(why) if why else {"ok": True, "state": show()}
    if "remove_file" in want:  # a file you sent, removed now (only from her inbox: settings/files.py)
        why = files.remove(str(want["remove_file"]))
        return no(why) if why else {"ok": True, "state": show()}
    for name in ("login", "menubar"):
        if name in want and bool(want[name]) != now["system"][name]:
            if why := runtime.set_system(name, bool(want[name])):
                return no(why)
    hers = now["character"]
    if hers["module"] and any(k in want for k in ("feelings", "nature", "band", "reset_feelings", "words", "bounds", "says")):
        control = feeling(env).control
        try:
            if "nature" in want and want["nature"] != hers["nature"]:
                if want["nature"] not in NATURES:
                    return no("That personality does not exist.")
                control("nature", want["nature"])
            if "feelings" in want and bool(want["feelings"]) != hers["on"]:
                control("resume" if want["feelings"] else "pause")
            if want.get("reset_feelings"):
                control("reset")
            if band := want.get("band"):
                if "on" in band:
                    control("on" if band["on"] else "off", band=str(band.get("id")))
                if "rest" in band:
                    control("rest", band=str(band.get("id")), value=float(band["rest"]))
                if "now" in band:
                    control("set", band=str(band.get("id")), value=float(band["now"]))
                if "pace" in band:
                    control("pace", band=str(band.get("id")), value=float(band["pace"]))
            if words := want.get("words"):
                control("words", choice=str(words.get("text", ""))[:600], band=str(words.get("band")), value=int(words.get("level", -1)))
            if (bounds := want.get("bounds")) is not None:  # where each level begins (thresholds and ranges)
                if why := bounds_why((bounds or {}).get("at")):
                    return no(why)
                control("bounds", band=str(bounds.get("band")), choice=",".join(str(int(x)) for x in bounds["at"]))
            if says := want.get("says"):  # what a level says, in your words in place of main's ("" puts main's back)
                control("says", choice=str(says.get("text", "")).strip()[:1200], band=str(says.get("band")), value=int(says.get("level", -1)))
        except (ValueError, TypeError):
            return no("That is not something Feelings can do.")

    # Accounts you add or remove for her Workers (xPerfect's Connections): at once, no restart.
    if "add_account" in want:
        why = add_account(want["add_account"])
        return no(why) if why else {"ok": True, "state": show()}
    if "remove_account" in want:
        why = remove_account(want["remove_account"])
        return no(why) if why else {"ok": True, "state": show()}
    if "account_signin" in want:  # (an account you added whose sign-in ended: its sign-in again)
        why = sign_in_again(want["account_signin"])
        return no(why) if why else {"ok": True, "state": show()}
    if "account_input" in want:  # (a code the provider's sign-in asks you to paste back)
        try:
            runtime.xperfect("POST", f"/v1/provider-accounts/{want['account_input'].get('account', '')}/setup/input",
                             {"value": str(want["account_input"].get("value", ""))[:400]})
        except RuntimeError as e:
            runtime.logged("a sign-in code for an added account", f"{type(e).__name__}: {e}")
            return no("The code was not taken. Check it and try again.")
        return {"ok": True, "state": show()}
    keys_off, restart = None, False
    if "account" in want:  # (an account off or on: what it amounts to, applied as the same choices would be)
        made = account(want["account"], env, dict(now["choices"]))
        if isinstance(made, str):
            return no(made)
        keys_off = made.pop("keys_off", None)
        if keys_off is not None:  # (her mind's own sign-in turned off or on: a call and Telegram follow it at their next
            # request, brain/queen._turned_off; she restarts at her next calm moment, never checked first and never put
            # back: your choice holds, also with no backup, when her replies pause. A key's line stays as on main.)
            toggled = set(keys_off.split()) ^ set(env.get("KEYS_OFF", "").split())
            restart = bool(toggled & set(catalog.OWN_SIGN_INS))
            if want["account"].get("line") == "key" and want["account"].get("id") == "openai" \
                    and (env.get("SMALL_MAC_TIER") or runtime.own_is_off("OPENAI_API_KEY")):
                changed_switch = runtime.own_is_off("OPENAI_API_KEY") == bool(want["account"].get("use"))
                runtime.own_off("OPENAI_API_KEY", not want["account"].get("use"))
                restart = bool(env.get("SMALL_MAC_TIER")) and (changed_switch or bool(toggled))
            if want["account"].get("line") == "mind":  # (the page's own switch, as asked, whatever a profile line says:
                # turned on, it is cleared even when KEYS_OFF never named it; no profile line undoes it)
                name = next((a["mind"] for a in catalog.ACCOUNTS if a["id"] == want["account"].get("id") and a.get("mind")), "")
                if name and runtime.own_is_off(name) != (not want["account"].get("use")):
                    runtime.own_off(name, not want["account"].get("use"))
                    restart = True
        if (routes_off := made.pop("accounts_off", None)) is not None:  # read by each job: at once, no restart
            store.remember(lambda s: s.__setitem__("accounts_off", routes_off))
            if not made and keys_off is None:
                return {"ok": True, "state": show()}
        want = {**{k: v for k, v in want.items() if k != "account"}, **made}

    # What she runs on: checked first, then applied when she is free.
    target = want.get("profile", profile)
    if target not in [p["id"] for p in now["profiles"]]:
        return no("That profile does not exist.")
    plains = {p["id"]: store.values(p["id"], KEYS, blocks=False) for p in now["profiles"]}
    defaults = {p: choices(plain) for p, plain in plains.items()}
    if "profile" in want:  # a profile says where each part runs; the option is the one last chosen for that place
        # (asked for by name, a profile always puts every part back where it says, also from "your own mix")
        chosen = {}
        for part in PARTS:
            where = place(part, defaults[target][part])
            last = saved.get("last", {}).get(part, {}).get(where)
            chosen[part] = last if last and not check(part, last, env) else defaults[target][part]
    else:
        chosen = dict(now["choices"])
    for part in PARTS:
        if part in want:
            chosen[part] = want[part]
            if why := check(part, want[part], env):
                return no(why)
    # Work on this Mac manages itself; the Worker manager manages the online work. So the manager is this Mac's only
    # when every Worker is on this Mac, and the one you did not touch follows the other.
    if "other" not in (first("manager", chosen["manager"]), first("hands", chosen["hands"])) \
            and (place("manager", chosen["manager"]) == "mac") != (place("hands", chosen["hands"]) == "mac"):
        if "manager" in want and "hands" not in want:
            chosen["hands"] = {"use": [chosen["manager"]["id"]], "effort": {}}
        else:  # (the first online Worker; with none, the one on this Mac)
            online = [i for i in chosen["hands"]["use"] if catalog.option("hands", i)["where"] != "mac"]
            chosen["manager"] = {"id": (online or chosen["hands"]["use"])[0]}
    # Parts that now sit where another profile puts them: she is on that profile (one name for one truth).
    if "profile" not in want:
        places = {part: place(part, chosen[part]) for part in PARTS}
        fits = [p for p in defaults if all(place(part, defaults[p][part]) == places[part] for part in PARTS)]
        target = profile if profile in fits or not fits else fits[0]

    plain, block = plains[target], {}
    # (each profile as it runs now, and what its tracked file alone says: where an option's private lines are)
    running = {p["id"]: store.values(p["id"], KEYS) for p in now["profiles"]}
    tracked = {p["id"]: store.shell_values([store.read(store.files(p["id"])[0])], KEYS) for p in now["profiles"]}
    for part in PARTS:
        choice = chosen[part]
        if first(part, choice) == "other":  # set by hand: keep whatever the block already says for this part
            keys = HANDS_KEYS if part == "hands" else MANAGER_KEYS if part == "manager" else \
                [k for o in PARTS[part]["options"] for k in o["env"]] + ["QUEEN_EFFORT"]
            block.update({k: v for k, v in store.block(target).items() if k in keys})
            continue
        own = lines(part, choice)
        if part == "talk" and own.get("TTS") in ("xai", "xai_plan") and env.get("SMALL_MAC_TIER") in ("8", "16"):
            own["TTS_FALLBACK"] = "mac_say"
        automatic_voice = part == "talk" and tracked[target].get("TTS") == "auto"
        fixed_voice = automatic_voice and ("talk" in want or "TTS" in store.block(target)
                                         or first(part, choice) != first(part, defaults[target][part]))
        if part == "talk" and automatic_voice and not fixed_voice:
            own = {}  # An unrelated setting must not turn the automatic voice into a saved choice.
        elif part not in ("hands", "manager") and not fixed_voice and first(part, choice) == first(part, defaults[target][part]):
            # The profile's own option: its lines are the shipped profile's, so an update to them is followed; only the
            # thinking effort is yours (an option chosen elsewhere carries its lines from the catalog).
            own = {k: v for k, v in own.items() if k == PARTS[part].get("effort")}
        # (your own lines stay in force as they are; the ones the page keeps for you are written as they are, empty too)
        hand, found = private_lines(part, choice, target, plains, running, tracked, saved)
        wanted = {**own, **hand}
        if part == "manager" and first("hands", chosen["hands"]) != "other":
            # Unset, the manager is the first Worker's harness at that Worker's effort: a choice equal to that says nothing.
            if wanted["MANAGER_PROFILE"] == lines("hands", chosen["hands"])["WORKER_PROFILE"]:
                wanted["MANAGER_PROFILE"] = ""
            follows = chosen["hands"].get("effort", {}).get(choice["id"]) or (catalog.option("manager", choice["id"]) or {}).get("effort", "")
            if wanted["MANAGER_EFFORT"] == follows:
                wanted["MANAGER_EFFORT"] = ""
        block.update({k: v for k, v in wanted.items() if plain.get(k, "") != v})
        if fixed_voice:
            block["TTS"] = wanted["TTS"]  # Even a choice equal to today's default stays the person's choice.
        block.update(found)
    left = leaving(target, chosen, running)
    base, machine, own = store.files(target)
    machine_plain = store.shell_values([store.read(base), store.split(store.read(machine))[0]], KEYS)
    mine = dict(store.machine_block())
    if "telegram" in want:
        mine.pop("TELEGRAM", None)
        if bool(want["telegram"]) != (machine_plain.get("TELEGRAM", "") != "off"):
            mine["TELEGRAM"] = "on" if want["telegram"] else "off"
    if "phone" in want:  # calling from the phone: the page's two doors on this Mac's name (./vx opens them at its start)
        on = None
        if want["phone"]:  # (its network remembered: the doors stay shut on any other)
            where = runtime.phone_address()
            if not where["ip"] or not where.get("network"):
                return no("This Mac is not on a network your phone could reach it on right now.")
            on = {"VX_LAN_ORIGIN": where["page"], "VX_LAN_LIVEKIT_URL": where["call"], "VX_LAN_NETWORK": where["network"]}
        phone_lines(mine, on, plain)
    if keys_off is not None:  # (a key Light does not load: this Mac's line, read by vx and the page)
        mine.pop("KEYS_OFF", None)
        if keys_off:
            mine["KEYS_OFF"] = keys_off
    if not hers["module"] and want.get("feelings"):  # the one case that is a profile line: the module itself, on
        mine["FEELINGS"] = want.get("nature") if want.get("nature") in NATURES else "warm"

    before = {own: store.read(own), machine: store.read(machine)}
    after = {own: store.join(store.split(before[own])[0], block), machine: store.join(store.split(before[machine])[0], mine)}
    changed = target != profile or any(before[f] != after[f] for f in before)
    if restart and not changed and set(want) <= {"talk"} and target == profile:  # (only the page's own switch moved)
        runtime.apply_when_idle(target)
        return {"ok": True, "state": show()}
    if changed:
        for file, text in after.items():
            store.write(file, text)
        if restart and set(want) <= {"talk"} and target == profile:
            runtime.apply_when_idle(target)
            return {"ok": True, "state": show()}
        if set(want) <= {"talk"} and target == profile:
            # Her voice alone: a call and Telegram read it from these files when they change (speech/live.py), so the
            # next words she says are in it. Nothing restarts and nothing waits for a call to end (a voice that
            # changed only after the call felt like a bug). What it needs was checked above.
            store.remember(lambda s: [keep_left(s, target, left)] + [remember_choice(s, part, chosen[part]) for part in PARTS if part in want])
            return {"ok": True, "state": show()}
        if not runtime.ran(f"checking {target} before switching over", runtime.vx("ready", target, timeout=180)):
            # Nothing was stopped, and the files are put back as they were. Why, in vx's own words, is in her settings
            # log; the page says what did not change.
            for file, text in before.items():
                store.write(file, text)
            names = {p["id"]: p["name"] for p in now["profiles"]}
            if target != profile:
                return no(f"Nothing changed: {names.get(target, target)} cannot start on this Mac right now, so Viventium "
                          f"stays on {names.get(profile, profile)}.")
            return no("Nothing changed: that choice cannot start on this Mac right now, so Viventium keeps what it had.")
        runtime.apply_when_idle(target)
        store.remember(lambda s: keep_left(s, target, left))
    store.remember(lambda s: [remember_choice(s, part, chosen[part]) for part in PARTS if part in want or "profile" in want])
    return {"ok": True, "state": show()}
