"""Resource contracts for profile selection, startup, Settings and doctor. No model is loaded here."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Resources:
    memory_gb: int
    setup_gb: int
    model_gb: int


PROFILES = {
    name: Resources(*map(int, values))
    for line in (Path(__file__).resolve().parents[1] / "profiles/resources.tsv").read_text().splitlines()
    if line and not line.startswith("#")
    for name, *values in [line.split()]
}


def selected(memory_bytes: int, requested: str = "local") -> str:
    if memory_bytes > 0:
        for profile, ceiling in zip(("small-8", "small-16", "small-24"), ("small-16", "small-24", "local")):
            if memory_bytes < PROFILES[ceiling].memory_gb * 2**30:
                return profile
    return "local" if requested.startswith("small-") else requested


def requirements(profile: str) -> Resources:
    """The supported profile's complete budget, including its backups and helper models."""
    return PROFILES[profile]


def recovery(memory_gb: float) -> str:
    minimum = PROFILES["small-8"].memory_gb
    if memory_gb < minimum:
        return f"Use a Mac with Apple silicon and at least {minimum} GB of memory."
    target = selected(int(memory_gb * 2**30))
    if target.startswith("small-"):
        return "Run ./vx up to use this Mac's supported profile. Sign in or add a key in Settings › System if asked."
    return "Close other heavy programs, then run ./vx up again."
