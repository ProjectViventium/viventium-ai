"""Voice tags stay in their sentence. Chatterbox keeps its native, best-effort sounds.

Isolated clips remain a research/build asset, never part of live calls or voice notes.
The runtime never inserts a recording from another utterance.
"""
import json
import os
import random
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "sounds"
ROOT = HERE.parent
CHECK = [str(ROOT / "tools" / "soundcheck" / ".venv" / "bin" / "python"), str(ROOT / "tools" / "soundcheck" / "soundcheck.py")]
BEFORE, AFTER = 0.08, 0.12  # seconds of quiet around a sound, as between spoken phrases
CLEAR = 0.45
# What each documented tag is checked as (tools/soundcheck's sounds): the classifier hears a giggle and a chuckle as
# laughter, a breath in or out as breathing, a tsk, a tongue click and a lip smack as a click.
SOUND_OF = {"laugh": "laugh", "chuckle": "laugh", "giggle": "laugh", "sigh": "sigh", "gasp": "gasp", "cry": "cry",
            "breath": "breath", "inhale": "breath", "exhale": "breath", "hum-tune": "hum", "tsk": "click",
            "tongue-click": "click", "lip-smack": "click",
            # (Chatterbox Turbo's own, from its tokenizer: tests/sound_test.py measures them; heard ones are documented)
            "cough": "cough", "clear throat": "throat", "sniff": "sniff", "groan": "groan", "crying": "cry", "shush": "hiss"}
LIGHT_LAUGHS = ("chuckle", "giggle")  # (when the voice's own is not heard: one of her three shortest laughs)
_cache: dict[str, dict[str, list[tuple[np.ndarray, int]]]] = {}
_documented: dict[tuple, list[str]] = {}
_last: dict[str, int] = {}


def voice() -> str:
    """The active voice's folder name: its model and voice (chatterbox-turbo-8bit-default, xai-eve)."""
    provider = os.environ.get("TTS", "mlx_local")
    if provider in ("xai", "xai_plan"):
        return "xai-" + os.environ.get("TTS_VOICE", "eve")
    if provider == "mac_say":
        return "mac-speech"
    if provider != "mlx_local":
        return provider + "-" + os.environ.get("TTS_VOICE", "default")
    model = os.environ.get("TTS_MODEL", "mlx-community/chatterbox-turbo-8bit").rstrip("/").split("/")[-1]
    return f"{model}-{os.environ.get('TTS_VOICE', 'default')}"


def clips() -> dict[str, list[tuple[np.ndarray, int]]]:
    """{sound: [(int16 audio, rate)]} for the active voice, {} when it has none."""
    name = voice()
    if name not in _cache:
        found: dict[str, list[tuple[np.ndarray, int]]] = {}
        for f in sorted((LIBRARY / name).glob("*.wav")):
            with wave.open(str(f)) as w:
                audio = np.frombuffer(w.readframes(w.getnframes()), np.int16)
                found.setdefault(f.stem.rsplit("-", 1)[0], []).append((audio, w.getframerate()))
        _cache[name] = found
    return _cache[name]


def documented() -> list[str]:
    """The active voice's documented inline tags, without brackets, as her voice rules name them (main's typed voice
    data in brain/prompts/feelings, found the way brain/feelings.py finds it)."""
    key = (os.environ.get("TTS", "mlx_local"), os.environ.get("TTS_MODEL", ""))
    if key not in _documented:
        from brain import feelings  # (here: speech/ is imported by brain/queen.py)
        controls = feelings._voice().get("inline_controls", {})
        if controls.get("mode") == "chatterbox_nonverbal_markers":
            tokens = controls.get("exact_tokens", [])
        elif controls.get("mode") == "xai_speech_tags":
            tokens = json.loads((feelings.kernel.PROMPTS / controls["dialect_contract"]).read_text())["speech_tags"]["inline"]
        else:
            tokens = []
        _documented[key] = [t.strip("[]").lower() for t in tokens]
    return _documented[key]


def supported() -> list[str]:
    """Every inline tag the active voice can be given: the documented ones, and those its own model's tokenizer knows
    (a local voice's added tokens, read from the local model cache: Chatterbox Turbo knows 19, main documents 4). What
    tests/sound_test.py measures; only the heard ones are offered to her, once documented (brain/prompts/feelings)."""
    found = list(documented())
    if os.environ.get("TTS", "mlx_local") == "mlx_local":
        try:
            from huggingface_hub import try_to_load_from_cache
            path = try_to_load_from_cache(os.environ.get("TTS_MODEL", "mlx-community/chatterbox-turbo-8bit"), "added_tokens.json")
            tokens = json.loads(Path(path).read_text()) if isinstance(path, str) else {}
            found += [t.strip("[]").lower() for t in tokens if re.fullmatch(r"\[[a-z][a-z -]*\]", t)]
        except (ImportError, OSError, ValueError):
            pass
    return list(dict.fromkeys(found))


def wrapping() -> list[str]:
    """The active voice's documented wrapping controls (xAI's <soft>words</soft> and the rest), without brackets."""
    from brain import feelings
    controls = feelings._voice().get("inline_controls", {})
    if controls.get("mode") != "xai_speech_tags":
        return []
    return json.loads((feelings.kernel.PROMPTS / controls["dialect_contract"]).read_text())["speech_tags"]["wrapping"]


def heard() -> list[str]:
    """Offered native sounds. Chatterbox's are best effort; Eve keeps its measured gate."""
    name = voice()
    return list(INLINE[name]) if name in INLINE else [t.strip("[]") for t in native_controls(name).get("exact_tokens", ())]


# Eve's release-42 qualification is unchanged. Local controls come from the same typed data Feelings reads.
INLINE = {"xai-eve": ("laugh", "sigh"), "mac-speech": ()}


def native_controls(name: str | None = None) -> dict:
    """The declared local voice's native controls, including when it is the selected voice's fallback."""
    name = name or voice()
    if name in INLINE:
        return {}
    from brain import feelings
    providers = json.loads((feelings.kernel.PROMPTS / "tts_provider_capabilities.json").read_text())["providers"]
    for provider in providers.values():
        controls = provider.get("inline_controls", {})
        if controls.get("mode") == "chatterbox_nonverbal_markers" and any(
                name == model["id"].rsplit("/", 1)[-1] + "-default" for model in provider["runtime_models"]):
            return controls
    return {}


def native_text(text: str, name: str | None = None) -> str:
    """Only declared sound tags are controls. Ordinary words and other brackets stay intact."""
    name = name or voice()
    local = {} if name in INLINE else native_controls(name)
    allowed = INLINE.get(name, tuple(t.strip("[]") for t in local.get("exact_tokens", ())))
    if name not in INLINE and not local:
        return text
    pattern = r"\[(" + "|".join(map(re.escape, SOUND_OF)) + r")\]"
    return re.sub(pattern, lambda m: (f"[{m[1].lower()}]" if local else m[0]) if m[1].lower() in allowed else "", text, flags=re.I)


def pick(sound: str) -> tuple[np.ndarray, int]:
    """One of her clips for this sound, never the same one twice in a row."""
    options = clips()[sound]
    choices = [i for i in range(len(options)) if i != _last.get(sound)] or [0]
    _last[sound] = i = random.choice(choices)
    return options[i]


def audio(sound: str, rate: int) -> np.ndarray:
    """A clip with its quiet around it, as int16 at the voice's own rate."""
    clip, own = pick(sound)
    if own != rate:  # (linear resampling is plenty for a half-second sound)
        n = int(len(clip) * rate / own)
        clip = np.interp(np.linspace(0, len(clip) - 1, n), np.arange(len(clip)), clip).astype(np.int16)
    quiet = lambda s: np.zeros(int(s * rate), np.int16)  # noqa: E731
    return np.concatenate([quiet(BEFORE), clip, quiet(AFTER)])


def frames(samples: np.ndarray, rate: int):
    """LiveKit audio frames of 20 ms."""
    from livekit import rtc
    step = rate // 50
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        yield rtc.AudioFrame(data=chunk.tobytes(), sample_rate=rate, num_channels=1, samples_per_channel=len(chunk))


def pieces(text: str) -> list[tuple[str, str]]:
    """A voice note keeps each native tag in the request containing its words."""
    return [("say", native_text(text))]


# Only explicitly marked stage directions are controls. Bare words are always speech, at every chunk boundary.
# Exact action forms avoid treating ordinary emphasis such as "*laughable*" as a control.
_SOUND_WORDS = (r"laugh(?:s|ing)?|chuckl(?:e|es|ing)|giggl(?:e|es|ing)|sigh(?:s|ing)?|gasp(?:s|ing)?"
                r"|cr(?:y|ies|ying)|sob(?:s|bing)?|breath(?:e|es|ing)?|inhal(?:e|es|ing)|exhal(?:e|es|ing)"
                r"|hum(?:s|ming)?|tsk(?:s)?|cough(?:s|ing)?|sniff(?:s|ing)?|groan(?:s|ing)?|shush(?:es|ing)?"
                r"|whisper(?:s|ing)?|clears? (?:her |his )?throat"
                r"|clearing (?:her |his )?throat|smacks? (?:her |his )?lips|clicks? (?:her |his )?tongue")
_STAGE = re.compile(rf"\s*(?:\*\s*(?:{_SOUND_WORDS})\s*\*|\(\s*(?:{_SOUND_WORDS})\s*\))", re.I)
_CUT = re.compile(r"\s*\[[A-Za-z][A-Za-z -]{0,20}$")
_OPEN = re.compile(r"[*(\[][^*()\[\]]{0,30}$")  # (a stage direction or a tag still arriving)


async def unstaged(text):
    """A text transform before her voice: stage directions of sounds out (_STAGE), the rest as it streams. Holds back
    only an opening "*", "(" or "[" for up to thirty letters (to see whether it is one)."""
    held, said = "", False
    async for piece in text:
        held += piece
        held = _STAGE.sub("", held)
        cut = _OPEN.search(held)
        out, held = (held[:cut.start()], held[cut.start():]) if cut else (held, "")
        if not said:  # (a direction gone from her first words leaves no space before them)
            out = out.lstrip()
        if out:
            said = True
            yield out
    held = _CUT.sub("", _STAGE.sub("", held))
    if not said:
        held = held.lstrip()
    if held:
        yield held


async def voiced(text, speak, rate: int):
    """Stream each voice's allowed native markers with their words."""
    async def native():
        held = ""
        async for piece in text:
            held += piece
            cut = re.search(r"\[[A-Za-z -]{0,20}$|\[$", held)
            out, held = (held[:cut.start()], held[cut.start():]) if cut else (held, "")
            if out:
                yield native_text(out)
        if held:
            yield native_text(held)

    spoken = speak(native())
    try:
        async for frame in spoken:
            yield frame
    finally:
        await spoken.aclose()


# Building a voice's clips (once per voice; needs tools/soundcheck and the voice itself)

async def _render(engine, text: str, path: Path) -> None:
    from livekit.agents import tts as lk_tts
    stream = (engine if engine.capabilities.streaming else lk_tts.StreamAdapter(tts=engine)).stream()
    stream.push_text(text)
    stream.end_input()
    got = [ev.frame async for ev in stream]
    await stream.aclose()
    samples = np.frombuffer(b"".join(bytes(f.data) for f in got), np.int16).astype(np.float32)
    loud = np.flatnonzero(np.abs(samples) > np.abs(samples).max() * 0.01) if len(samples) else []
    rate = got[0].sample_rate if got else 24000
    if len(loud):  # cut the quiet ends, fade 15 ms in and out, peak at most -1 dB
        samples = samples[max(0, loud[0] - int(0.02 * rate)):loud[-1] + int(0.04 * rate)]
        fade = min(int(0.015 * rate), len(samples) // 4)
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)
        samples *= min(1.0, 29000 / max(1.0, float(np.abs(samples).max())))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())


def _install(source: bytes | Path, target: Path) -> None:
    """One file put in place whole: written beside it, then renamed over it (a reader sees the old file or the new one,
    never a part of either, and the old one stays until the new one is complete)."""
    tmp = target.with_name(f".{target.name}.new")
    tmp.write_bytes(source.read_bytes() if isinstance(source, Path) else source)
    os.replace(tmp, target)


def _playable(path: Path) -> bool:
    """A clip that can be played as one: a mono 16-bit WAV of a tenth of a second at least."""
    try:
        with wave.open(str(path)) as w:
            return w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getnframes() >= w.getframerate() // 10
    except (OSError, wave.Error, EOFError):
        return False


async def build(tries: int = 36, keep: int = 6, only: list[str] | None = None, replace: bool = False) -> None:
    """Her checked clips for the documented tags of the active voice that a classifier can hear (SOUND_OF), or only the
    tags named: each rendered on its own `tries` times, cut, scored on the sound it is checked as, and the clearest `keep`
    kept. A tag that has clips keeps them unless `replace` is asked for (checked clips are never lost to a worse run);
    a replacement is installed only when it is heard and playable, each file whole, the extra old ones removed after,
    the manifest last. A chuckle or a giggle built here whose own renderings are not heard is one of her three shortest
    laughs (neither voice's own [chuckle] was heard); building one tag never makes another. The manifest says,
    for every tag built, whether it is heard and its best score; a tag never heard keeps no clip (heard() leaves it out)."""
    import aiohttp
    sys.path.insert(0, str(ROOT))
    from speech import factory
    folder = LIBRARY / voice()
    have = {f.stem.rsplit("-", 1)[0] for f in folder.glob("*.wav")} if folder.exists() else set()
    tags = [t for t in documented() if t in SOUND_OF and (not only or t in only) and (replace or t not in have)]
    for tag in [t for t in documented() if t in SOUND_OF and (not only or t in only) and t not in tags]:
        print(f"  {tag}: kept its clips (build --replace {tag} to make new ones)")
    work = ROOT / "logs" / "sound" / "build" / voice()
    work.mkdir(parents=True, exist_ok=True)
    files: dict[str, list[Path]] = {}
    if tags:
        async with aiohttp.ClientSession() as http:
            engine = factory.tts(http)
            for tag in tags:
                for i in range(tries):  # (a laugh comes out more often when asked twice)
                    path = work / f"{tag}-{i}.wav"
                    await _render(engine, f"[{tag}]" if i % 2 or tag != "laugh" else "[laugh] [laugh]", path)
                    files.setdefault(tag, []).append(path)
    out = subprocess.run(CHECK + [str(p) for ps in files.values() for p in ps], capture_output=True, text=True,
                         check=True).stdout if files else ""
    scores = {json.loads(line)["file"]: json.loads(line) for line in out.splitlines() if line.startswith("{")}
    folder.mkdir(parents=True, exist_ok=True)
    kept = folder / "manifest.json"
    manifest = json.loads(kept.read_text()) if kept.exists() else {}
    manifest.update({"voice": voice(), "checked_by": "MIT/ast-finetuned-audioset-10-10-0.4593",
                     "rule": f"sound score >= {CLEAR} and speech < 0.3, as the clip is played"})
    manifest.setdefault("clips", {})
    manifest.setdefault("tags", {})
    derived = set()  # (the tags made from her short laughs here: only one built now, never another)
    for tag, paths in files.items():
        sound = SOUND_OF[tag]
        score = lambda p: scores.get(str(p), {}).get("peak", {}).get(sound, 0)  # noqa: E731
        good = sorted((p for p in paths if score(p) >= CLEAR and scores[str(p)]["peak"]["speech"] < 0.3 and _playable(p)),
                      key=lambda p: -score(p))[:keep]
        best = round(max((score(p) for p in paths), default=0.0), 3)
        if not good:  # (nothing new heard: whatever it had stays as it was)
            had = sorted(f.stem for f in folder.glob(f"{tag}-*.wav"))
            manifest["tags"][tag] = {**manifest["tags"].get(tag, {}), "heard": bool(had), "kept": len(had), "of": len(paths),
                                     "best": best, "checked_as": sound, **({"note": "no new rendering heard: kept"} if had else {})}
            print(f"  {tag}: none of {len(paths)} heard (best {best:.2f} as {sound})" + ("; its clips kept" if had else ""))
            if not had and tag in LIGHT_LAUGHS:
                derived.add(tag)
            continue
        for n, p in enumerate(good, 1):
            _install(p, folder / f"{tag}-{n}.wav")
            manifest["clips"][f"{tag}-{n}"] = {"score": score(p), "seconds": scores[str(p)]["seconds"]}
        for old in folder.glob(f"{tag}-*.wav"):  # (more of them than now: the rest go, after the new ones are in)
            if int(old.stem.rsplit("-", 1)[1]) > len(good):
                old.unlink()
                manifest["clips"].pop(old.stem, None)
        manifest["tags"][tag] = {"heard": True, "kept": len(good), "of": len(paths), "best": best, "checked_as": sound}
        print(f"  {tag}: kept {len(good)} of {len(paths)} (best {best:.2f} as {sound})")
    shortest = sorted((k for k in manifest["clips"] if k.startswith("laugh-") and "from" not in manifest["clips"][k]),
                      key=lambda k: manifest["clips"][k]["seconds"])[:3]
    for tag in derived:  # (her own short laughs, for a chuckle or giggle built now whose own was not heard)
        for n, k in enumerate(shortest, 1):
            _install(folder / f"{k}.wav", folder / f"{tag}-{n}.wav")
            manifest["clips"][f"{tag}-{n}"] = {**manifest["clips"][k], "from": k}
        if shortest:
            manifest["tags"][tag] = {**manifest["tags"].get(tag, {}), "heard": True, "from": "her shortest laughs"}
    _cache.pop(voice(), None)
    manifest["heard"] = [tag for tag in documented() if tag in clips()]
    _install(json.dumps(manifest, indent=1).encode() + b"\n", kept)
    print(f"  heard on this voice: {', '.join(manifest['heard'])}")
    print(f"  clips: {folder}")


if __name__ == "__main__" and sys.argv[1:2] == ["build"]:  # build [--replace] [tag ...]: kept clips stay unless replaced
    import asyncio
    asyncio.run(build(only=[a for a in sys.argv[2:] if a != "--replace"] or None, replace="--replace" in sys.argv[2:]))
