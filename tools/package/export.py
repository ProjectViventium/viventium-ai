#!/usr/bin/env python3
"""Export the product from a private Git checkout without copying its history or runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ROOT_FILES = {".gitignore", ".python-version", "pyproject.toml", "uv.lock", "vx", "LICENSE", "SECURITY.md", "README.md", "CHANGELOG.md"}
DOCS = {"docs/licences.md", "docs/dependencies.csv", "docs/distribution.md", "docs/downloads.md", "docs/notices/LobeHub-MIT.txt",
        "docs/install.md"}  # (the README and the install guide are written for the public; their pictures: BINARY)
WORKER_TOOLS = {"tools/grok-build-pin.json", "tools/grok-worker-auth"}
PRODUCT = {"brain", "call", "chat", "core", "life-template", "settings", "speech"}
PROFILES = {"cloud", "hybrid", "local", "small-8", "small-16", "small-24"}
TEXT_SUFFIXES = {".css", ".csv", ".env", ".example", ".json", ".lock", ".md", ".mjs", ".patch",
                 ".py", ".sh", ".svg", ".swift", ".toml", ".ts", ".tsx", ".txt", ".yaml"}
BINARY = re.compile(
    r"call/ui/(?:app/icon\.png|fonts/(?:CommitMono-(?:400|700)-(?:Italic|Regular)\.otf|"
    r"InterTight-Variable\.woff2|PublicSans-Variable\.ttf)|public/(?:"
    r"marks/(?:viventium-logo\.png|v-glass\.webp)|samples/(?:chatterbox|eve)\.wav))|"
    r"speech/sounds/(?:chatterbox-turbo-8bit-default|xai-eve)/(?:chuckle|gasp|laugh|sigh)-[1-6]\.wav|"
    r"docs/images/[a-z0-9-]+\.jpg"
)
RUNTIME_DIRS = {".git", ".github", ".next", ".venv", ".build", "__pycache__", "backups", "exports",
                "logs", "models", "node_modules", "private", "screenshots", "sessions", "state"}
EMAIL = re.compile(rb"(?<![\w@])([a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,})(?![\w.-])", re.I)
PATH_OR_CHAT = re.compile(rb"(?<![\w.])/(?:Us" rb"ers|ho" rb"me)/[\w.-]+/|(?:co" rb"dex://|cla" rb"ude\.ai/chat/)")
APPROVED_ADDRESSES = {
    "call/ui/fonts/CommitMono-OFL.txt": {b"eigi0088" b"@gmail.com"},  # copyright notice
    "brain/night.py": {b"night" b"@viventium.invalid"},  # synthetic record source
}


def selected(name, *, payload):
    path = PurePosixPath(name)
    head = path.parts[0]
    if name in ROOT_FILES or name in DOCS or name in WORKER_TOOLS or name.startswith("docs/images/"):
        return True
    if not payload and name.startswith("speech/sounds/") and name.endswith(".wav"):
        return False  # (research and build clips: the runtime never plays them, so the public source does not carry them)
    if (set(path.parts) & RUNTIME_DIRS or any(part.startswith(("state-", ".next-")) for part in path.parts)
            or name.endswith((".local.env", ".env.local"))):
        return False
    if head == "profiles":
        return name == "profiles/resources.tsv" or (
            len(path.parts) == 2 and path.suffix == ".env" and path.stem in PROFILES)
    if head in PRODUCT:
        return name != "brain/xperfect" and not name.startswith("brain/xperfect/") and name != "call/ui/README.md"
    return name.startswith(("tools/media/", "tools/menubar/", "tools/desktop/")) or (
        not payload and name.startswith("tools/package/")
    )


def scan(tree):
    configured_name = subprocess.run(["git", "-C", str(ROOT), "config", "--get", "user.name"],
                                     capture_output=True, text=True).stdout
    identities = {Path.home().name, ROOT.owner(), *configured_name.split()} - {"root", "admin", "runner", "user"}
    identities = {name.encode() for name in identities if len(name) > 2}
    private_name = re.compile(rb"\b(?:" + b"|".join(map(re.escape, identities)) + rb")\w*\b", re.I) if identities else None
    failed = []
    for file in sorted(tree.rglob("*")):
        if not file.is_file():
            continue
        name = file.relative_to(tree).as_posix()
        raw = file.read_bytes()
        if BINARY.fullmatch(name):
            raw = b"\n".join(re.findall(rb"[\x20-\x7e]{8,}", raw))
        for line, value in enumerate(raw.splitlines(), 1):
            emails = set(EMAIL.findall(value)) - APPROVED_ADDRESSES.get(name, set())
            emails = {email for email in emails if not re.search(rb"\d@\d", email)}
            if PATH_OR_CHAT.search(value) or emails or (private_name and private_name.search(value)):
                failed.append(f"{name}:{line}")
        if PATH_OR_CHAT.search(os.fsencode("/" + name)) or (private_name and private_name.search(os.fsencode(name))):
            failed.append(f"{name} (filename)")
    if failed:
        raise SystemExit("Identity scan failed (locations only):\n" + "\n".join(failed))
    with tempfile.TemporaryDirectory(prefix="light-scan-") as temp:
        report = Path(temp) / "findings.json"
        result = subprocess.run(["gitleaks", "dir", "--redact=100", "--no-banner", "--log-level=error",
                                 "--report-format=json", f"--report-path={report}", "."], cwd=tree,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            for item in json.loads(report.read_text()) if report.is_file() else []:
                print(f"{item['File']}:{item['StartLine']} ({item['RuleID']})")
            raise SystemExit(f"Secret scan did not pass (gitleaks exit {result.returncode}).")


def export(destination, *, payload):
    manifest = ROOT / ".vx-export-files"
    listing = manifest.read_bytes() if manifest.is_file() else subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--stage", "-z"])
    with tempfile.TemporaryDirectory(prefix=".light-export-", dir=destination.parent) as temp:
        tree = Path(temp) / "tree"
        tree.mkdir()
        pin = None
        included = []
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            meta, encoded = entry.split(b"\t", 1)
            mode, oid, stage = meta.decode().split()
            name = os.fsdecode(encoded)
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\n" in name or not path.parts:
                raise SystemExit("Invalid source path in file list.")
            if name == "brain/xperfect" and mode == "160000" and stage == "0":
                if not re.fullmatch(r"[0-9a-f]{40}", oid):
                    raise SystemExit("Invalid xPerfect pin.")
                pin = oid
                included.append(entry)
            if not selected(name, payload=payload):
                continue
            if stage != "0" or mode not in {"100644", "100755"}:
                raise SystemExit(f"Unexpected index entry: {name}")
            source = ROOT / name
            if any(parent.is_symlink() for parent in source.parents if parent != ROOT and ROOT in parent.parents):
                raise SystemExit(f"Unexpected symlink parent: {name}")
            if not source.exists() and not source.is_symlink():
                continue
            if not stat.S_ISREG(source.lstat().st_mode):
                raise SystemExit(f"Unexpected file type: {name}")
            target = tree / name
            if target.suffix not in TEXT_SUFFIXES and not BINARY.fullmatch(name) and name not in ROOT_FILES | WORKER_TOOLS | {
                "profiles/resources.tsv", "call/ui/LICENSE", "call/ui/.prettierignore", "call/ui/.prettierrc", "call/ui/.gitignore", "call/ui/.npmrc", "call/ui/.env.example", "speech/tts/.python-version", "tools/media/make", "tools/desktop/hold"
            }:
                raise SystemExit(f"Unreviewed file type: {name}")
            contents = source.read_bytes()
            if not BINARY.fullmatch(name):
                contents.decode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            target.chmod(0o755 if mode == "100755" else 0o644)
            # Keep file paths and modes in the clean export. Only the upstream xPerfect pin needs a Git object ID.
            included.append(f"{mode} - 0\t".encode() + encoded)
        if not pin:
            raise SystemExit("xPerfect pin is missing.")
        archive_pin = tree / "brain/xperfect.archive.sha256.txt"
        if not archive_pin.is_file() or not re.fullmatch(rf"{pin} [0-9a-f]{{64}}\n", archive_pin.read_text()):
            raise SystemExit("The xPerfect archive checksum must match the selected commit.")
        (tree / "brain/xperfect.pin").write_text(pin + "\n")
        scan(tree)
        if not payload:
            (tree / manifest.name).write_bytes(b"\0".join(included) + b"\0")
        if payload:
            digest = hashlib.sha256()
            for file in sorted(tree.rglob("*")):
                if file.is_file():
                    digest.update(os.fsencode(file.relative_to(tree)) + b"\0" + hashlib.sha256(file.read_bytes()).digest())
            (tree / ".vx-release").write_text(digest.hexdigest() + " packaged\n")
        # Reserve the destination before moving. Never replace a previous export.
        destination.mkdir()
        try:
            os.replace(tree, destination)
        except OSError:
            destination.rmdir()
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--payload", action="store_true", help="prepare the runtime payload for the app")
    args = parser.parse_args()
    out = args.destination.resolve()
    export(out, payload=args.payload)
    print(out)
