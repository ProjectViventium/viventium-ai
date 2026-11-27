"""The texts Viventium is given, as the settings page shows them (python -m settings prompts show): every prompt the
ledger keeps (brain/prompts/ledger.json), by category, with the one really in force: the shipped text, or the owner's
own. A text edited on a page of its own (the ledger's edited_on: Scheduling for the routines, Subconscious for the
cards) is read the way its reader reads it (core/routines.words, settings/subconscious.show) and names that page. When
a saved text of his cannot be used (unreadable, not UTF-8, or one that would break what is given), its own place on the
page says why (brain/prompts entries(): set_aside) and that the shipped text is used instead. Shown here, never changed
here."""
from brain import prompts as ledger

INSTEAD = "Viventium uses the shipped text instead."


def _why(set_aside: str) -> str:
    """The reason alone (the page says what is used instead, in its own line)."""
    return set_aside.removesuffix("Using the shipped text.").strip()


def _routine(entry: dict) -> tuple[str, str]:
    """(in force, as shipped): what the routine is told when it wakes, read as the routine reads it."""
    from core import routines
    name = entry["id"].split("/", 1)[1]
    return routines.words(name), routines._routine(name)["prompt"]


def _cards(state: dict) -> str:
    """The Subconscious as a round reads it: the coordinator's words, what every cortex is told first, each card that
    is on (When and Then), and how a thought reaches the conversation."""
    on = [c for c in state["cortices"] if c.get("on", True)]
    parts = [("Before the cards", state["coordinator"]["before"]), ("What every cortex is told first", state["every_cortex"])]
    parts += [(f"[{c['id']}] {c['name']}", f"When: {c['when'].strip() or '(every turn)'}\nThen: {c['then'].strip()}")
              for c in on]
    parts += [("After the cards", state["coordinator"]["after"]),
              ("How a thought reaches the conversation", state.get("surfacing", ""))]
    off = [c["name"] for c in state["cortices"] if not c.get("on", True)]
    return "\n\n".join(f"{head}:\n{words.strip()}" for head, words in parts if words.strip()) \
        + (f"\n\nSwitched off: {', '.join(off)}." if off else "")


def _subconscious(entry: dict) -> tuple[str, str]:
    from settings import subconscious as page
    return _cards(page.show()), _cards(page.defaults())


EDITED = {"the Scheduling page": ("/settings/scheduling", _routine),
          "the Subconscious page": ("/settings/subconscious", _subconscious)}


def show() -> dict:
    found = ledger._ledger()
    prompts = []
    for entry in ledger.entries():
        item = {"id": entry["id"], "title": entry["title"], "category": entry["category"], "about": entry["about"],
                "text": entry.get("text", ""), "file": entry.get("file", ""), "yours": bool(entry.get("yours")),
                "set_aside": _why(entry.get("set_aside", "")), "edited_on": "", "edited_at": ""}
        if (page := EDITED.get(entry.get("edited_on", ""))) is not None:  # (read as its own reader reads it)
            now, shipped = page[1](entry)
            item.update(text=now, yours=" ".join(now.split()) != " ".join(shipped.split()), set_aside="",
                        edited_on=entry["edited_on"], edited_at=page[0])
        item["instead"] = INSTEAD if item["set_aside"] else ""
        prompts.append(item)
    aside = sum(1 for p in prompts if p["set_aside"])
    yours = sum(1 for p in prompts if p["yours"])
    status = (f"{aside} of your saved texts cannot be used; the shipped text is used for {'it' if aside == 1 else 'them'}."
              if aside else f"{yours} of your own in force; the rest as shipped." if yours else "Every text as shipped.")
    return {"status": status, "categories": [c for c in found["categories"] if c["id"] != "code"], "prompts": prompts,
            "in_code": len(found["in_code"])}


def apply(change: dict) -> dict:
    return {"ok": False, "why": "These texts are shown here, not changed here."}
