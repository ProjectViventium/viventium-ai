"""Feelings kernel: the nine bands, Nature, decay, the capsule and typed reactions. Pure structure.

A port of main Viventium's Feelings (LibreChat packages/api/src/feelings: kernel, service, types),
plus the Viventium Feelings plugin's Nature profiles and capsule size limit. Runtime owns the shape
(bands, levels, decay, the 3/8/15 deltas, validation); the appraiser model owns what a moment means.
The only I/O is reading the prompt data in brain/prompts/feelings.

The bands, their resting points and their half-lives are engineered software state: a working hypothesis about
which pulls make a companion useful (loosely after interoception and salience), not a model of biology and not a
claim of consciousness. What they do to her replies is measured, never assumed (tests/feelings_eval.py: the same ask
under contrasting states, Off and the shipped default).

What the owner may set per band (settings: Personality, Advanced; the requirement: each band's thresholds and ranges
can be seen and changed, and so can what is said at each level): where its five levels begin (levelBounds), what
each level says in the capsule in place of main's words (levelWords), and his own words added to a level (additions).
"""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import NamedTuple

PROMPTS = Path(__file__).resolve().parent / "prompts" / "feelings"


class Band(NamedTuple):
    id: str
    name: str
    low: str          # its two poles and level words are for people; the capsule uses felt causes
    high: str
    nature: float     # default Nature (the Grounded profile)
    half_life: float  # minutes for Current to come halfway back to Nature
    color: str
    description: str
    words: tuple


BANDS = (
    Band("energy", "Energy", "tired", "energetic", 56, 240, "#e7b14a",
         "Available activation and cognitive capacity.",
         ("depleted", "subdued", "steady", "energized", "electric")),
    Band("mood", "Mood", "sad", "happy", 58, 360, "#d889c4",
         "Background emotional pleasantness, from sadness toward happiness.",
         ("deeply sad", "low", "okay", "happy", "radiant")),
    Band("drive", "Drive", "unmotivated", "determined", 62, 480, "#7397e8",
         "Persistence and effort after a goal is chosen.",
         ("disengaged", "unhurried", "purposeful", "driven", "fiercely determined")),
    Band("curiosity", "Curiosity", "uninterested", "absorbed", 66, 45, "#58b9c9",
         "Pull toward information, novelty, and exploration.",
         ("uninterested", "open", "curious", "fascinated", "absorbed")),
    Band("vigilance", "Vigilance", "at ease", "highly alert", 68, 20, "#8b7bd3",
         "Attention to uncertainty, risk, error, and boundaries.",
         ("at ease", "aware", "watchful", "on guard", "highly alert")),
    Band("care", "Care", "detached", "deeply caring", 74, 1440, "#d47c8f",
         "The outward pull to tend, help, and protect.",
         ("detached", "receptive", "caring", "deeply caring", "intensely caring")),
    Band("connection", "Connection", "self-contained", "wanting closeness", 52, 480, "#4eb394",
         "The inward pull toward affiliation and closeness.",
         ("self-contained", "open", "drawn to connection", "wanting closeness", "strongly drawn to connection")),
    Band("openness", "Openness", "guarded", "fully expressive", 55, 180, "#ef8e68",
         "How freely the inner state becomes visible in expression.",
         ("closed off", "guarded", "contained", "emotionally open", "fully expressive")),
    Band("play", "Play", "serious", "playful", 48, 90, "#91bd52",
         "Flexible, humorous, non-serious exploration.",
         ("serious", "light", "playful", "mischievous", "exuberant")),
)
BAND_IDS = tuple(band.id for band in BANDS)
LEVEL_IDS = ("level_0", "level_1", "level_2", "level_3", "level_4")  # 0-19 … 80-100 by default; 0 and 4 are "required"
DEFAULT_BOUNDS = (20, 40, 60, 80)  # where levels 1 to 4 begin (main: 0-19, 20-39, 40-59, 60-79, 80-100)
MIN_LEVEL_WIDTH = 5  # each of a band's five levels keeps at least five whole points of 0-100
MODEL_CAUSES = ("playful_exchange", "connection_bid", "care_signal", "progress", "setback", "new_information",
                "uncertainty", "risk_or_boundary", "fatigue", "conflict", "praise", "loss", "surprise", "other")
CAUSES = MODEL_CAUSES + ("manual_adjustment", "reset_to_nature")
DIRECTIONS = ("up", "down")
STRENGTHS = {"slight": 3, "clear": 8, "strong": 15}
SOURCE_TYPES = ("user_turn", "manual", "reset")
ACTIVATION_MODES = ("always", "classified", "disabled")

# Nature profiles (from the plugin). Grounded: steady, caring, alert, minimally theatrical. Candid: direct,
# guarded against easy agreement. Warm: relational, caring, open, grounded in judgment. Curious:
# exploratory, energized by open questions, lightly playful.
PROFILES = {
    "grounded": {band.id: band.nature for band in BANDS},
    "candid": dict(energy=56, mood=54, drive=66, curiosity=64, vigilance=74, care=66, connection=44, openness=78, play=35),
    "warm": dict(energy=55, mood=62, drive=58, curiosity=62, vigilance=54, care=86, connection=76, openness=72, play=56),
    "curious": dict(energy=62, mood=60, drive=64, curiosity=86, vigilance=60, care=70, connection=56, openness=70, play=68),
    # Light's own, for people who want to hear the extremes (people come to try them and play with them). Each is
    # only where the nine feelings rest; nothing else is prompted.
    # (GPT-6.1 Sol: three rows pulled against the manner and moved: the Extrovert's Play at its top level asked
    # for "ridiculous riffs" and read as the Clown (82 -> 64); the Fierce coach's Vigilance at its top made her cautious
    # (88 -> 50); the Sad poet's Care at its top made her tend, like the Romantic (82 -> 50), and its Play at the bottom
    # asked for the moment "literal, orderly", against her images (16 -> 30). tests/personality_eval.py)
    "clown": dict(energy=90, mood=92, drive=45, curiosity=72, vigilance=14, care=58, connection=80, openness=96, play=99),
    "poet": dict(energy=28, mood=12, drive=34, curiosity=78, vigilance=38, care=50, connection=62, openness=94, play=30),
    "romantic": dict(energy=64, mood=80, drive=46, curiosity=60, vigilance=24, care=96, connection=98, openness=92, play=58),
    "introvert": dict(energy=36, mood=50, drive=62, curiosity=82, vigilance=64, care=58, connection=10, openness=16, play=22),
    "extrovert": dict(energy=96, mood=84, drive=74, curiosity=66, vigilance=30, care=68, connection=96, openness=92, play=64),
    "fierce": dict(energy=92, mood=44, drive=99, curiosity=48, vigilance=50, care=34, connection=22, openness=84, play=8),
    "zen": dict(energy=34, mood=66, drive=18, curiosity=52, vigilance=8, care=72, connection=48, openness=46, play=30),
}
# Where a personality rested before it was improved (above): a saved state still exactly at one of these, every
# band as it shipped, was never moved by hand, and takes the personality as it ships now (normalize_state). One he moved
# by hand, or whose profile is "custom", is his and stays as it is (before, improvements never reached saved presets).
SHIPPED_BEFORE = {
    "poet": [dict(energy=28, mood=12, drive=34, curiosity=78, vigilance=38, care=82, connection=62, openness=94, play=16)],
    "extrovert": [dict(energy=96, mood=84, drive=74, curiosity=66, vigilance=30, care=68, connection=96, openness=92, play=82)],
    "fierce": [dict(energy=92, mood=44, drive=99, curiosity=48, vigilance=88, care=34, connection=22, openness=84, play=8)],
}
MIN_HALF_LIFE, MAX_HALF_LIFE = 5, 7 * 24 * 60  # minutes: how fast a feeling may come back to where it rests

MAX_TRAIL = 90             # typed changes kept (a dashboard draws each band's recent path from them)
TRAIL_CONTEXT = 10         # of which the appraiser sees the latest
MAX_INNER_STATE = 280
MAX_ADDITION = 1200        # optional owner text added to one band's level
MAX_CAPSULE_BYTES = 2640   # bounds range additions; main's own wording is never cut (up to ~2,850 bytes). The plugin's
# 2,400, plus the 240 bytes of the sentence that says the rows are private and how she answers when asked why she feels
# so: the room for his words stays
MAX_PROCESSED_KEYS = 100
# The user's words are appraised whole up to this many characters (about 30,000 tokens, inside every appraiser's room:
# her quick helpers online, this Mac's model). At 16,000 an 18,026-character message lost its middle, and with
# it a constraint, with nothing saying so. Past it: an excerpt that says exactly what it left out.
# A stated exception to "his words whole on every path": an appraisal
# is a mood signal about the moment, not work on his words, so beyond this it reads the start and the end with the span
# left out named; his words still go whole to her mind and to every Worker (brain/queen.py, core/attachments.py).
MAX_STIMULUS_CHARS = 120_000
DEFAULT_REACTION_INSTRUCTION = ("React to what genuinely moves Viventium. Let each change match how much the moment "
                                "matters. Move only the feelings the moment actually touches, and leave nature unchanged.")
LEGACY_REACTION_INSTRUCTIONS = {"React to what genuinely moves Viventium. Prefer small natural changes. Move only "
                                "the feelings the moment actually touches, and leave nature unchanged."}
# Main's classifier answer format (BackgroundCortexService DEFAULT_ACTIVATION_RESPONSE_FORMAT), for "classified".
ACTIVATION_FORMAT = ('Respond with a JSON object:\n{\n  "should_activate": true,\n  "confidence": 1.0,\n'
                     '  "reason": "2-4 explanatory words"\n}')


def prompt(name: str) -> str:
    """A Feelings prompt's text in force: brain/prompts/feelings/<name>.md as it ships (its front matter is metadata),
    or the owner's own text for it, through the prompt ledger (brain/prompts: in force from her next turn)."""
    from brain import prompts as ledger
    return ledger.text(f"prompts/feelings/{name}")


def policy() -> dict:
    """The capsule wording (main's feelings.capsule_policy): the frame, two directives, a cause per level."""
    words = json.loads(prompt("capsule_policy"))
    if not all(words.get(key) for key in ("frame", "behavior", "directAnswer")) or not all(
            words["levels"].get(band, {}).get(level) for band in BAND_IDS for level in LEVEL_IDS):
        raise ValueError("capsule_policy_incomplete")
    return words


def manner(profile_id, names: dict | None = None) -> str:
    """The note for a personality that has a manner of its own ("" for the others, and for none)."""
    words = json.loads(prompt("personalities"))
    text = words["manners"].get(profile_id or "")
    return words["note"].format(name=(names or {}).get(profile_id, profile_id), manner=text) if text else ""


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value, default: dt.datetime) -> dt.datetime:
    try:
        t = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return default
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _number(value, default: float) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else default


def clamp(value) -> float:
    return min(100.0, max(0.0, float(_number(value, 0.0))))


SETTLED = 0.5  # within half a point of its Nature, a feeling has come back: it rests there exactly


def decay(stored, nature, minutes: float, half_life: float) -> float:
    """Current, `minutes` after it was set: nature + (current - nature) * 2^(-minutes / half-life), and Nature itself
    once within SETTLED of it. (Play resting at 80, the edge of its top level, came back to 79.99 and stayed
    one level short, so his words for that level were never sent.)"""
    stored, nature = clamp(stored), clamp(nature)
    if not _number(half_life, 0) > 0:
        return nature
    value = clamp(nature + (stored - nature) * 2 ** (-max(0.0, _number(minutes, 0.0)) / half_life))
    return nature if abs(value - nature) < SETTLED else value


def materialize(stored: dict | None, now: dt.datetime) -> dict:
    """Every band as of `now`, Current decayed lazily since it last changed (no timer runs).
    A clock that went backwards counts as no time; a disabled band keeps decaying."""
    bands = {}
    for band in BANDS:
        saved = (stored or {}).get(band.id)
        saved = saved if isinstance(saved, dict) else {}
        nature = clamp(_number(saved.get("baseline"), band.nature))
        half_life = _number(saved.get("halfLifeMinutes"), band.half_life)
        half_life = half_life if half_life > 0 else band.half_life
        minutes = (now - parse_time(saved.get("updatedAt"), now)).total_seconds() / 60
        current = decay(_number(saved.get("current"), nature), nature, minutes, half_life)
        bands[band.id] = {"baseline": nature, "current": current, "halfLifeMinutes": half_life,
                          "enabled": saved.get("enabled") is not False, "updatedAt": iso(now)}
    return bands


def bounds_of(value) -> tuple:
    """A band's four bounds between its five levels, as the owner set them: four whole numbers, rising, each level at
    least MIN_LEVEL_WIDTH wide (level 0 starts at 0 and level 4 ends at 100). Anything else: main's default."""
    if isinstance(value, (list, tuple)) and len(value) == 4 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and float(v).is_integer() for v in value):
        bounds = tuple(int(v) for v in value)
        edges = (0, *bounds, 101)
        if all(b - a >= MIN_LEVEL_WIDTH for a, b in zip(edges, edges[1:])):
            return bounds
    return DEFAULT_BOUNDS


def valid_bounds(value) -> bool:
    """Whether these bounds are taken as given (bounds_of() falls back to the default otherwise)."""
    return isinstance(value, (list, tuple)) and len(value) == 4 and bounds_of(value) == tuple(value)


def normalize_bounds(value) -> dict:
    """The owner's levelBounds, {band: [b1, b2, b3, b4]}, kept only where valid and not the default."""
    out = {}
    for band in BANDS:
        given = value.get(band.id) if isinstance(value, dict) else None
        if given is not None and valid_bounds(given) and tuple(given) != DEFAULT_BOUNDS:
            out[band.id] = [int(v) for v in given]
    return out


def level(value, bounds=DEFAULT_BOUNDS) -> int:
    """Its level, 0 to 4: how many of its band's bounds it has reached (by default 0-19, 20-39, 40-59, 60-79, 80-100)."""
    current = clamp(value)
    return sum(current >= bound for bound in bounds_of(bounds))


def normalize_additions(value) -> dict:
    """The owner's optional text per band level: whitespace collapsed, 1-1,200 characters, else dropped."""
    additions = {}
    for band in BANDS:
        levels = value.get(band.id) if isinstance(value, dict) else None
        for level_id in LEVEL_IDS:
            text = levels.get(level_id) if isinstance(levels, dict) else None
            text = " ".join(text.split()) if isinstance(text, str) else ""
            if 0 < len(text) <= MAX_ADDITION:
                additions.setdefault(band.id, {})[level_id] = text
    return additions


def render_capsule(enabled: bool, bands: dict, additions=None, words=None, bounds=None) -> tuple[str, bool]:
    """The words-only capsule (main's v2), and whether range additions were dropped to fit the size limit.
    words: the owner's levelWords, his text for a level in place of main's (kept whole, like main's own: only additions
    give way); bounds: his levelBounds, where each band's levels begin."""
    if not enabled:
        return "", False
    words, bounds = normalize_additions(words), normalize_bounds(bounds)
    text = _capsule(bands, normalize_additions(additions), words, bounds)
    if additions and len(text.encode()) > MAX_CAPSULE_BYTES:
        return _capsule(bands, {}, words, bounds), True
    return text, False


def _capsule(bands: dict, additions: dict, owned: dict | None = None, bounds: dict | None = None) -> str:
    """One row per enabled band, in order: its level's felt cause (the owner's words for it, else main's) plus any
    addition. Extreme levels are required; with fewer than two, the strongest non-neutral pulls are promoted until two are."""
    words, owned, bounds = policy(), owned or {}, bounds or {}
    active = [(band, bands[band.id]["current"], level(bands[band.id]["current"], bounds.get(band.id))) for band in BANDS
              if band.id in bands and bands[band.id]["enabled"]]
    if not active:
        return ""
    required = {band.id for band, _, at in active if at in (0, 4)}
    if len(required) < 2:
        moderate = sorted((row for row in active if row[2] in (1, 3)), key=lambda row: -abs(row[1] - 50))
        for band, _, _ in moderate:
            required.add(band.id)
            if len(required) >= 2:
                break
    rows = []
    for band, _, at in active:
        level_id = LEVEL_IDS[at]
        addition = additions.get(band.id, {}).get(level_id)
        label = f"required {band.id}" if band.id in required else band.id
        says = owned.get(band.id, {}).get(level_id) or words["levels"][band.id][level_id]
        rows.append(f"{label}: {says}" + (f" {addition}" if addition else ""))
    return "\n".join(["<viventium_feeling_state>", words["frame"], words["behavior"], *rows,
                      words["directAnswer"], "</viventium_feeling_state>"])


def bounded_stimulus(text: str) -> str:
    """The user's words, whole up to MAX_STIMULUS_CHARS. Longer: its start and its end, with the exact span left out
    named between them (characters a to b of n), never a silent cut."""
    if len(text) <= MAX_STIMULUS_CHARS:
        return text
    half = MAX_STIMULUS_CHARS // 2
    left_out = (half + 1, len(text) - half)
    return (f"{text[:half]}\n[characters {left_out[0]:,} to {left_out[1]:,} of this {len(text):,}-character message are "
            f"left out here; the whole message is in the conversation record]\n{text[-half:]}")


def stimulus_key(reaction_id: str) -> str:
    """The one-way key a reaction is remembered by (main: sha256, 24 hex), so it never applies twice."""
    return hashlib.sha256(str(reaction_id).encode()).hexdigest()[:24]


def reaction_input(bands: dict, trail: list, stimulus: str) -> str:
    """The appraiser's whole input (main): every band's Current, Nature, half-life and enabled flag, the last
    ten typed changes, and the user's latest words, as one JSON object (the words are a quoted value)."""
    return json.dumps({
        "currentState": {band_id: {"current": round(band["current"], 3), "nature": round(band["baseline"], 3),
                                   "halfLifeMinutes": band["halfLifeMinutes"], "enabled": band["enabled"]}
                         for band_id, band in bands.items()},
        "recentTrail": trail[-TRAIL_CONTEXT:],
        "latestExternalUserStimulus": stimulus,
    }, ensure_ascii=False)


def output_contract() -> str:
    """The answer shape and closed enums, generated from the kernel so the prompt cannot drift (main)."""
    return (f'Return exactly one JSON object with this shape and no other text:\n{{"changes":[{{"band":"{"|".join(BAND_IDS)}",'
            f'"direction":"up|down","strength":"slight|clear|strong","cause":"{"|".join(MODEL_CAUSES)}"}}],'
            f'"innerState":"one first-person sentence, 1-{MAX_INNER_STATE} characters"}}\n'
            "Strength semantics: slight = subtle but real movement; clear = unmistakable movement; strong = pronounced "
            "movement with high felt impact. Select proportionally; do not default to slight.")


def unfence(raw) -> str:
    text = str(raw or "").strip()
    if len(text) >= 6 and text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        text = text[4:].strip() if text[:4].lower() == "json" else text
    return text


def parse_appraisal(raw) -> tuple[list, str]:
    """The appraiser's answer, validated: up to nine changes (each band at most once; band, direction,
    strength and cause from closed lists; extra keys in a change are dropped) and one Inner state line.
    Anything else raises ValueError with an issue code."""
    try:
        answer = json.loads(unfence(raw))
    except ValueError:
        raise ValueError("invalid_json") from None
    if not isinstance(answer, dict) or set(answer) - {"changes", "innerState"}:
        raise ValueError("invalid_shape")
    changes = answer.get("changes")
    if not isinstance(changes, list) or len(changes) > len(BAND_IDS):
        raise ValueError("invalid_changes")
    clean = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("invalid_change")
        values = [change.get(key) if isinstance(change.get(key), str) else None
                  for key in ("band", "direction", "strength", "cause")]
        for value, allowed, issue in zip(values, (BAND_IDS, DIRECTIONS, STRENGTHS, MODEL_CAUSES),
                                         ("invalid_band", "invalid_direction", "invalid_strength", "invalid_cause")):
            if value not in allowed:
                raise ValueError(issue)
        if values[0] in {c["band"] for c in clean}:
            raise ValueError("duplicate_band")
        clean.append(dict(zip(("band", "direction", "strength", "cause"), values)))
    inner = answer.get("innerState")
    inner = inner.strip() if isinstance(inner, str) else ""
    if not 0 < len(inner) <= MAX_INNER_STATE or "\n" in inner or "\r" in inner:
        raise ValueError("invalid_inner_state")
    return clean, inner


def apply_changes(bands: dict, changes: list, now: dt.datetime) -> tuple[dict, list]:
    """Typed changes as relative moves on Current (slight 3, clear 8, strong 15; Nature never moves).
    Disabled bands ignore them; a move clamped to nothing leaves no trail."""
    bands, trail = {band_id: dict(band) for band_id, band in bands.items()}, []
    for change in changes[:len(BAND_IDS)]:
        band = bands.get(change["band"])
        if not band or not band["enabled"]:
            continue
        before = clamp(band["current"])
        after = clamp(before + STRENGTHS[change["strength"]] * (1 if change["direction"] == "up" else -1))
        if after == before:
            continue
        band.update(current=after, updatedAt=iso(now))
        trail.append({"timestamp": iso(now), "band": change["band"], "direction": change["direction"],
                      "strength": change["strength"], "sourceType": "user_turn", "cause": change["cause"],
                      "before": before, "after": after})
    return bands, trail


def strength_for(delta: float) -> str:
    return "slight" if delta <= 4 else "clear" if delta <= 10 else "strong"


def apply_nature(bands: dict, values: dict, now: dt.datetime) -> tuple[dict, list]:
    """A Nature profile: each band's resting value, with Current reset to it (manual trail entries)."""
    bands, trail = {band_id: dict(band) for band_id, band in bands.items()}, []
    for band_id, value in values.items():
        before = bands[band_id]["current"]
        bands[band_id].update(baseline=value, current=value, updatedAt=iso(now))
        if value != before:
            trail.append({"timestamp": iso(now), "band": band_id, "direction": "up" if value > before else "down",
                          "strength": strength_for(abs(value - before)), "sourceType": "manual",
                          "cause": "manual_adjustment", "before": before, "after": value})
    return bands, trail


def new_health() -> dict:
    """The last reaction's outcome, and the route asked for versus the route that answered."""
    return {"status": "never"} | dict.fromkeys((
        "lastStartedAt", "lastCompletedAt", "lastDurationMs", "lastErrorClass", "lastErrorDetail", "lastSkipReason",
        "requestedProvider", "requestedModel", "lastUsedProvider", "lastUsedModel", "lastFallbackUsed",
        "lastPrimaryErrorClass", "lastPassedOver"))


def new_state(profile: str, now: dt.datetime) -> dict:
    """A first state: the chosen Nature (else Grounded), Current at rest, Feelings on."""
    profile = profile if profile in PROFILES else "grounded"
    stamp = iso(now)
    return {"schemaVersion": 1, "version": 0, "controlEpoch": 0, "enabled": True, "profileId": profile, "mannerId": profile,
            "bands": {band.id: {"baseline": PROFILES[profile][band.id], "current": PROFILES[profile][band.id],
                                "halfLifeMinutes": band.half_life, "enabled": True, "updatedAt": stamp} for band in BANDS},
            "rangePromptOverrides": {}, "levelBounds": {}, "levelWords": {}, "reactionInstruction": DEFAULT_REACTION_INSTRUCTION,
            "reactionActivationMode": "always", "innerState": None, "trail": [], "reactionHealth": new_health(),
            "processedStimulusKeys": [], "createdAt": stamp, "updatedAt": stamp}


def _trail_entry(entry, now: dt.datetime) -> dict | None:
    if not (isinstance(entry, dict) and entry.get("band") in BAND_IDS and entry.get("direction") in DIRECTIONS
            and entry.get("strength") in STRENGTHS and entry.get("cause") in CAUSES
            and entry.get("sourceType") in SOURCE_TYPES):
        return None
    before, after = _number(entry.get("before"), -1), _number(entry.get("after"), -1)
    if not (0 <= before <= 100 and 0 <= after <= 100):
        return None
    return {key: entry[key] for key in ("band", "direction", "strength", "cause", "sourceType")} | {
        "timestamp": iso(parse_time(entry.get("timestamp"), now)), "before": before, "after": after}


def normalize_state(raw, profile: str, now: dt.datetime) -> dict:
    """A stored state (Light's, or the plugin's, which has the same shape), checked field by field:
    an invalid field takes its default. Not a state document at all raises ValueError."""
    if not isinstance(raw, dict) or not isinstance(raw.get("bands"), dict):
        raise ValueError("state_invalid")
    state = new_state(profile, now)
    for band in BANDS:
        saved = raw["bands"].get(band.id)
        if isinstance(saved, dict):
            nature = clamp(_number(saved.get("baseline"), band.nature))
            half_life = _number(saved.get("halfLifeMinutes"), band.half_life)
            state["bands"][band.id] = {"baseline": nature, "current": clamp(_number(saved.get("current"), nature)),
                                       "halfLifeMinutes": half_life if half_life > 0 else band.half_life,
                                       "enabled": saved.get("enabled") is not False,
                                       "updatedAt": iso(parse_time(saved.get("updatedAt"), now))}
    if isinstance(raw.get("enabled"), bool):
        state["enabled"] = raw["enabled"]
    for key in ("version", "controlEpoch"):
        if isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool) and raw[key] >= 0:
            state[key] = raw[key]
    if raw.get("profileId") in (*PROFILES, "custom"):
        state["profileId"] = raw["profileId"]
    was = {band.id: state["bands"][band.id]["baseline"] for band in BANDS}
    if any(was == old for old in SHIPPED_BEFORE.get(state["profileId"], [])):  # (a preset as it shipped then: as it ships now)
        for band in BANDS:
            state["bands"][band.id]["baseline"] = PROFILES[state["profileId"]][band.id]
    # The personality whose manner she keeps (a resting point moved by hand makes the profile "custom", not the manner).
    state["mannerId"] = raw["mannerId"] if raw.get("mannerId") in PROFILES else state["profileId"] if state["profileId"] in PROFILES else None
    state["rangePromptOverrides"] = normalize_additions(raw.get("rangePromptOverrides"))
    state["levelBounds"] = normalize_bounds(raw.get("levelBounds"))
    state["levelWords"] = normalize_additions(raw.get("levelWords"))
    instruction = raw.get("reactionInstruction").strip() if isinstance(raw.get("reactionInstruction"), str) else ""
    if 0 < len(instruction) <= 4000 and instruction not in LEGACY_REACTION_INSTRUCTIONS:
        state["reactionInstruction"] = instruction
    if raw.get("reactionActivationMode") in ACTIVATION_MODES:
        state["reactionActivationMode"] = raw["reactionActivationMode"]
    inner = raw.get("innerState")
    text = inner.get("text").strip() if isinstance(inner, dict) and isinstance(inner.get("text"), str) else ""
    if 0 < len(text) <= MAX_INNER_STATE and "\n" not in text and "\r" not in text:
        state["innerState"] = {"text": text, "generatedAt": iso(parse_time(inner.get("generatedAt"), now))}
    trail = [_trail_entry(entry, now) for entry in raw.get("trail", [])] if isinstance(raw.get("trail"), list) else []
    state["trail"] = [entry for entry in trail if entry][-MAX_TRAIL:]
    if isinstance(raw.get("reactionHealth"), dict):
        state["reactionHealth"] |= {k: v for k, v in raw["reactionHealth"].items() if k in state["reactionHealth"]}
    keys = raw.get("processedStimulusKeys") if isinstance(raw.get("processedStimulusKeys"), list) else []
    state["processedStimulusKeys"] = [key for key in keys if isinstance(key, str) and len(key) == 24
                                      and all(c in "0123456789abcdef" for c in key)][-MAX_PROCESSED_KEYS:]
    user = raw.get("userSet") if isinstance(raw.get("userSet"), dict) else {}  # what the user chose themself
    state["userSet"] = {key: value for key, value in user.items()
                        if (key == "paused" and value is True) or (key == "nature" and value in (*PROFILES, "custom"))}
    state["createdAt"] = iso(parse_time(raw.get("createdAt"), now))
    state["updatedAt"] = iso(parse_time(raw.get("updatedAt"), now))
    return state
