"""The Subconscious page's two calls: show() the cortices as they are set, and apply() one change.

A cortex is a card, and a card is two prompts: "When" says when it should run, "Then" says what it does. The
coordinator reads every "When" as one prompt after a turn and answers with the cortices to run; a card whose
"When" is empty is not asked about, it runs every turn. merged() is that one prompt, the same text the page
shows. What comes with Light is in brain/subconscious/; what you changed is in state/subconscious.json.

This module keeps and shows; brain/rounds.py runs them, after every turn, as they are set here. show() also says where
each one runs on the profile now, at what effort, and why when that is not exactly the card's choice (`place`: what
runs, never only what was chosen), and what it did last (brain/rounds.last_runs: where it really ran).
"""
import uuid

from core import cards
from settings import catalog

HOME = cards.BRAIN / "subconscious"
PAGE = "subconscious"
FIELDS = ("when", "then", "runs_on", "effort", "linked", "on")  # what a card lets you change
WAITS = (1, 3, 10)  # minutes the linked cortices wait for each other, at most
LIMITS = {"name": 60, "when": 2000, "then": 6000, "every_cortex": 4000, "surfacing": 4000}
FOLLOW = "manager"  # the coordinator runs on whatever the Worker manager runs on, unless you choose
HELPERS = "helpers"  # a card may run on her quick helpers, as the profile sets them (core/helpers.py)
HELPER_NAMES = {"claude": "Claude", "openai": "OpenAI", "xai_plan": "Grok", "mac": "this Mac"}
HELPER_MARKS = {"claude": "claude", "openai": "openai", "xai_plan": "xai", "mac": "ollama"}
HELPER_EFFORTS = ("none", "low")  # thinking off, or on (each helper thinks its own way: core/helpers.py, think)
# What a part on this Mac's model can take (Qwen 3.6 thinks or not; brain/rounds.mac_effort). The Workers' own choice
# of it has none to set (its harness sets its own), but a cortex or the coordinator asked there directly does: before,
# the coordinator thought at low while its card said "This model has one".
MAC_EFFORTS = ("none", "low", "medium", "high")
PROFILE_KEYS = ["WORKERS", "MANAGER_PROFILE", "WORKER_PROFILE", "HELPERS", "MEMORY_CORTEX"]


def _cortex(path) -> dict:
    facts, body = cards.read(path)
    words = cards.parts(body, ("When", "Then"))
    then = words.get("then", "")
    if source := facts.get("then_from"):  # one text, kept in one place (Feelings' own prompt, as the prompt ledger has it in force)
        from brain import prompts as ledger
        then = _unwrapped(ledger.text(source.removesuffix(".md")))
    return {"id": path.stem.split("-", 1)[1], "name": facts["name"], "group": facts["group"], "region": facts.get("region", ""),
            "does": facts.get("does", ""), "sign": facts.get("sign", "sparkles"), "system": True,
            "hands_back": facts.get("hands_back", "thought"),  # a thought for the conscious mind, or a change to Feelings
            "when": words.get("when", ""), "then": then, "runs_on": facts["runs_on"], "effort": facts.get("effort", ""),
            "linked": facts.get("linked", True), "on": facts.get("on", True),
            # (typed, never read from a name: the memory search runs first and its finds come with the conversation;
            # needs_finds: when it finds nothing new, the cortex is not asked at all)
            "searches": facts.get("searches", ""), "needs_finds": bool(facts.get("needs_finds", False))}


def _unwrapped(text: str) -> str:
    """A prompt file wrapped by hand at 100 columns, as running paragraphs (list lines stay their own lines)."""
    out = []
    for paragraph in text.split("\n\n"):
        lines = []
        for line in paragraph.splitlines():
            if lines and not line.lstrip().startswith("- ") and not lines[-1].lstrip().startswith("- "):
                lines[-1] += " " + line.strip()
            else:
                lines.append(line.rstrip())
        out.append("\n".join(lines))
    return "\n\n".join(out)


def defaults() -> dict:
    facts, body = cards.read(HOME / "coordinator.md")
    words = cards.parts(body, ("Before the cards", "After the cards"))
    return {
        "coordinator": {"on": facts.get("on", True), "runs_on": facts.get("runs_on", FOLLOW), "effort": facts.get("effort", "low"),
                        "wait": int(facts.get("wait_minutes", 3)), "before": words["before_the_cards"], "after": words["after_the_cards"]},
        "cortices": [_cortex(p) for p in sorted((HOME / "cortices").glob("*.md"))],
        "every_cortex": cards.read(HOME / "every_cortex.md")[1], "surfacing": cards.read(HOME / "surfacing.md")[1],
    }


def merged(coordinator: dict, cortices: list[dict]) -> str:
    """The one prompt the coordinator reads: its own words, then the "When" of every card that is on and has one."""
    asked = [c for c in cortices if c["on"] and c["when"].strip()]
    listed = "\n\n".join(f"[{c['id']}] {c['name']}\n{c['when'].strip()}" for c in asked)
    return "\n\n".join(part for part in (coordinator["before"], listed, coordinator["after"]) if part)


def show() -> dict:
    base, saved = defaults(), cards.kept(PAGE)
    cortices = [{**c, **{f: v for f, v in saved.get("cards", {}).get(c["id"], {}).items() if f in FIELDS}} for c in base["cortices"]]
    cortices += [{"group": "own", "region": "", "does": "", "sign": "sparkles", "system": False, "hands_back": "thought", **own}
                 for own in saved.get("own", [])]
    coordinator = {**base["coordinator"], **{f: v for f, v in saved.get("coordinator", {}).items() if f in ("on", "runs_on", "effort", "wait")}}
    env, last = _profile(), _last()
    from brain import rounds
    for c in cortices:
        where = rounds.cortex_place(c, env)
        c["runs_on"], c["place"] = where.chose, _runs(where)
        c["last"] = last.get(c["id"])
    coordinator["place"] = _runs(rounds.coordinator_place(coordinator, env))
    coordinator["last"] = last.get("coordinator")
    return {
        "running": bool(coordinator["on"]),  # brain/rounds.py runs a round after every turn while it is on
        "status": _status(bool(coordinator["on"]), rounds.local(env), last.get("round")),
        "last_round": last.get("round"),
        "helpers": _helpers(env),
        "coordinator": coordinator,
        "groups": [g for g in _groups() if any(c["group"] == g["id"] for c in cortices)],
        "cortices": cortices,
        "every_cortex": saved.get("every_cortex", base["every_cortex"]), "surfacing": saved.get("surfacing", base["surfacing"]),
        "merged": merged(coordinator, cortices),
        "always": [c["name"] for c in cortices if c["on"] and not c["when"].strip()],
        "waits": list(WAITS),
        "mac_efforts": list(MAC_EFFORTS),
    }


def _runs(where) -> dict:
    """Where a part runs on the profile now and at what thinking effort, as it is; `note` says why that is not exactly
    what was chosen ("On Local every cortex thinks on this Mac."), "" when it is."""
    return {"kind": where.kind, "name": where.name, "effort": where.effort, "note": where.note}


def _profile() -> dict:
    """The profile's settings that decide where a part runs (the way ./vx loads them)."""
    try:
        from settings import runtime, store
        return store.values(runtime.profile_now(), PROFILE_KEYS)
    except Exception:  # noqa: BLE001 (no profile to read: as this process runs)
        import os
        return {k: os.environ.get(k, "") for k in PROFILE_KEYS}


def _last() -> dict:
    from brain import rounds
    return rounds.last_runs()


def _helpers(env: dict) -> dict:
    """Her quick helpers as a choice for a card: they follow the profile (core/helpers.py)."""
    kinds = [part.split(":", 1)[0].strip() for part in (env.get("HELPERS") or "mac").split(",") if part.strip()] or ["mac"]
    names = [HELPER_NAMES.get(k, k) for k in kinds]
    return {"id": HELPERS, "provider": "Viventium", "model": "Quick helpers", "mark": HELPER_MARKS.get(kinds[0], "ollama"),
            "where": "mac" if kinds == ["mac"] else "key", "tried": True, "needs": "", "efforts": list(HELPER_EFFORTS),
            "effort": "none",
            "detail": "Follows your profile: " + ", then ".join(names) + "."}


def _status(on: bool, local: bool, last: dict | None) -> str:
    """One true line under the title: whether it runs, and where."""
    if not on:
        return "Off. Nothing runs after an answer: your Feelings do not move and Deep memory does not look."
    line = "Running after every answer, on calls and on Telegram."
    return line + (" On Local every cortex thinks on this Mac, one at a time, after each answer, and waits while your "
                   "work uses this Mac." if local else "")


def _groups() -> list[dict]:
    import json
    return json.loads((HOME / "groups.json").read_text())


def no(why: str) -> dict:
    return {"ok": False, "why": why}


def _who(part: str, runs_on, effort) -> tuple[str, str] | str:
    """A Worker type and thinking effort that exist together, or why not (a sentence)."""
    option = catalog.option(part, str(runs_on))
    if option is None:
        return "That Worker type does not exist."
    mac = option.get("where") == "mac" and not option.get("efforts")
    efforts = list(MAC_EFFORTS) if mac else option.get("efforts", [])
    if effort and effort not in efforts:
        effort = ""  # (a level the new Worker type does not have: its own usual one)
    return option["id"], effort or ("none" if mac else option.get("effort", "") if efforts else "")


def apply(want: dict) -> dict:
    from settings import runtime
    if runtime.tests_running():
        return no("Viventium is being tested right now. Try again when it ends.")
    base = defaults()
    by_id = {c["id"]: c for c in base["cortices"]}
    added = None

    if "coordinator" in want:
        change = dict(want["coordinator"])
        if "wait" in change and change["wait"] not in WAITS:
            return no("That wait does not exist.")
        if "runs_on" in change or "effort" in change:
            now = show()["coordinator"]
            runs_on = change.get("runs_on", now["runs_on"])
            if runs_on == FOLLOW:
                change["runs_on"] = FOLLOW
                if "effort" in change and change["effort"] not in catalog.EFFORT:
                    return no("That effort level does not exist.")
            else:
                who = _who("manager", runs_on, change.get("effort", now["effort"]))
                if isinstance(who, str):
                    return no(who)
                change["runs_on"], change["effort"] = who
        if "on" in change:
            change["on"] = bool(change["on"])

        def keep_coordinator(s: dict) -> None:
            mine = {**s.get("coordinator", {}), **{f: v for f, v in change.items() if f in ("on", "runs_on", "effort", "wait")}}
            s["coordinator"] = cards.differing(base["coordinator"], mine, ("on", "runs_on", "effort", "wait"))
            if not s["coordinator"]:
                del s["coordinator"]
        cards.keep(PAGE, keep_coordinator)

    if "card" in want:
        change = dict(want["card"])
        card_id = str(change.pop("id", ""))
        own = next((c for c in cards.kept(PAGE).get("own", []) if c["id"] == card_id), None)
        if card_id not in by_id and own is None:
            return no("That cortex does not exist.")
        for field in ("when", "then", "name"):
            if field in change:
                change[field] = str(change[field])[:LIMITS[field]]
        for field in ("linked", "on"):
            if field in change:
                change[field] = bool(change[field])
        if "runs_on" in change or "effort" in change:
            now = next(c for c in show()["cortices"] if c["id"] == card_id)
            if change.get("runs_on", now["runs_on"]) == HELPERS:  # her quick helpers: thinking off, or on
                effort = change.get("effort", now["effort"])
                change["runs_on"], change["effort"] = HELPERS, effort if effort in HELPER_EFFORTS else ""
            else:
                who = _who("hands", change.get("runs_on", now["runs_on"]), change.get("effort", now["effort"]))
                if isinstance(who, str):
                    return no(who)
                change["runs_on"], change["effort"] = who

        def keep_card(s: dict) -> None:
            if own is not None:  # yours: kept whole
                mine = next(c for c in s["own"] if c["id"] == card_id)
                mine.update({f: v for f, v in change.items() if f in (*FIELDS, "name")})
                return
            mine = {**s.get("cards", {}).get(card_id, {}), **{f: v for f, v in change.items() if f in FIELDS}}
            mine = cards.differing(by_id[card_id], mine, FIELDS)
            s.setdefault("cards", {})[card_id] = mine
            if not mine:
                del s["cards"][card_id]
            if not s["cards"]:
                del s["cards"]
        cards.keep(PAGE, keep_card)

    if want.get("add"):
        first = catalog.option("hands", "claude") or catalog.PARTS["hands"]["options"][0]
        who = _who("hands", str(want.get("runs_on") or first["id"]), "low")
        if isinstance(who, str):
            return no(who)
        added = "own-" + uuid.uuid4().hex[:6]
        new = {"id": added, "name": "", "when": "", "then": "", "runs_on": who[0], "effort": who[1], "linked": True, "on": True}
        cards.keep(PAGE, lambda s: s.setdefault("own", []).append(new))

    if "remove" in want:
        card_id = str(want["remove"])
        if card_id in by_id:
            return no("A cortex that comes with Viventium can be switched off, not removed.")

        def drop(s: dict) -> None:
            s["own"] = [c for c in s.get("own", []) if c["id"] != card_id]
            if not s["own"]:
                del s["own"]
        cards.keep(PAGE, drop)

    for name in ("every_cortex", "surfacing"):
        if name in want:
            text = str(want[name])[:LIMITS[name]].strip()

            def keep_text(s: dict, name=name, text=text) -> None:
                if text and text != base[name]:
                    s[name] = text
                else:  # emptied, or back to what came with Light: the default again
                    s.pop(name, None)
            cards.keep(PAGE, keep_text)

    return {"ok": True, "state": show(), **({"added": added} if added else {})}
