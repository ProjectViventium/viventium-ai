"""The Memory page's two calls: show() what Viventium keeps about you, and apply() one look or one change.

What it shows: what is kept in mind in every conversation (the standing view, as it stands by your changes), the
latest conversations it remembers (their summaries), what you changed (with an undo), and how memory runs right now,
each part with its own state. A look searches everything it keeps (core/memory.inspect); a change is the same change
her voice tools make (brain/memory_tools.py): correct, forget, undo, listed once, naming exactly the line you acted on.
Reading never changes anything, and a change never edits your own notes.

    python -m settings.memory show | apply < JSON
"""
import json
import re
import sys

from core import life, memory

CONVERSATIONS = 12  # the latest conversation summaries shown
# Where a fact of a conversation was that you asked not to bring up: said in its place (never as if never said).
LEFT_OUT = "Something you asked Viventium not to bring up."
PART_LEFT_OUT = "(Part of this is something you asked Viventium not to bring up.)"


def _standing(live: list[dict] | None = None) -> list[dict]:
    """The standing view, line by line under its sections, as she reads it (the page showed the whole
    line after one sentence of it was forgotten): a line you forgot is not shown (it is in the changes, with its undo),
    a part you forgot is not shown, a line you corrected shows your words; `mark` stands for the line as the file has
    it (core/life.line_mark), which a change from the page sends (a line changed since is refused, never acted on)."""
    root = life.life()
    path = root / "Views" / life.CORE_NAME if root else None
    if not path or not path.exists():
        return []
    rel = f"Views/{life.CORE_NAME}"
    live = life.in_force() if live is None else live
    forgets = [c for c in live if c["kind"] == "forget"]
    out, section = [], ""
    for number, line in enumerate(path.read_text(errors="replace").split("\n"), 1):
        text = line.strip()
        if not text or text.startswith("<!--"):
            continue
        if title := life.core_title(line):  # (its titles are the runtime's: always a heading, never a line to change,
            section = title                 # with or without the marks a model wrote)
            continue
        if heading := re.match(r"#{1,6}\s+(.*)", text):
            shown = life.current(line, 0.0, live, rel, first=number)
            section = shown.lstrip("# ").strip().strip("*") if shown.strip() else ""
            fix = life.latest_fix(live, lambda c: life._names(c, rel, line, number))
            if fix and shown.strip():
                section = fix["said"]
            continue
        left = life.current(line, 0.0, forgets, rel, first=number)
        if not left.strip():
            continue  # (forgotten)
        fix = life.latest_fix(live, lambda c: life._names(c, rel, line, number))
        out.append({"id": f"{rel}:{number}", "section": section, "text": left.strip().lstrip("-*• ").strip(),
                    "mark": life.line_mark(line), **({"now": fix["said"], "corrected": fix["at"]} if fix else {})})
    return out


def _facts(text: str) -> list[str]:
    """A summary's "Facts the user stated" lines (Light's own summary format), from every part of a long one (before,
    only the first part's were read, so a fact said in its second part never showed)."""
    lines = [l.strip().lstrip("-*• ").strip()
             for part in re.findall(r"(?ms)^#{1,5}\s*Facts the user stated[^\n]*\n(.*?)(?=^#{1,5} |\Z)", text)
             for l in part.split("\n")]
    return [l for l in lines if l and l.lower() not in ("none", "none.")][:6]


def _conversations(live: list[dict] | None = None) -> list[dict]:
    """The latest conversation summaries, newest first: title, where and when, what the user said in it, a fact you
    asked not to bring up said so in its place (one you forgot whole is not shown: it is in the changes, with its
    undo)."""
    root = life.life()
    folder = root / "Memory" / "Conversations" if root else None
    if not folder or not folder.exists():
        return []
    live = life.in_force() if live is None else live
    gone = life.skipped(live)
    found = sorted((p for p in life._summaries() if str(p.relative_to(root)) not in gone),
                   key=lambda p: p.name, reverse=True)[:CONVERSATIONS]  # (the folder walked once)
    out = []
    for path in found:
        rel = str(path.relative_to(root))
        source = life.source(rel, root)
        # (each by its name, its date and a short id, never its file's name, which came from its title)
        plain = source["label"].removeprefix("summary of a ").capitalize()
        if issue := source.get("unreadable"):
            out.append({"id": life.name_of(rel, root), "title": plain, "source": source["label"], "date": source["date"],
                        "facts": [], "unreadable": issue})
            continue
        text = life.marked(life._file_text(path), rel, live, gone=LEFT_OUT, part=PART_LEFT_OUT)
        title = next((l.lstrip("# ").strip() for l in text.split("\n") if l.startswith("# ")), plain)
        out.append({"id": life.name_of(rel, root), "title": title, "source": source["label"], "date": source["date"],
                    "facts": _facts(text)})
    return out


def show() -> dict:
    """The page's state. When the change list cannot be read nothing of memory is shown, only why (anything shown
    could be what you asked to forget)."""
    try:
        with life.one_pass():  # (the change list, the record and the summary folder read once for all of it)
            live = life.in_force()
            return {"life": bool(life.life()), "status": memory.status(), "standing": _standing(live),
                    "conversations": _conversations(live), "changes": memory.changes(20)}
    except life.Unreadable as e:
        return {"life": bool(life.life()), "status": memory.status(), "standing": [], "conversations": [],
                "changes": [], "unreadable": str(e)}


def no(why: str) -> dict:
    return {"ok": False, "why": why}


def _shown(change: dict) -> dict:
    """What the page showed for each place it acts on ({place id: the mark of the line it showed}): a place that holds
    something else now is refused (core/memory._passages)."""
    shown = change.get("shown") or {}
    return {str(k): str(v) for k, v in shown.items()} if isinstance(shown, dict) else {}


def _receipt(answer: dict) -> dict:
    """What the page says after a change: what was kept, what still holds the same words, and, for a line of a summary,
    the messages it may have come from (the page's per-line Forget never named the message, so it came
    back when that conversation was summarized again): one more click each."""
    if not answer.get("ok"):
        return {}
    return {"id": answer.get("id", ""), "places": len(answer.get("passages", [])) + len(answer.get("messages", [])),
            "still": _for_page(answer.get("still", answer.get("also", []) if answer.get("kind") == "correct" else [])),
            "from": _for_page(answer.get("from", []))}


def _for_page(items: list[dict]) -> list[dict]:
    """Places as the page gets them: a summary by its name alone (its id: its date and a short id), never by its file's
    place in Life, which came from its title (the page showed it when the pointer rested on a line)."""
    return [{**i, "path": ""} if life.kind_of(i.get("path", "")) == "summary" else i for i in items]


def apply(want: dict) -> dict:
    if "look" in want:
        about = str(want["look"] or "").strip()[:300]
        issues: set[str] = set()
        try:
            found = memory.inspect(about, issues=issues) if about else []
        except life.Unreadable as e:
            return no(f"Nothing can be shown: {e}.")
        warning = life.search_notice(issues, bool(found))
        return {"ok": True, "looked": about, "found": _for_page(found), "state": show(),
                **({"warning": warning} if warning else {})}
    if "older" in want:  # (an older conversation's own messages, before its forget: a look, nothing is changed)
        try:
            found = memory.older_look(str(want["older"] or ""))
        except life.Unreadable as e:
            return no(f"Nothing can be shown: {e}.")
        return {"ok": True, **(found or {"look": None})}
    if "correct" in want:
        change = dict(want["correct"] or {})
        new = str(change.get("new", "")).strip()
        if not new:
            return no("Write what it should say instead, or use Forget.")
        answer = memory.correct(str(change.get("old", "")), new, tuple(change.get("passages") or ()), by="page",
                                shown=_shown(change))
    elif "forget" in want:
        change = dict(want["forget"] or {})
        what, passages = str(change.get("what", "")), tuple(change.get("passages") or ())
        answer = memory.forget(what, passages, by="page", shown=_shown(change))
        # (what still holds it in other words, the messages a new conversation picks up included: one click each;
        # never looked for where the page shows no such list, "still": false, since its helper reads them all)
        if answer.get("ok") and not answer.get("file") and change.get("still", True) is not False:
            issues: set[str] = set()
            try:
                answer["still"] = memory.still_kept(what, passages, issues=issues)
            except life.Unreadable as e:
                issues.add(str(e))
                answer["still"] = []
            if warning := life.search_notice(issues, bool(answer["still"])):
                answer["warning"] = warning
    elif "undo" in want:
        answer = memory.undo(str(want["undo"] or ""), by="page")
    else:
        return no("Nothing to do.")
    if answer.get("maybe"):  # (written, not confirmed by the disk: the list shows whether it is there)
        return {**no(answer["why"]), "state": show()}
    if answer.get("conversation"):  # (an older conversation's look: its messages, then one click forgets them all)
        changed = "changed since" in answer.get("why", "")
        return {**no("That conversation changed since it was shown: here are its messages now." if changed else
                     "This older summary does not say which messages it was written from, so nothing is forgotten "
                     "yet: here they are."), "look": answer["look"], "all": answer["all"]}
    notice = {"warning": answer["warning"]} if answer.get("warning") else {}
    if not answer.get("ok"):
        return {**no(answer.get("why", "That could not be changed.")), **notice,
                **({"look": _for_page(answer["look"])} if "look" in answer else {})}
    return {"ok": True, "receipt": _receipt(answer), "state": show(), **notice}


if __name__ == "__main__":  # python -m settings.memory show | apply < JSON
    print(json.dumps(apply(json.load(sys.stdin)) if sys.argv[1:2] == ["apply"] else show(), ensure_ascii=False))
