"""Make a picture or a short video with a model on this Mac. A Worker of any kind runs this from its shell.

    tools/media/make MODEL "what it should show" [--from PICTURE] [--size 1024x1024] [--seconds 6] [--seed N]

    MODEL      z-image-turbo (fast, from words) | qwen-image-2.1 (detailed; changes a picture) | minimax-h3 (video)
    --from     a picture to change (qwen-image-2.1) or to start a video from
    --seconds  a video's length: 2 (the default) or 6
    --seed     the same number and words make the same picture again; without it, each one is new

It prints the new file's full path and nothing else. The file lands in ./artifacts of the folder it is run
from. One at a time: a second request waits for the first. The engine is main Viventium's own
(viventium_media, see UPSTREAM.md); what is installed, and where, is settings/install.py's to say.
"""
import argparse
import asyncio
import fcntl
import secrets
import shutil
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]
from settings import install  # noqa: E402
from viventium_media import video  # noqa: E402
from viventium_media.engine import MediaError, Model, Settings, Workspace, render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Make a picture or a short video on this Mac.")
    parser.add_argument("model", choices=list(install.MEDIA))
    parser.add_argument("prompt")
    parser.add_argument("--from", dest="source", type=Path)
    parser.add_argument("--size", default="")
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--seed", type=int, default=None)  # (a fixed one made every "another selfie" the same picture)
    args = parser.parse_args()
    spec, is_video = install.MEDIA[args.model], args.model == video.MODEL
    if not install.media_ready(args.model):
        print(f"{spec['name']} is not installed yet. It is one click in Settings, under Photos and videos.", file=sys.stderr)
        return 1
    try:
        width, height = (int(n) for n in (args.size or ("384x256" if is_video else "1024x1024")).lower().split("x"))
    except ValueError:
        print("A size looks like 1024x1024.", file=sys.stderr)
        return 1
    if args.source and not is_video and len(spec["commands"]) == 1:  # said plainly, with the way out
        print(f"{spec['name']} makes pictures from words only. To change an existing picture, choose Qwen Image 2.1 "
              "in Settings, under Photos and videos.", file=sys.stderr)
        return 1
    workspace = Workspace.open(Path.cwd())
    reference = None
    if args.source:  # the engine reads a picture from the folder it works in: one from elsewhere is copied in
        source = args.source.expanduser().resolve()
        if not source.is_file():
            print(f"There is no picture at {source}.", file=sys.stderr)
            return 1
        if not source.is_relative_to(workspace.root):
            source = Path(shutil.copy(source, workspace.artifacts() / f"from-{source.name}"))
        reference = str(source.relative_to(workspace.root))
    ffmpeg = shutil.which("ffmpeg")
    # The weights are the folder their proof names (install.proved), never found again from "~": a Worker's shell has a
    # home of its own, where main Viventium's folder is not (Qwen Image 2.1 was "unavailable" to every Worker).
    weights = install.proved(args.model) or install.weights(args.model)
    settings = Settings(install.media_home() / "models" / "media.toml", {args.model: Model(install.runtime_bin(args.model), weights)},
                        1800, Path(ffmpeg) if ffmpeg else Path("/unavailable/ffmpeg"))
    settings.file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (settings.file.parent / "make.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)  # one at a time: the next one waits here for its turn
            made = asyncio.run(until_stopped(render(settings, workspace, args.model, args.prompt, width=width, height=height,
                                                    seed=args.seed if args.seed is not None and args.seed >= 0 else secrets.randbelow(2 ** 31),
                                                    reference=reference, frames=141 if args.seconds > 3 else 56)))
    except MediaError as error:
        print(str(error), file=sys.stderr)
        return 1
    except asyncio.CancelledError:
        print("Stopped before it was finished: nothing was made.", file=sys.stderr)
        return 130
    print((workspace.root / made.path).resolve())
    return 0


async def until_stopped(work):
    """The render, cancelled when this command is asked to stop (SIGTERM or SIGHUP, as when a Worker's job is stopped),
    so the engine ends the model's own process and removes its half-made files. The model runs in a session of its own,
    which a stop of this command alone never reached (a stopped Qwen render kept running, holding its memory)."""
    task = asyncio.ensure_future(work)
    loop = asyncio.get_running_loop()
    for stop in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(stop, task.cancel)
    return await task


if __name__ == "__main__":
    raise SystemExit(main())
