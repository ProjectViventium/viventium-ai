"""The few downloads outside package locks. Check bytes before publishing or executing them."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "core/downloads.json").read_text())


def home():
    return Path(os.environ.get("VX_STATE") or ROOT / "state") / "downloads"


def digest(path, kind="sha256"):
    made = hashlib.sha1(b"blob %d\0" % path.stat().st_size) if kind == "git" else hashlib.new(kind)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 << 20), b""):
            made.update(chunk)
    return made.hexdigest()


def matches(path, spec):
    try:
        return (any(k in spec for k in ("sha256", "sha512", "git")) and path.is_file() and not path.is_symlink()
                and ("size" not in spec or path.stat().st_size == spec["size"])
                and all(digest(path, k) == spec[k] for k in ("sha256", "sha512", "git") if k in spec))
    except OSError:
        return False


def shared_caches():
    """Read existing HF caches only. Keep the old location before vx sets its private cache."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    hf = Path(os.environ.get("HF_HOME") or base / "huggingface")
    paths = [os.environ.get(key) for key in ("VX_SHARED_HF_CACHE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE",
                                             "TRANSFORMERS_CACHE")]
    paths.extend((hf / "hub", base / "huggingface/hub"))
    private = (home() / "hub").resolve()
    return list(dict.fromkeys(Path(p).expanduser().resolve() for p in paths if p and Path(p).resolve() != private))


def shared_file(spec, name, proof):
    """A name or revision is only a search hint; size and every digest are the verdict."""
    seen = set()
    for root in shared_caches():
        cache = root / ("models--" + spec["repo"].replace("/", "--"))
        candidates = [cache / "snapshots" / spec["revision"] / name]
        candidates.extend(sorted((cache / "snapshots").glob("*/" + name)))
        candidates.extend(cache / "blobs" / proof[k] for k in ("sha256", "git") if k in proof)
        candidates.extend(sorted((cache / "blobs").glob("*")))
        for candidate in candidates:
            try:
                source = candidate.resolve(strict=True)
                if source in seen or not source.is_relative_to(root):
                    continue
                seen.add(source)
                if matches(source, proof):
                    return source
            except OSError:
                continue
    return None


def seed(path, source, proof):
    """Publish independent verified bytes, with a hard link if cloning is unavailable. Never edit the source."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".seed-", dir=path.parent) as temp:
        pending = Path(temp) / "file"
        cloned = False
        if sys.platform == "darwin":
            cloned = subprocess.run(["/bin/cp", "-c", str(source), str(pending)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not cloned:
            pending.unlink(missing_ok=True)
            try:
                os.link(source, pending)
            except OSError:
                shutil.copyfile(source, pending)
        if not matches(pending, proof):
            return False  # The shared file changed during the transfer; fetch a verified replacement instead.
        os.replace(pending, path)
    return True


def upgrade_report():
    """Read-only, network-free plan for an empty private cache. No refs, locks or receipts are written."""
    report = []
    for key, spec in MANIFEST["hf"].items():
        for name, proof in spec["files"].items():
            source = shared_file(spec, name, proof)
            report.append({"part": key, "file": name, "size": proof["size"],
                           "action": "seed" if source else "download"})
    return {"files": report, "download_bytes": sum(f["size"] for f in report if f["action"] == "download"),
            "seed_bytes": sum(f["size"] for f in report if f["action"] == "seed")}


def voice_status(value=None):
    path = home() / "voice.json"
    if value is None:
        try:
            return json.loads(path.read_text())["status"]
        except (OSError, ValueError, KeyError):
            return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps({"status": value}))
    os.replace(temporary, path)


def voice_notice():
    if "mlx_local" not in (os.environ.get("TTS", ""), os.environ.get("TTS_FALLBACK", "")):
        return ""
    status = voice_status()
    if status == "failed":
        return "The local voice download paused. The backup voice is available. Restart Viventium to retry."
    if status == "preparing":
        return "The local voice is getting ready. The backup voice is available. You can keep talking or typing."
    if status == "downloading":
        return "The local voice is downloading. The backup voice is available. You can keep talking or typing."
    return ""


def fetch(path, url, spec):
    """Keep an interrupted transfer; replace a bad file only after its replacement verifies."""
    if matches(path, spec):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    if partial.is_symlink():
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if offset and response.status == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    partial.unlink(missing_ok=True)
                    raise ValueError("The server returned the wrong download range")
            else:
                offset = 0  # A server may ignore Range; never append its full response.
            with partial.open("ab" if offset else "wb") as handle:
                while chunk := response.read(1 << 20):
                    if shutil.disk_usage(path.parent).free < 10 * 2**30:
                        raise OSError("Keep at least 10 GB free to download")
                    handle.write(chunk)
    except urllib.error.HTTPError as error:
        if error.code == 416:
            partial.unlink(missing_ok=True)
        raise
    if not matches(partial, spec):
        if "size" in spec and partial.stat().st_size < spec["size"]:
            raise ValueError(f"{path.name} was interrupted")
        partial.unlink(missing_ok=True)
        raise ValueError(f"{path.name} did not verify")
    os.replace(partial, path)


def snapshot(key, *, check=False, report=False):
    spec = MANIFEST["hf"][key]
    cache = home() / "hub" / ("models--" + spec["repo"].replace("/", "--"))
    folder = cache / "snapshots" / spec["revision"]
    alias = cache / "refs" / spec["alias"]
    bad = [name for name, proof in spec["files"].items() if not matches(folder / name, proof)]
    # Never leave a default/tag reference pointing at a partial or changed snapshot.
    if bad:
        if not check:
            alias.unlink(missing_ok=True)
        else:
            raise ValueError(f"{key} did not verify")
    if check:
        if alias.read_text() != spec["revision"]:
            raise ValueError(f"{key} has the wrong revision")
        return folder
    bad = [name for name in bad if not ((source := shared_file(spec, name, spec["files"][name]))
                                      and seed(folder / name, source, spec["files"][name]))]
    if bad:
        print(f"  download: {key}", flush=True)
        if report and key in ("voice", "speech-tokenizer"):
            voice_status("downloading")
    for name in bad:
        url = f"{spec.get('origin', 'https://huggingface.co')}/{spec['repo']}/resolve/{spec['revision']}/{name}"
        fetch(folder / name, url, spec["files"][name])
    # Check every file, including a previous cache hit, before the library can resolve its alias.
    if any(not matches(folder / name, proof) for name, proof in spec["files"].items()):
        raise ValueError(f"{key} did not verify")
    alias.parent.mkdir(parents=True, exist_ok=True)
    temporary = alias.with_name(alias.name + ".part")
    temporary.write_text(spec["revision"])
    os.replace(temporary, alias)
    return folder


def unpack(archive, destination):
    with tarfile.open(archive) as package:
        # Works with Apple's bootstrap Python too. No links, devices, parent paths or special permission bits.
        for member in package.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected archive path or file type")
        for member in package.getmembers():
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
                target.chmod(member.mode & 0o777)


def files(folder, *, hashes=True):
    found = {}
    for base, directories, names in os.walk(folder):
        directories[:] = sorted(d for d in directories if d not in {".git", ".venv", "__pycache__", "node_modules"})
        for name in directories[:]:
            p = Path(base) / name
            if p.is_symlink():
                found[p.relative_to(folder).as_posix()] = {"symlink": os.readlink(p)}
                directories.remove(name)
        for name in sorted(names):
            p = Path(base) / name
            if name in {".git", ".verified.json"}:
                continue
            if p.is_symlink():
                found[p.relative_to(folder).as_posix()] = {"symlink": os.readlink(p)}
            elif p.is_file():
                found[p.relative_to(folder).as_posix()] = (
                    {"sha256": digest(p), "executable": bool(p.stat().st_mode & 0o111)} if hashes else
                    {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns, "executable": bool(p.stat().st_mode & 0o111)})
    return found


def harness_ready(name, *, full=False):
    folder = ROOT / "tools/harnesses" / name
    try:
        proof = json.loads((folder / ".verified.json").read_text())
        pin = MANIFEST["harnesses"][name]
        return (proof["pin"] == pin["platforms"][platform.machine()] and proof["stat"] == files(folder, hashes=False)
                and (not full or proof["files"] == files(folder))
                and (folder / proof["binary"]).is_file()
                and (ROOT / "tools/harnesses/bin" / name).resolve() == (folder / proof["binary"]).resolve())
    except (OSError, ValueError, KeyError):
        return False


def shared_tool(name):
    found = shutil.which(name)
    if found and not Path(found).resolve().is_relative_to((ROOT / "tools").resolve()):
        return found
    return ""


def harness(name):
    shared = shared_tool(name)
    if shared:
        # Do not replace a tool another app uses. Record the version it actually reports.
        result = subprocess.run([shared, "--version"], capture_output=True, text=True, timeout=15,
                                stdin=subprocess.DEVNULL)
        if result.returncode or not result.stdout.strip():
            raise ValueError(f"{name} could not report its version")
        home().mkdir(parents=True, exist_ok=True)
        (home() / f"shared-{name}.json").write_text(json.dumps({"path": shared, "version": result.stdout.strip()}))
        return
    if harness_ready(name, full=True):
        return
    pin = MANIFEST["harnesses"][name]["platforms"][platform.machine()]
    archive = home() / (name + ".tgz")
    print(f"  download: {name}", flush=True)
    fetch(archive, pin["url"], pin)
    parent = ROOT / "tools/harnesses"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=parent) as temp:
        stage = Path(temp) / name
        stage.mkdir()
        unpack(archive, stage)
        candidates = [p for p in stage.rglob("*") if p.name in (name, name + ".exe")
                      and p.is_file() and p.stat().st_mode & 0o111]
        if len(candidates) != 1:
            raise ValueError(f"{name} has no unique executable")
        binary = candidates[0].relative_to(stage).as_posix()
        proof = {"pin": pin, "binary": binary, "files": files(stage), "stat": files(stage, hashes=False)}
        (stage / ".verified.json").write_text(json.dumps(proof))
        # No entry point becomes visible before the whole verified archive is in place.
        into = parent / name
        if into.exists():
            shutil.rmtree(into)
        os.replace(stage, into)
        link = parent / "bin" / name
        link.parent.mkdir(exist_ok=True)
        pending = link.with_name(name + ".part")
        pending.unlink(missing_ok=True)
        pending.symlink_to(Path("..") / name / binary)
        os.replace(pending, link)
    if not harness_ready(name, full=True):
        raise ValueError(f"{name} did not verify")


def xperfect_proof(root=ROOT, pin=None):
    proof = json.loads((root / "brain/xperfect.files.json").read_text())
    kept = (root / "brain/xperfect.pin").read_text().strip() if (root / "brain/xperfect.pin").exists() else None
    pin = pin or kept or subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD:brain/xperfect"], text=True).strip()
    patches = {p.name: {"sha256": digest(p)} for p in sorted((root / "brain/patches").glob("xperfect-*.patch"))}
    if pin != proof["pin"] or (kept is not None and kept != pin) or patches != proof["patches"]:
        raise ValueError("The Workers' file list does not match their pin and patches")
    return proof


def xperfect_check(root=ROOT, pin=None):
    proof = xperfect_proof(root, pin)
    xp = root / "brain/xperfect"
    for name, spec in proof["files"].items():
        path = xp / name
        if not matches(path, spec) or bool(path.stat().st_mode & 0o111) != spec["executable"]:
            raise ValueError(f"The Workers' files did not verify: {name}")
    # The source check also rejects unexpected code. Runtime outputs are excluded by the upstream ignore rules.
    unexpected = set(files(xp)) - set(proof["files"])
    unexpected = {p for p in unexpected if not any(part in {".git", ".venv", "__pycache__"} for part in Path(p).parts)}
    if unexpected:
        with tempfile.TemporaryDirectory(prefix="vx-ignore-") as temp:
            subprocess.run(["git", "init", "-q", temp], check=True, capture_output=True)
            ignored = subprocess.run(["git", "--git-dir=" + temp + "/.git", "--work-tree=" + str(xp),
                                      "-c", "core.excludesFile=/dev/null", "check-ignore", "--no-index", "--stdin"],
                                     cwd=xp, input="\n".join(sorted(unexpected)) + "\n", capture_output=True, text=True)
        unexpected -= set(ignored.stdout.splitlines())
        if unexpected:
            raise ValueError("Unexpected Workers' files: " + ", ".join(sorted(unexpected)[:3]))
    if (xp / ".git").exists():
        def git(*args):
            return subprocess.run(["git", "--no-optional-locks", "-C", str(xp), *args], capture_output=True)
        head = git("rev-parse", "--verify", "HEAD")
        if head.returncode or head.stdout.decode().strip() != proof["pin"]:
            raise ValueError("The Workers' Git HEAD is not their pin")
        # The index can be the pristine pin or the complete checked working tree. Partial/staged drift is refused.
        if git("diff", "--cached", "--quiet", proof["pin"], "--").returncode:
            tracked = git("ls-files", "-z")
            names = {os.fsdecode(p) for p in tracked.stdout.split(b"\0") if p}
            if tracked.returncode or names != set(proof["files"]) or git("diff", "--quiet", "--").returncode:
                raise ValueError("The Workers' Git index does not match their pin or checked files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", choices=("voice", "hearing", "harnesses", "claude", "codex", "xperfect", "upgrade-report"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--prepare", action="store_true", help="report voice preparation for the running conversation")
    parser.add_argument("--pending", action="store_true", help="mark voice preparation before starting its background process")
    parser.add_argument("--pin", help="the xPerfect gitlink already read by status")
    args = parser.parse_args()
    try:
        if args.part == "upgrade-report":
            print(json.dumps(upgrade_report(), indent=2))
        elif args.part == "voice" and args.pending:
            voice_status("preparing")
        elif args.part == "xperfect":
            xperfect_check(pin=args.pin)
        elif args.part in ("harnesses", "claude", "codex"):
            for name in (("claude", "codex") if args.part == "harnesses" else (args.part,)):
                if args.check:
                    if not shared_tool(name) and not harness_ready(name, full=True):
                        raise ValueError(f"{name} did not verify")
                else:
                    harness(name)
        else:
            if args.part == "voice" and args.prepare:
                voice_status("preparing")
            for key in (("voice", "speech-tokenizer") if args.part == "voice" else ("turn-en", "turn-multilingual")):
                snapshot(key, check=args.check, report=args.prepare)
            if args.part == "voice" and args.prepare:
                voice_status("ready")
    except (OSError, ValueError, KeyError, tarfile.TarError, http.client.HTTPException, subprocess.SubprocessError) as error:
        if args.part == "voice" and args.prepare:
            voice_status("failed")
        repair = ("Keep this copy and install a fresh copy of Light." if args.part == "xperfect" else
                  "Run ./vx up again to repair it.")
        print(f"  {args.part} is not ready. {repair}", file=sys.stderr)
        print(f"  Detail: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
