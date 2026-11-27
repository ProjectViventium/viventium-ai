"""What a Worker is told about making pictures and videos (brain/worker.md, {media}): the tools this Worker can use now.

It comes from what can run, never from a saved choice alone (Z-Image was installed, no choice had been
saved, the brief named nothing, and a Worker spent 26 minutes on a website's image maker):
  - a model installed on this Mac (settings/install.media_ready: its weights whole, its program there): any Worker runs
    it from its shell with tools/media/make;
  - ChatGPT Images: the image tool of a Codex Worker on its ChatGPT sign-in, so only a job going to such a Worker online
    hears of it (its route was chosen from the sign-ins that work: no CLI is asked here). A job on this Mac's model
    never hears of a tool online.
The choice on the settings page (Photos and videos) is honoured where it can run for this job; otherwise every tool this
job can use is offered, the page's own order first. Built for each job once its Worker is known (in the launch, never
before her words).
"""
import shlex
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAKE = HERE / "make"
WHAT = {"photos": ("picture", "what it should show"), "videos": ("short video", "what happens in it")}


def _saved(place: str | None) -> dict:
    """The page's choice per kind for this place: on this Mac its local model ("media_local", a model's id, matched to
    its option), online and on the page itself the option chosen ("media"). Kept apart, so an online choice never
    decides a job on this Mac. (The page saves one choice today, not one per profile.)"""
    from core.state import setting
    if place == "mac":
        local = setting("media_local") or {}
        if not isinstance(local, dict):
            return {}
        from settings import catalog
        return {kind: next((o["id"] for o in spec["options"] if o.get("local_media") and o["local_media"] == local.get(kind)), "")
                for kind, spec in catalog.MEDIA.items()}
    saved = setting("media") or {}
    return saved if isinstance(saved, dict) else {}


def place_of(worker: str = "") -> str:
    """Where a job's Worker runs: "mac" (this Mac's model) or "online" (a signed-in Worker)."""
    import os
    if os.environ.get("WORKERS") != "signed-in":
        return "mac"
    try:
        from brain import xperfect
        return "mac" if xperfect.goes_local(worker) else "online"
    except Exception:  # noqa: BLE001 (no mix declared: the signed-in Workers)
        return "online"


def usable(place: str | None, worker: str) -> dict[str, list[dict]]:
    """Per kind (photos, videos), the options this job's Worker can use now, in the page's order. `place` None: what the
    settings page shows as able to run (no job yet)."""
    from settings import catalog, install, service
    out = {}
    for kind, spec in catalog.MEDIA.items():
        out[kind] = []
        for option in spec["options"]:
            if place is None:
                ready = not service.needs(kind, option, {})
            elif option.get("local_media"):
                ready = install.media_ready(option["local_media"])
            elif option.get("harness"):  # (a Worker's own tool: only for a job going to that Worker online, whose route
                ready = place == "online" and worker == option["harness"]  # was chosen from its working sign-ins)
            else:
                ready = False
            if ready:
                out[kind].append(option)
    return out


def offered(place: str | None, worker: str) -> dict[str, tuple[list[dict], str]]:
    """Per kind: the options this job is told about, and the page's choice among them ("" when it cannot run here)."""
    saved, out = _saved(place), {}
    for kind, options in usable(place, worker).items():
        chosen = next((o for o in options if o["id"] == saved.get(kind)), None)
        out[kind] = ([chosen], chosen["id"]) if chosen else (options, "")
    return out


def _words(option: dict) -> str:
    return ", ".join(word[0].lower() + word[1:] for word in option.get("words", []))


def _line(kind: str, option: dict) -> str:
    from settings import install
    name = f"{option['provider']} {option['model']}"
    if option.get("local_media"):
        model = option["local_media"]
        what, words = WHAT[kind]
        start = (" (add --from and a picture's full path to change that picture)" if len(install.MEDIA[model]["commands"]) > 1
                 else " (add --from and a picture's full path to start from it)" if kind == "videos" else "")
        return f'{name} ({_words(option)}): {shlex.quote(str(MAKE))} {model} "{words}"{start}'
    return f"{name} ({_words(option)}): your own image tool, on their ChatGPT sign-in"


def missed(place: str | None, worker: str) -> list[str]:
    """The page's choices of a model on this Mac that cannot run for this job (not ready), by name. Said in the brief, so
    another tool never takes their place unsaid (with Z-Image chosen and not ready, a Codex job was offered
    ChatGPT Images alone, with no word of why: found in the code). A Worker's own tool online is never named to a job
    going to another Worker (as usable() keeps it from them)."""
    from settings import catalog
    saved, can, out = _saved(place), usable(place, worker), []
    for kind, spec in catalog.MEDIA.items():
        if saved.get(kind) and all(o["id"] != saved[kind] for o in can.get(kind, [])):
            out += [f"{o['provider']} {o['model']}" for o in spec["options"] if o["id"] == saved[kind] and o.get("local_media")]
    return out


def brief(place: str | None = None, worker: str = "") -> str:
    """This job's part of its brief about pictures and videos: each tool its Worker can use now, and how. `place` is
    "mac" or "online" and `worker` the job's harness; without a job (place None), what the settings page shows."""
    tools, chosen = [], []
    for kind, (options, choice) in offered(place, worker).items():
        tools += [_line(kind, option) for option in options]
        if choice:
            chosen.append(f"{kind}: {options[0]['provider']} {options[0]['model']}")
    gone = " and ".join(missed(place, worker)) if place else ""
    if not tools:
        return ("Nothing here makes pictures or videos yet." + (f" Their choice, {gone}, is not ready here." if gone else "") +
                " If they ask for one, say so in a sentence: Z-Image Turbo, which makes pictures on this Mac, installs with "
                "one click in Settings, under Photos and videos.")
    out = "Pictures and videos: make them for real, as files, with these" + (" (the user's choice, " + "; ".join(chosen) + ")"
                                                                            if chosen else "") + ":\n- " + "\n- ".join(tools)
    if any("tools/media/make" in line for line in tools):
        out += ("\nThe ones on this Mac run from your shell, in your workspace, privately and boundless; each prints the new "
                "file's full path when it is done (a picture takes under a minute, a video several), one at a time.")
    if gone:
        out += (f"\nTheir choice, {gone}, cannot run for this job. If you use one of these instead, say which in your "
                "result, and that their choice was not available.")
    return out + "\nUse one of these, not another image or video tool or website."
