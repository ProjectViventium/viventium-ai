"""A short recording of each voice, so a person can hear one before choosing it.

Each voice says the same line itself (the real engine, the way a call uses it), once; the recordings are kept
with the page (call/ui/public/samples/<voice>.wav) and played from there, so listening costs nothing and
needs no key. A new voice in settings/catalog.py gets its recording with:

    ./vx samples            every voice that has none yet (keys from the Keychain, the local voice server up)
    ./vx samples eve        one voice again
"""
import asyncio
import os
import sys
import wave
from pathlib import Path

from settings import catalog

FOLDER = Path(__file__).resolve().parents[1] / "call" / "ui" / "public" / "samples"


def path(sample: str) -> Path:
    return FOLDER / f"{sample}.wav"


def seconds(file: Path) -> float:
    with wave.open(str(file)) as w:
        return w.getnframes() / w.getframerate()


async def render(option: dict) -> Path:
    import aiohttp
    from speech import factory
    from speech.sounds import _render
    os.environ.update({k: v for k, v in option["env"].items() if k.startswith("TTS_") and v})
    FOLDER.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as http:
        engine = factory._voice(option["env"]["TTS"], http, option["env"].get("TTS_VOICE"))
        await _render(engine, catalog.SAMPLE_LINE, path(option["sample"]))
    return path(option["sample"])


def main(names: list[str]) -> None:
    voices = [o for o in catalog.PARTS["talk"]["options"] if o.get("sample")]
    for option in voices:
        if names and option["id"] not in names or not names and path(option["sample"]).exists():
            continue
        try:
            made = asyncio.run(render(option))
            print(f"  {option['id']}: {seconds(made):.1f} s, {made.stat().st_size // 1024} KB")
        except Exception as e:  # (a missing key, the local voice server down): said, and the others still render
            print(f"  {option['id']}: not recorded ({type(e).__name__}: {str(e)[:120]})", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
