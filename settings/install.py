"""What a choice still lacks, brought onto this Mac with one click: a photo or video model, a language model,
a provider's own command-line tool. One list, one quiet helper, true progress.

    python -m settings install ID     the helper the page starts (also ./vx install ID, to watch it in a
                                      terminal). It writes state/installs/ID.json as it goes; run again, it
                                      continues where it stopped.

Nothing half-done ever looks ready: a model counts as installed only when every file it needs is whole and
the program that runs it is there. Before anything is downloaded, this Mac's free space and memory are
checked, and a refusal says why in plain words.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from settings import catalog
from settings.store import ROOT, clean_env, private_open, private_write, state_file

CODE = Path(__file__).resolve().parents[1]
OFFLINE = os.environ.get("VX_SETTINGS_OFFLINE") == "1"  # tests: nothing is downloaded, nothing is run
MARGIN = 20e9  # bytes left free after an install (a full disk can corrupt things)
PASSED_ON = ("VX_SETTINGS_ROOT", "VX_SETTINGS_OFFLINE", "VX_STATE", "VX_MEDIA_HOME", "VX_SETTINGS_MEDIA", "VX_SETTINGS_MODELS",
             "VX_SETTINGS_NOT_INSTALLED", "VX_SETTINGS_FREE_GB", "VX_SOULFACE_PACKAGE", "VX_SOULFACE_SHA256", "VX_SETTINGS_INSTALL_FAILS", "VX_SETTINGS_INSTALL_STEP", "OLLAMA_MODELS")

# Photo and video models: main Viventium's qualified sources (viventium-media 0.1.3), at exact revisions.
#   bytes      the true download (Hugging Face, at that revision)        memory_gb  what one render holds
#   commands   the programs that must exist in its runtime               files      None: the whole repository
MEDIA = {
    "z-image-turbo": {"name": "Z-Image Turbo", "repo": "mflux-community/z-image-turbo-mflux-q8",
                      "revision": "4ccff28917346aa9daae49cd3c477cf5260a242c", "files": None, "bytes": 10.99e9,
                      "memory_gb": 17, "runtime": "mflux", "commands": ["mflux-generate-z-image-turbo"]},
    "qwen-image-2.1": {"name": "Qwen Image 2.1", "repo": "mflux-community/qwen-image-2-1-mflux-q8",
                       "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25", "files": None, "bytes": 18.46e9,
                       "memory_gb": 50, "runtime": "mflux", "commands": ["mflux-generate-qwen-2.1", "mflux-generate-qwen-2.1-edit"]},
    "minimax-h3": {"name": "MiniMax H3", "repo": "unsloth/MiniMax-H3-GGUF", "revision": "babc040eff0084465460ead58fdb8ec44296f8dd",
                   "files": ["minimax_h3_fl2va_pruned-Q5_0.gguf", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
                             "vae/minimax_h3_video_vae_fp16.safetensors", "vae/minimax_h3_audio_vae_fp32.safetensors"],
                   "bytes": 37.95e9, "memory_gb": 20, "runtime": "sdcpp", "commands": ["sd-cli"]},
}
# The programs that run them, installed once beside the weights (tools/media): MFLUX from PyPI at the qualified
# version; stable-diffusion.cpp built here for Apple's GPU at the qualified commit.
RUNTIMES = {"mflux": {"bytes": 1.2e9, "words": "Getting the picture tools"},
            "sdcpp": {"bytes": 0.3e9, "words": "Building the video tools", "commit": "f5df5f8",
                      "source": "https://github.com/leejet/stable-diffusion.cpp"}}
# Language models in Ollama's store (the true size of each, from its manifest).
MODELS = {
    "qwen3.6:latest": {"name": "Qwen 3.6", "bytes": 22.62e9, "memory_gb": 24},
    "qwen3:1.7b": {"name": "Qwen 3 1.7B", "bytes": 1_359_293_444, "memory_gb": 3},
}
# Add-ons: parts a person adds only if they want them, never part of Light itself (the requirement, for Soulface: it is
# heavy and extra, so someone who does not want it never has to download it or have it at all).
# One package each: a .tgz whose addon.json lists every file with its SHA-256; it lands in
# state/addons/ID, and the page serves only files that still match (call/ui/app/api/addons). Where the package comes from
# is the env line named here (a path on this Mac or an https address), and its own SHA-256 when it is given.
ADDONS = {"soulface": {"name": "Soulface", "bytes": 1.1e6, "package": "VX_SOULFACE_PACKAGE", "sha256": "VX_SOULFACE_SHA256"}}
# Each provider's native command-line tool, pinned and checked inside this project's tools/.
# Existing shared Claude/Codex installs are recorded and reused.
TOOLS = {
    "claude": {"name": "Claude Code", "run": ["python3", "{code}/core/downloads.py", "claude"]},
    "codex": {"name": "Codex", "run": ["python3", "{code}/core/downloads.py", "codex"]},
    "grok": {"name": "Grok Build", "run": ["/bin/bash", "-c", 'source "$1/vx" >/dev/null; WORKER_GROK_SIGN_IN=1; grok_harness', "sh", "{code}"]},
}


# -- Where things are --

def media_home() -> Path:
    """The folder that holds the media runtime (.venv, sdcpp) and the weights (models/)."""
    return Path(os.environ.get("VX_MEDIA_HOME") or CODE / "tools" / "media")


def whole(model: str, folder: Path) -> bool:
    """Every file the model needs is in this folder (the engine's own rule: each part's index and all its shards)."""
    if MEDIA[model]["files"]:
        return all((folder / name).is_file() for name in MEDIA[model]["files"])
    try:
        for part in ("text_encoder", "transformer", "vae"):
            shards = set(json.loads((folder / part / "model.safetensors.index.json").read_text())["weight_map"].values())
            if not shards or any(not (folder / part / shard).is_file() for shard in shards):
                return False
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return False
    return True


def _digest(path: Path, kind: str) -> str:
    """A file's SHA-256, or ("git") its git blob id, read in pieces."""
    made = hashlib.sha256() if kind == "sha256" else hashlib.sha1(b"blob %d\0" % path.stat().st_size)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            made.update(chunk)
    return made.hexdigest()


def needed(model: str, folder: Path) -> list[str]:
    """The files a model cannot run without (whole()'s rule): the ones it names, or each part's index and its shards."""
    if MEDIA[model]["files"]:
        return list(MEDIA[model]["files"])
    names = []
    for part in ("text_encoder", "transformer", "vae"):
        try:
            shards = json.loads((folder / part / "model.safetensors.index.json").read_text())["weight_map"].values()
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            shards = []
        names += [f"{part}/model.safetensors.index.json", *sorted({f"{part}/{shard}" for shard in shards})]
    return names


def checked(model: str, folder: Path) -> tuple[list[str], list[str]]:
    """Each file of a downloaded model against what Hugging Face recorded for it when it came at the model's own revision
    (its record, kept beside it: .cache/huggingface/download/<file>.metadata, its first line the revision, its second the
    etag: a large file's SHA-256, a small file's git blob id), read in full: (the files proven damaged or gone, the
    needed files that could not be checked). A file with no record, with a record of another revision (stale) or of
    another form is not judged: unknown, so never a reason to remove it, and a needed one is not proved whole. The
    downloader trusts its records on a retry and never reads a file again, so a damaged one is only ever fetched again
    once it is removed (media())."""
    revision, record = MEDIA[model]["revision"], folder / ".cache" / "huggingface" / "download"
    want = needed(model, folder)
    names = set(want) | ({m.relative_to(record).as_posix().removesuffix(".metadata") for m in record.rglob("*.metadata")}
                         if record.is_dir() else set())
    bad, unknown = [], []
    for name in sorted(names):
        try:
            lines = (record / f"{name}.metadata").read_text().splitlines()
        except OSError:
            lines = []
        etag = lines[1].strip().strip('"') if len(lines) > 1 else ""
        form = "sha256" if re.fullmatch(r"[0-9a-f]{64}", etag) else "git" if re.fullmatch(r"[0-9a-f]{40}", etag) else ""
        if not form or lines[0].strip() != revision:
            if name in want:
                unknown.append(name)
            continue
        file = folder / name
        if not file.is_file() or _digest(file, form) != etag:
            bad.append(name)
    return bad, unknown


def _proof(model: str) -> Path:
    return note(model).with_name(f"{note(model).stem}.proved.json")


def prove(model: str, folder: Path) -> None:
    """Keep that this folder's files were each proved whole at the model's revision, with what each was then (its size
    and change time), so the page knows it is installed without reading gigabytes again."""
    files = {name: [(folder / name).stat().st_size, (folder / name).stat().st_mtime_ns] for name in needed(model, folder)}
    private_write(_proof(model), json.dumps({"revision": MEDIA[model]["revision"], "folder": str(folder), "files": files}))


def proved(model: str) -> Path | None:
    """The folder of a model proved whole at its revision (prove()) and unchanged since; None: not proved."""
    try:
        kept = json.loads(_proof(model).read_text())
        folder, files = Path(kept["folder"]), kept["files"]
        if kept["revision"] != MEDIA[model]["revision"] or not files or set(files) != set(needed(model, folder)):
            return None
        for name, (size, changed) in files.items():
            seen = (folder / name).stat()
            if [seen.st_size, seen.st_mtime_ns] != [size, changed]:
                return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return folder


def whole_here(model: str) -> tuple[Path | None, list[str]]:
    """The weights already on this Mac (weights(): Light's own first, then main Viventium's), read in full against what
    Hugging Face recorded for them at the model's revision (checked()): (that folder when every needed file is proved
    whole, else None; Light's own files proved damaged). It only reads: removing a damaged file is media()'s, on a click."""
    found = weights(model)
    if found is None:
        return None, []
    bad, unknown = checked(model, found)
    own = found == media_home() / "models" / catalog.MEDIA_WEIGHTS[model]
    return (None if bad or unknown else found), (bad if own else [])


def recognize() -> list[str]:
    """At each start: the photo and video models already on this Mac, whole, that were never proved, proved now (the
    models it proved). Weights that came before proofs did were never called installed again (Z-Image was downloaded,
    and every Worker was then told nothing here makes pictures). Each is read exactly as a
    click on Install reads it (whole_here()); nothing is downloaded, built, removed or chosen, and a model with a file
    damaged, missing or not on record stays not installed, for that click to put right."""
    if OFFLINE:
        return []
    made = []
    for model in MEDIA:
        last = read(model)
        if proved(model) is not None or not runtime_ready(model) or weights(model) is None or \
                (last.get("state") == "running" and alive(last.get("pid"))):  # (an install of it is under way: its own)
            continue
        found, _ = whole_here(model)
        if found is not None:
            prove(model, found)
            made.append(model)
    return made


def weights(model: str) -> Path | None:
    """Where a model's whole weights are: Light's own folder first, then main Viventium's (read, never changed)."""
    bases = [media_home() / "models"] + [Path(base).expanduser() for base in catalog.MEDIA_MODELS if base.startswith("~")]
    return next((base / catalog.MEDIA_WEIGHTS[model] for base in bases if whole(model, base / catalog.MEDIA_WEIGHTS[model])), None)


def runtime_bin(model: str) -> Path:
    return media_home() / (".venv/bin" if MEDIA[model]["runtime"] == "mflux" else "sdcpp")


def runtime_ready(model: str) -> bool:
    there = all(os.access(runtime_bin(model) / command, os.X_OK) for command in MEDIA[model]["commands"])
    return there and (MEDIA[model]["runtime"] != "sdcpp" or bool(shutil.which("ffmpeg") and shutil.which("ffprobe")))


def starts(model: str) -> bool:
    """The program really starts (asked for its own help text). Only the installer asks: it takes a few seconds."""
    try:
        return subprocess.run([str(runtime_bin(model) / MEDIA[model]["commands"][0]), "--help"], env=clean_env(), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def media_ready(model: str) -> bool:
    """Installed: its program here, and its weights proved whole at its revision (checked(), kept by prove())."""
    if OFFLINE:
        return model in os.environ.get("VX_SETTINGS_MEDIA", "").split() or done(model)
    return proved(model) is not None and runtime_ready(model)


def tool_ready(name: str) -> bool:
    """Whether a provider's own command-line tool is on this Mac."""
    if OFFLINE:  # (tests say what is missing in the environment, or in a file so it can change while the page is open)
        missing = os.environ.get("VX_SETTINGS_NOT_INSTALLED", "").split() + ((ROOT / "logs" / "not-installed").read_text().split()
                                                                           if (ROOT / "logs" / "not-installed").exists() else [])
        return name not in missing or done(name)
    return bool(tool_path(name))


def tool_path(name: str) -> str:
    """Where a provider's command-line tool is: on the PATH, in this project's own tools/, or its installer's own place."""
    command = catalog.SIGN_INS[name]["check"][0]
    if name in ("claude", "codex"):
        from core.downloads import harness_ready, shared_tool
        shared = shared_tool(name)
        return shared or (str(CODE / "tools/harnesses/bin" / name) if harness_ready(name) else "")
    if name == "grok":
        import platform
        binary = CODE / "tools/grok-build/grok"
        expected = json.loads((CODE / "tools/grok-build-pin.json").read_text())["sha256"][platform.machine()]
        return str(binary) if binary.is_file() and not binary.is_symlink() and _digest(binary, "sha256") == expected else ""
    places = [ROOT / "tools" / "node_modules" / ".bin" / command] + ([Path(TOOLS[name]["home"]).expanduser()] if TOOLS.get(name, {}).get("home") else [])
    return shutil.which(command) or next((str(place) for place in places if os.access(place, os.X_OK)), "")


def local_models() -> set[str]:
    """The models in Ollama's store on this Mac, as name:tag."""
    if OFFLINE:
        return set(os.environ.get("VX_SETTINGS_MODELS", "qwen3.6:latest").split()) | {m for m in MODELS if done(m)}
    store = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models") / "manifests" / "registry.ollama.ai" / "library"
    return {f"{model.name}:{tag.name}" for model in store.glob("*") if model.is_dir() for tag in model.glob("*")}


def kind(item: str) -> str:
    return "media" if item in MEDIA else "tool" if item in TOOLS else "addon" if item in ADDONS else "model" if re.fullmatch(r"[a-z0-9._\-]+:[a-z0-9._\-]+", item or "") else ""


def installed(item: str) -> bool:
    return {"media": media_ready, "tool": tool_ready, "addon": addon_ready, "model": lambda m: m in local_models()}[kind(item)](item)


def name(item: str) -> str:
    return (MEDIA.get(item) or TOOLS.get(item) or MODELS.get(item) or ADDONS.get(item) or {"name": item})["name"]


def size(item: str) -> float:
    """What is still to download, in bytes (the weights, plus the program that runs them when it is not here yet)."""
    if item in MEDIA:
        spec = MEDIA[item]
        return (0 if not OFFLINE and weights(item) else spec["bytes"]) + (0 if not OFFLINE and runtime_ready(item) else RUNTIMES[spec["runtime"]]["bytes"])
    return (MODELS.get(item) or ADDONS.get(item) or {}).get("bytes", 0)


# -- Add-ons --

def addons_home() -> Path:
    return state_file().parent / "addons"


def addon_manifest(item: str) -> dict:
    """The installed add-on's own list (addon.json), or {} when it is not here or does not read."""
    try:
        manifest = json.loads((addons_home() / item / "addon.json").read_text())
        return manifest if isinstance(manifest, dict) and manifest.get("id") == item else {}
    except (OSError, ValueError):
        return {}


def addon_ready(item: str) -> bool:
    """Here and whole: its manifest names its entry, and every file it lists is there with that SHA-256."""
    manifest, folder = addon_manifest(item), addons_home() / item
    files = manifest.get("files") or {}
    if not manifest.get("entry") or manifest["entry"] not in files:
        return False
    for rel, digest in files.items():
        path = (folder / rel).resolve()
        if folder.resolve() not in path.parents or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


ADDON_MOST = 50e6  # bytes a package may be, and 4x that unpacked (Soulface is about 0.3 MB packed, 1.1 MB unpacked)


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to another https address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).startswith("https://"):
            raise Stop("The download tried to move to an address that is not https, so nothing was installed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def addon_source(item: str) -> str:
    return os.environ.get(ADDONS[item]["package"], "").strip()


def addon(item: str) -> None:
    """Fetch the package, check it, unpack it beside the old one, check every file, then put it in place at once."""
    source, want = addon_source(item), os.environ.get(ADDONS[item]["sha256"], "").strip().lower()
    if not source:
        raise Stop(f"{name(item)} is not available to download yet.")
    home = addons_home()
    home.mkdir(parents=True, exist_ok=True)
    package = home / f".{item}.tgz"
    say(item, 10, f"Getting {name(item)}")
    if source.startswith("https://"):
        # From the internet, only what matches a fingerprint given beside the address (VX_SOULFACE_SHA256): the files'
        # own list (addon.json) vouches only for itself, so it cannot be what proves where a download came from.
        if not want:
            raise Stop(f"{name(item)}'s download has no fingerprint to check it against, so nothing was installed.")
        opener = urllib.request.build_opener(_HttpsOnly)
        with opener.open(source, timeout=60) as reply, open(package, "wb") as out:
            got = 0
            while chunk := reply.read(1 << 16):
                got += len(chunk)
                if got > ADDON_MOST:
                    raise Stop(f"{name(item)}'s download is far larger than it should be, so nothing was installed.")
                out.write(chunk)
    elif source.startswith(("http:", "file:", "ftp:")) or "://" in source:
        raise Stop(f"{name(item)} can only come from this Mac or an https address.")
    else:
        local = Path(source).expanduser()
        if not local.is_file():
            raise Stop(f"{name(item)}'s package is not where it should be on this Mac.")
        shutil.copyfile(local, package)
        sidecar = Path(f"{local}.sha256")
        if not want and sidecar.is_file():
            want = sidecar.read_text().split()[0].lower()
    if want and hashlib.sha256(package.read_bytes()).hexdigest() != want:
        package.unlink(missing_ok=True)
        raise Stop(f"{name(item)}'s package did not match its fingerprint, so nothing was installed.")
    say(item, 50, f"Checking {name(item)}")
    fresh = home / f".{item}.new"
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir()
    import tarfile
    with tarfile.open(package) as tar:
        if sum(m.size for m in tar.getmembers()) > 4 * ADDON_MOST:
            shutil.rmtree(fresh, ignore_errors=True)
            raise Stop(f"{name(item)}'s package unpacks far larger than it should, so nothing was installed.")
        tar.extractall(fresh, filter="data")  # (no path leaves the folder, no links out, no special files)
    package.unlink(missing_ok=True)
    try:
        manifest = json.loads((fresh / "addon.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    if manifest.get("id") != item:
        shutil.rmtree(fresh, ignore_errors=True)
        raise Stop(f"That package is not {name(item)}.")
    old = home / f".{item}.old"
    shutil.rmtree(old, ignore_errors=True)
    if (home / item).exists():
        os.replace(home / item, old)
    os.replace(fresh, home / item)
    if not addon_ready(item):
        shutil.rmtree(home / item, ignore_errors=True)
        if old.exists():
            os.replace(old, home / item)
        raise Stop(f"{name(item)}'s files did not match their fingerprints, so nothing was changed.")
    shutil.rmtree(old, ignore_errors=True)
    say(item, 100, "Installed")


# -- How an install is doing (one small file each, in her state) --

def note(item: str) -> Path:
    return state_file().parent / "installs" / (re.sub(r"[^A-Za-z0-9.\-]", "_", item) + ".json")


def read(item: str) -> dict:
    try:
        return json.loads(note(item).read_text())
    except (OSError, ValueError):
        return {}


def write(item: str, **fields) -> None:
    path = note(item)
    tmp = path.with_suffix(f".{os.getpid()}-{threading.get_ident()}.tmp")
    private_write(tmp, json.dumps({"id": item, "pid": os.getpid(), "at": time.time(), **fields}))
    os.replace(tmp, path)


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def done(item: str) -> bool:
    return read(item).get("state") == "done"


def status(item: str) -> dict | None:
    """What the page shows for something that is not here yet: its size, and how getting it is going
    (state "" before a first click, "running" with a percent and a few words, or "failed" with why)."""
    if not kind(item) or installed(item):
        return None
    last = read(item)
    out = {"id": item, "name": name(item), "size_gb": round(size(item) / 1e9), "size_mb": round(size(item) / 1e6, 1),
           "state": "", "percent": 0, "words": "", "error": ""}
    if last.get("state") == "running" and not alive(last.get("pid")):
        last = {"state": "failed", "error": "It stopped before it finished. Try again: it continues where it left off."}
    if last.get("state") in ("running", "failed"):
        out.update({k: last[k] for k in ("state", "percent", "words", "error") if k in last})
    return out


def running() -> bool:
    folder = state_file().parent / "installs"
    return any(row.get("state") == "running" and alive(row.get("pid"))
               for row in (read(path.stem) for path in folder.glob("*.json"))) if folder.is_dir() else False


# -- Starting one --

def free_bytes() -> float:
    if os.environ.get("VX_SETTINGS_FREE_GB"):
        return float(os.environ["VX_SETTINGS_FREE_GB"]) * 1e9
    target = media_home() if media_home().exists() else media_home().parent
    return shutil.disk_usage(target if target.exists() else Path.home()).free


def refuse(item: str) -> str:
    """"" when this Mac can take it, else why not, in plain words."""
    if item in ADDONS:  # (about a megabyte: no memory or space to weigh; where it comes from is checked when it is fetched)
        return ""
    need = (MEDIA.get(item) or MODELS.get(item) or {}).get("memory_gb", 0)
    if need and not OFFLINE:
        have = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0) / 2**30
        if have and have < need + 8:  # (it runs beside everything else that is open)
            return f"{name(item)} needs about {need} GB of memory while it works, and this Mac has {have:.0f} GB."
    present = 0
    if item in MEDIA and not OFFLINE:
        folder = media_home() / "models" / catalog.MEDIA_WEIGHTS[item]
        present = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0
    more, free = max(0, size(item) - present), free_bytes()
    if more + MARGIN > free:
        return (f"Not enough free space: {name(item)} is {more / 1e9:.0f} GB, and Viventium keeps {MARGIN / 1e9:.0f} GB free so this "
                f"Mac stays healthy. It has {free / 1e9:.0f} GB free.")
    return ""


def start(item: str) -> str:
    """Begin installing (a quiet helper of its own; it outlives the page). Returns "" or why not."""
    if not kind(item) or (kind(item) == "model" and item not in {o.get("local_model") for part in catalog.PARTS.values() for o in part["options"]}):
        return "That cannot be installed from here."
    last = read(item)
    if installed(item) or (last.get("state") == "running" and alive(last.get("pid"))):
        return ""
    if why := refuse(item):
        return why
    logs = ROOT / "logs"
    env = {**clean_env(), **{k: os.environ[k] for k in PASSED_ON if k in os.environ}}
    write(item, state="running", percent=0, words="Starting")  # (with this process's pid, until the helper writes its own)
    with private_open(logs / f"install-{note(item).stem}.log") as log:
        child = subprocess.Popen([sys.executable, "-m", "settings", "install", item], cwd=CODE, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    if read(item).get("pid") == os.getpid():
        write(item, state="running", percent=0, words="Starting", pid=child.pid)
    return ""


# -- The helper --

class Stop(Exception):
    """An install that cannot go on, with the plain reason (the page shows it: never a path or a command)."""


def missing(tool: str) -> Stop:
    """A program the install needs is not on this Mac: its name goes to the install's own log, plain words to the page."""
    print(f"missing on this Mac: {tool}", flush=True)
    return Stop("A tool this needs is missing from this Mac, so nothing was installed.")


def say(item: str, percent: float, words: str) -> None:
    write(item, state="running", percent=round(percent), words=words)
    print(f"{percent:3.0f}%  {words}", flush=True)


def run_step(command: list[str], why: str, **more) -> None:
    done_ = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **more)
    if done_.returncode:
        print(done_.stdout[-3000:], flush=True)
        raise Stop(why)


def media_runtime(item: str) -> None:
    """The program that runs a media model, installed once beside the weights."""
    home, kind_ = media_home(), MEDIA[item]["runtime"]
    if not shutil.which("uv"):
        raise missing("uv")
    home.mkdir(parents=True, exist_ok=True)
    if not (home / ".venv" / "bin" / "python").exists():
        run_step(["uv", "venv", "-q", "--python", "3.12", str(home / ".venv")], "Python for the picture tools could not be set up.")
    if kind_ == "mflux" or not (home / ".venv" / "bin" / "hf").exists():  # (hf, the downloader, comes with MFLUX)
        run_step(["uv", "pip", "install", "-q", "--python", str(home / ".venv" / "bin" / "python"), "-r", str(CODE / "tools" / "media" / "requirements.txt")],
                 "The picture tools could not be downloaded. Is this Mac online?")
    if kind_ == "sdcpp" and not runtime_ready(item):
        spec, source = RUNTIMES["sdcpp"], home / "sdcpp-source"
        for tool in ("git", "ffmpeg", "ffprobe", "cc"):
            if not shutil.which(tool):
                raise missing(tool)
        run_step(["uv", "pip", "install", "-q", "--python", str(home / ".venv" / "bin" / "python"), "cmake"], "The build tool could not be downloaded.")
        cmake = str(home / ".venv" / "bin" / "cmake")
        if not (source / ".git").exists():
            run_step(["git", "clone", "-q", spec["source"], str(source)], "The video program's source could not be downloaded.")
        run_step(["git", "-C", str(source), "checkout", "-q", spec["commit"]], "The video program's qualified version was not found.")
        run_step(["git", "-C", str(source), "submodule", "update", "-q", "--init", "--recursive"], "The video program's source is incomplete.")
        run_step([cmake, "-S", str(source), "-B", str(source / "build"), "-DSD_METAL=ON", "-DCMAKE_BUILD_TYPE=Release"], "The video program could not be prepared.")
        run_step([cmake, "--build", str(source / "build"), "--config", "Release", "-j", "8"], "The video program did not build on this Mac.")
        (home / "sdcpp").mkdir(exist_ok=True)
        for built in (source / "build" / "bin").iterdir():  # the one program the video model runs (and any library beside it)
            if built.is_file() and (built.name in MEDIA[item]["commands"] or built.suffix == ".dylib"):
                shutil.copy2(built, home / "sdcpp" / built.name)
        shutil.rmtree(source, ignore_errors=True)
    if not runtime_ready(item) or not starts(item):
        raise Stop("The tools were installed but do not start, so it is not ready. Try again.")  # (why: its install log)


def media(item: str) -> None:
    spec, folder = MEDIA[item], media_home() / "models" / catalog.MEDIA_WEIGHTS[item]
    if not runtime_ready(item) or not starts(item):  # (there but not starting: put right the same way)
        say(item, 1, RUNTIMES[spec["runtime"]]["words"])
        media_runtime(item)
    if weights(item) is not None:  # (whole-looking weights already here, Light's own or main Viventium's: proved before used)
        say(item, 2, "Checking the files already here")
    found, damaged = whole_here(item)  # (main Viventium's are only read: when they fail, Light gets its own)
    for name in damaged:  # (Light's own: a file proved damaged goes now, so this download fetches it again)
        (folder / name).unlink(missing_ok=True)
    if found is None:
        folder.mkdir(parents=True, exist_ok=True)
        total, stop = spec["bytes"], threading.Event()

        def watch() -> None:  # true progress: what is on disk, against what the whole download weighs
            while not stop.wait(1.5):
                have = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
                say(item, min(98, 2 + 96 * have / total), f"Downloading · {have / 1e9:.1f} of {total / 1e9:.0f} GB")
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:  # the documented way: the Hugging Face downloader, an exact revision, into the model's own folder
            run_step([str(media_home() / ".venv" / "bin" / "hf"), "download", spec["repo"], *(spec["files"] or []), "--revision", spec["revision"],
                      "--local-dir", str(folder)], "The download stopped. Is this Mac online? Try again: it continues where it left off.",
                     env={**clean_env(), "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        finally:
            stop.set()
            watcher.join(5)
        say(item, 99, "Checking every file")
        bad, unknown = checked(item, folder)
        if bad:  # (proved damaged against what Hugging Face recorded at this revision: removed, so a retry fetches them)
            for name in bad:
                (folder / name).unlink(missing_ok=True)
            raise Stop(f"{len(bad)} file(s) did not arrive whole and were removed. Try again: only those are fetched again.")
        if unknown:  # (nothing to judge them by: kept as they are, and the model is not called installed)
            raise Stop("Some files could not be checked against what Hugging Face recorded for them. Try again.")
        found = folder
    prove(item, found)
    if not media_ready(item):
        raise Stop("Some files are missing after the download. Try again.")
    # Installed to be used: it becomes the choice for its kind (the page ticks it; a Worker is told how to run it).
    from settings import service
    for kind_, part in catalog.MEDIA.items():
        for option in part["options"]:
            if option.get("local_media") == item:
                service.keep_media(kind_, option)


def port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def model(item: str) -> None:
    """A language model, pulled through one of Light's own Ollama servers (never another program's)."""
    port = next((p for p in (11437, 11435, 11436) if port_open(p)), None)
    server = None
    if port is None:  # none of hers is up: a short-lived one of her own, for the download only
        ollama = sorted((Path.home() / ".cache" / "viventium-light").glob("ollama-*/ollama"))
        if not ollama:
            raise Stop("Ollama, which runs models on this Mac, is not set up yet, so nothing was downloaded.")
        port = 11438
        server = subprocess.Popen([str(ollama[-1]), "serve"], env={**clean_env(), "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_NOPRUNE": "1"},
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            if port_open(port):
                break
            time.sleep(0.5)
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/pull", data=json.dumps({"model": item, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"})
        layers: dict[str, tuple[int, int]] = {}
        with urllib.request.urlopen(request, timeout=3600) as reply:
            for line in reply:
                row = json.loads(line or b"{}")
                if row.get("error"):
                    raise Stop("The download stopped. Is this Mac online? Try again: it continues where it left off.")
                if row.get("digest") and row.get("total"):
                    layers[row["digest"]] = (row.get("completed", 0), row["total"])
                    have, total = sum(a for a, _ in layers.values()), sum(b for _, b in layers.values())
                    say(item, min(98, 98 * have / total), f"Downloading · {have / 1e9:.1f} of {total / 1e9:.0f} GB")
    except OSError as error:
        raise Stop("The download stopped. Is this Mac online? Try again: it continues where it left off.") from error
    finally:
        if server:
            server.terminate()
    if item not in local_models():
        raise Stop("The model did not arrive whole. Try again.")


def tool(item: str) -> None:
    say(item, 10, f"Getting {name(item)}")
    command = [part.replace("{tools}", str(ROOT / "tools")).replace("{code}", str(CODE)) for part in TOOLS[item]["run"]]
    run_step(command, f"{name(item)} could not be verified. Try again.", env=clean_env(), cwd=ROOT)
    home, linked = TOOLS[item].get("home"), ROOT / "tools" / "node_modules" / ".bin" / catalog.SIGN_INS[item]["check"][0]
    if home and Path(home).expanduser().exists() and not linked.exists():  # where this project's PATH finds it at once
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(Path(home).expanduser())
    if not tool_ready(item):
        raise Stop(f"{name(item)} was installed, but Viventium cannot find it yet. Turn Viventium off and open it again.")


def pretend(item: str) -> None:
    """Tests: the same states the page sees, with nothing downloaded."""
    step = float(os.environ.get("VX_SETTINGS_INSTALL_STEP", "0.5"))
    for percent in (5, 40, 80):
        say(item, percent, f"Downloading · {percent / 100 * size(item) / 1e9:.1f} of {size(item) / 1e9:.0f} GB" if size(item) else f"Getting {name(item)}")
        time.sleep(step)
    if item in os.environ.get("VX_SETTINGS_INSTALL_FAILS", "").split():
        raise Stop("The download stopped. Is this Mac online? Try again: it continues where it left off.")
    if item in MEDIA:
        from settings import service
        for kind_, part in catalog.MEDIA.items():
            for option in part["options"]:
                if option.get("local_media") == item:
                    service.keep_media(kind_, option)


def run(item: str) -> int:
    """The helper itself: one install from start to end, its state kept as it goes."""
    if not kind(item):
        print("That cannot be installed from here.")
        return 2
    try:
        if not installed(item) or (item in MEDIA and not OFFLINE):  # (a media model is checked through, and put right, every time)
            if why := refuse(item):
                raise Stop(why)
            say(item, 0, "Starting")
            (pretend if OFFLINE and kind(item) != "addon" else {"media": media, "model": model, "tool": tool, "addon": addon}[kind(item)])(item)
        write(item, state="done", percent=100, words="Installed")
        print(f"{name(item)} is installed.", flush=True)
        return 0
    except Stop as stop:
        write(item, state="failed", percent=read(item).get("percent", 0), error=str(stop))
        print(str(stop), flush=True)
        return 1
    except Exception as error:  # (anything unforeseen is still said, never left looking as if it were running)
        write(item, state="failed", percent=read(item).get("percent", 0), error="It stopped on an error. Try again.")
        print(f"{type(error).__name__}: {error}", flush=True)
        return 1
