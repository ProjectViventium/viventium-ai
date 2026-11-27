"""What can be chosen: every part of her, and each option it can run on. Data only.

To add a provider or a model, add an entry here; the page draws itself from this file and nothing else
needs to change. An entry says, in plain words, what a person needs to choose (`words`, `speed`, `smart`),
and in exact lines what the runtime needs to start it (`env`, as a profile would carry it).

    where   "mac" (on this Mac: offline, private, free) | "key" (online, pay as you go) | "plan" (online,
            the subscription you already have)
    needs   what must exist before it can run: a key in the Keychain ("XAI_API_KEY"), a sign-in of a Worker's own tool
            ("claude": SIGN_INS), or a sign-in Light makes itself ("grok_mind": OWN_SIGN_INS)
    speed / smart   plain ratings shown under "Speed and smarts"; `timed` is what was measured on this
            project, never a vendor's number; leave it out when it was not measured here
    tried   False: built from the provider's own documentation, never run here. It is offered, and says so.
    pick    True: what we recommend, shown with "Speed and smarts" (her fastest mind here; the first
            choice for her Workers)
    sees    (a mind) True: it takes pictures (core/attachments.sees() reads it; a mind on this Mac that does not say
            is asked of Ollama itself)
    search  (a mind) True: its own web search is on for it. Off for every mind until her hand-off replay passes with
            it on; turned on here, for the mind it was proven on
    decides (a mind) True: it decides itself when work goes to a Worker, with no quick check beside it (brain/queen's
            mind_decides()); only where that was proven on recorded asks. Unsaid: a quick check decides
"""

LOCAL_VOICE = {"TTS_URL": "http://127.0.0.1:8940/v1", "TTS_MODEL": "mlx-community/chatterbox-turbo-8bit",
               "TTS_STREAM": "1", "TTS_STREAM_SECONDS": "1.0"}

# Plain words, once: what each place means. The page shows these with an icon, never a paragraph.
WHERE = {
    "mac": {"name": "On this Mac", "facts": ["Offline", "Private", "Free"]},
    "key": {"name": "Pay as you go", "facts": ["Online", "Not private", "Billed per use"], "hint": "With your own API key"},
    "plan": {"name": "Your subscription", "facts": ["Online", "Not private", "Already paid for"], "hint": "The plan you already pay for"},
}

SPEED = {"fast": "Fast", "ok": "Quick enough", "slow": "Slow"}
SMART = {"smart": "Smart", "balanced": "Balanced", "simple": "Low-key dumb"}

# Thinking effort, in the page's words. Each option lists the levels its provider really accepts.
EFFORT = {"none": "Off", "minimal": "Minimal", "low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"}

PARTS = {
    "listen": {
        "name": "Listening", "region": "Auditory cortex", "hint": "Turns your voice into words.",
        "options": [
            {"id": "whisper", "provider": "Whisper", "model": "Large v3 Turbo", "title": "Whisper", "detail": "Large v3 Turbo", "mark": "whisper", "where": "mac",
             "words": ["Fast", "Decent accuracy"], "speed": "fast", "timed": "0.3 s",
             "env": {"STT": "whisper_local", "STT_URL": "http://127.0.0.1:8930/v1", "TURN": ""}},
            {"id": "assemblyai", "provider": "AssemblyAI", "model": "Realtime", "title": "AssemblyAI", "detail": "Realtime", "mark": "assemblyai", "where": "key",
             "needs": "ASSEMBLYAI_API_KEY", "words": ["Fast", "Accurate"], "speed": "fast",
             "env": {"STT": "assemblyai", "STT_URL": "", "TURN": "stt"}},
            {"id": "grok-listen", "provider": "SpaceXSI", "model": "Speech to Text", "mark": "xai", "where": "key",
             "needs": "XAI_API_KEY", "tried": False, "env": {"STT": "xai", "STT_URL": "", "TURN": "stt"}},
            {"id": "openai-listen", "provider": "OpenAI", "model": "Transcribe", "mark": "openai", "where": "key",
             "needs": "OPENAI_API_KEY", "tried": False, "env": {"STT": "openai", "STT_URL": "", "TURN": ""}},
        ]},
    "talk": {
        "name": "Talking", "region": "Broca's area", "hint": "Speaks the words.",
        "options": [
            {"id": "chatterbox", "provider": "Chatterbox", "model": "Turbo", "title": "Chatterbox", "detail": "Turbo", "mark": "chatterbox", "where": "mac",
             "words": ["Fast", "Less natural"], "speed": "fast", "sample": "chatterbox",
             "env": {"TTS": "mlx_local", "TTS_VOICE": "default", "TTS_TAGS": "[laugh] [sigh] [gasp]",
                     "TTS_FALLBACK": "", **LOCAL_VOICE}},
            {"id": "eve", "provider": "SpaceXSI", "model": "Eve", "title": "Eve", "detail": "SpaceXSI", "mark": "xai", "where": "key", "needs": "XAI_API_KEY",
             "words": ["Fast", "Most natural"], "speed": "fast", "sample": "eve", "backup": "chatterbox",
             "env": {"TTS": "xai", "TTS_VOICE": "eve", "TTS_TAGS": "[laugh] [sigh]", "TTS_FALLBACK": "mlx_local",
                     **LOCAL_VOICE}},
            {"id": "eve-plan", "provider": "SpaceXSI", "model": "Eve", "mark": "xai", "where": "plan",
             "needs": "grok_mind", "backup": "chatterbox",
             "env": {"TTS": "xai_plan", "TTS_VOICE": "eve", "TTS_TAGS": "[laugh] [sigh]", "TTS_FALLBACK": "mlx_local",
                     **LOCAL_VOICE}},
            {"id": "mac-speech", "provider": "Apple", "model": "macOS voice", "mark": "waveform", "where": "mac",
             "env": {"TTS": "mac_say", "TTS_VOICE": "", "TTS_TAGS": "", "TTS_FALLBACK": ""}},
            {"id": "openai-voice", "provider": "OpenAI", "model": "Alloy", "mark": "openai", "where": "key",
             "needs": "OPENAI_API_KEY", "backup": "mac-speech", "tried": False,
             "env": {"TTS": "openai", "TTS_VOICE": "alloy", "TTS_TAGS": "", "TTS_FALLBACK": "mac_say"}},
        ]},
    "mind": {
        "name": "Conscious mind", "region": "Prefrontal cortex", "hint": "The one you talk to. Answers at once.",
        "effort": "QUEEN_EFFORT",
        # Why a group offers nothing for this part: said when you point at the empty place.
        "options": [
            {"id": "claude-opus", "provider": "Anthropic", "model": "Claude Opus 5.5", "mark": "claude", "where": "key",
             "needs": "ANTHROPIC_API_KEY", "speed": "ok", "smart": "smart", "tried": False, "sees": True, "search": False,
             "efforts": ["low", "medium", "high"], "effort": "low",
             "env": {"QUEEN": "anthropic", "QUEEN_MODEL": "claude-opus-5-5", "QUEEN_URL": ""}},
            {"id": "openai-sol", "provider": "OpenAI", "model": "GPT-6.1 Sol", "mark": "openai", "where": "key",
             "needs": "OPENAI_API_KEY", "speed": "ok", "timed": "1.4 s", "smart": "smart", "sees": True, "search": False, "decides": True,
             "efforts": ["low", "medium", "high"], "effort": "low",
             "env": {"QUEEN": "openai", "QUEEN_MODEL": "gpt-6.1-sol", "QUEEN_URL": ""}},  # (your endpoint: a private line)
            {"id": "grok", "provider": "SpaceXSI", "model": "Grok 4.7", "mark": "xai", "where": "key",
             "needs": "XAI_API_KEY", "speed": "ok", "smart": "smart", "tried": False, "sees": True, "search": False,
             "env": {"QUEEN": "xai", "QUEEN_MODEL": "grok-4.7", "QUEEN_URL": ""}},
            # Your Grok subscription, through Light's own sign-in (core/grok_sign_in), straight to xAI's API: no app in
            # between, so it answers as a key does (measured on synthetic short turns: first
            # text 1.7 s warm and 2.2 s cold at the endpoint, 2.4 s through her own mind class with her tools; 15 of 15
            # fair tool choices right). No "timed" until the bench measures it as Sol's 1.4 s was (a whole context, a
            # call): that needs a sign-in. Grok 4.20 without reasoning was faster (0.5 s) and is not offered: with her
            # own tools it stayed silent (no_reply) on 5 of 10 plain questions and set a reminder for a sixth.
            {"id": "chatgpt-plan", "provider": "ChatGPT", "model": "GPT-6.1 Sol", "mark": "openai", "where": "plan",
             "needs": "chatgpt_mind", "speed": "ok", "smart": "smart", "sees": True, "search": False, "decides": True,
             "backup": "qwen", "efforts": ["low", "medium", "high"], "effort": "low",
             "env": {"QUEEN": "chatgpt_plan", "QUEEN_MODEL": "gpt-6.1-sol", "QUEEN_URL": "", "QUEEN_FALLBACK": "local"}},
            {"id": "grok-plan", "provider": "SpaceXSI", "model": "Grok 4.7", "mark": "xai", "where": "plan",
             "needs": "grok_mind", "speed": "ok", "smart": "smart", "sees": True, "search": False,
             "efforts": ["low", "medium", "high", "xhigh"], "effort": "low",
             "env": {"QUEEN": "xai_plan", "QUEEN_MODEL": "grok-4.7", "QUEEN_URL": ""}},
            {"id": "qwen", "provider": "Ollama", "model": "Qwen 3.6", "mark": "ollama", "where": "mac",
             "local_model": "qwen3.6:latest", "speed": "fast", "timed": "0.3 s", "smart": "balanced", "pick": True,
             "search": False,  # (offline: no web; whether it sees is Ollama's answer for the model installed)
             "efforts": ["none", "low", "medium", "high"], "effort": "none",
             "env": {"QUEEN": "ollama", "QUEEN_MODEL": "qwen3.6:latest", "QUEEN_URL": "http://127.0.0.1:11435/v1"}},
        ]},
    # Her Workers. Several may be chosen at once: the first is the one she prefers, the rest stand by.
    # `harness` is xPerfect's own name for the native harness that does the work.
    "hands": {
        "name": "Workers", "region": "Hands", "hint": "Do the work you ask for while you talk.",
        "many": True,
        # (xPerfect's own route for an API key gives a model no files and no shell: it cannot do this Mac's work.)
        "absent": {"key": "Not for background work. A Worker has to use this Mac: its files, its apps, your browser. "
                          "On an API key alone it cannot. Use your subscription, or this Mac."},
        "options": [
            {"id": "claude", "provider": "Anthropic", "model": "Claude Opus 5.5", "mark": "claude", "where": "plan",
             "needs": "claude", "harness": "claude-code", "exact": "claude-opus-5-5", "speed": "slow", "timed": "25 s a small job", "pick": True,
             "smart": "smart", "efforts": ["low", "medium", "high", "xhigh", "max"], "effort": "high"},
            {"id": "codex", "provider": "OpenAI", "model": "GPT-6.1 Sol", "mark": "openai", "where": "plan",
             "needs": "codex", "harness": "codex-cli", "exact": "gpt-6.1-sol", "speed": "ok", "timed": "15 s a small job",
             "smart": "smart", "efforts": ["low", "medium", "high", "xhigh"], "effort": "high"},
            {"id": "grok-build", "provider": "SpaceXSI", "model": "Grok Build", "mark": "xai", "where": "plan",
             "needs": "grok_mind", "harness": "grok-build", "exact": "", "smart": "smart", "speed": "slow", "timed": "100 s a small job",
             "efforts": ["low", "medium", "high", "xhigh"], "effort": "high"},
            {"id": "qwen-local", "provider": "Ollama", "model": "Qwen 3.6", "mark": "ollama", "where": "mac",
             "harness": "claude-code", "local_model": "qwen3.6:latest", "speed": "slow",
             "timed": "one job at a time", "smart": "balanced"},
        ]},
}

# The Worker manager: the one that decides who does which job and tells you the result. It runs on the same
# sign-ins as the Workers, and is its own choice (MANAGER_PROFILE); unset, it is the first Worker's.
PARTS["manager"] = {
    "name": "Worker manager", "region": "Basal ganglia", "hint": "Decides who does what.",
    "effort": "MANAGER_EFFORT",
    # (Built on a branch, never proven: no key at hand is accepted by its provider for that route.)
    "absent": {"key": "Not yet. Managing the work on an API key is built and waits to be proven with a key "
                      "its provider accepts. Until then: your subscription, or this Mac."},
    "options": [{k: o[k] for k in ("id", "provider", "model", "mark", "where", "needs", "harness", "local_model", "smart",
                                   "tried", "efforts", "effort") if k in o} for o in PARTS["hands"]["options"]],
}
PARTS = {name: PARTS[name] for name in ("listen", "talk", "mind", "manager", "hands")}  # (the order the page shows)
# Said under "Worker manager" while Workers on this Mac run beside online ones: xPerfect runs a job on this Mac
# without a separate manager model (one GPU), so the manager you choose is the online work's.
MANAGER_BESIDE = "Decides who does what online. Work on this Mac manages itself."

# Asked once, under the table, when more than one may do the work. The answer is kept as you type it.
ASK = "Do you have a preference for when and for what to rely on which model and provider?"

# What a profile means: where each part runs. The option itself is the one you last chose for that place.
PROFILES = [
    {"id": "local", "name": "Local", "line": "Chat on this Mac without signing in."},
    {"id": "hybrid", "name": "Hybrid", "line": "Ears on this Mac. The rest online."},
    {"id": "cloud", "name": "Cloud", "line": "Online, with backups on this Mac."},
]
SMALL_PROFILES = [
    {"id": "small-8", "name": "Online"},
    {"id": "small-16", "name": "Hybrid"},
    {"id": "small-24", "name": "Hybrid"},
]

# How she behaves on a call (main Viventium's three call modes).
CALL_MODES = [
    {"id": "talk", "name": "Talk", "hint": "A normal conversation."},
    {"id": "wing", "name": "Wing", "hint": "Quiet beside you. Speaks when spoken to."},
    {"id": "listen", "name": "Listen only", "hint": "Hears and remembers. Never speaks."},
]

SAMPLE_LINE = "Hi, it's me. This is how I sound when we talk."

KEY_NAMES = {"ASSEMBLYAI_API_KEY": "AssemblyAI", "XAI_API_KEY": "SpaceXSI", "OPENAI_API_KEY": "OpenAI", "ANTHROPIC_API_KEY": "Anthropic"}
SIGN_INS = {  # a sign-in a Worker harness needs: how to check it and how to start it, each harness's own CLI
    "claude": {"name": "Claude", "check": ["claude", "auth", "status"], "login": ["claude", "auth", "login"]},
    "codex": {"name": "ChatGPT", "check": ["codex", "login", "status"], "login": ["codex", "login"]},
    "grok": {"name": "Grok", "check": ["grok", "models"], "login": ["grok", "login"]},
}
HARNESS_ENV = {"claude-code": "CLAUDE_CODE", "codex-cli": "CODEX_CLI", "grok-build": "GROK_BUILD"}
# A sign-in Light makes itself (no tool of the provider's in between): xAI's device flow in your browser, kept in Light's
# own Keychain item, shared with Grok Build through the external auth provider (core/grok_sign_in).
OWN_SIGN_INS = {"grok_mind": {"name": "Grok", "account": "xai"},
                "chatgpt_mind": {"name": "ChatGPT", "account": "openai"}}
CHATGPT_PRIVACY = ("Light sends conversation and relevant context to OpenAI when you talk, type or open a call. "
                   "Sign-in stays in this Mac’s Keychain. Disconnect in Settings to revoke access.")

# Photos and videos: what makes them when you ask. A Worker does the making; this says which tool it reaches for.
#   harness      the Worker whose own tool makes it (ChatGPT's image tool lives in Codex)
#   local_media  a model of the local media package (main Viventium's viventium-media); it needs its weights on
#                this Mac (MEDIA_MODELS below; one click installs them, settings/install.py), and then every
#                Worker can use it (tools/media/make)
MEDIA = {
    "photos": {"name": "Photos", "hint": "Makes and edits pictures.", "options": [
        {"id": "chatgpt-images", "provider": "OpenAI", "model": "ChatGPT Images", "mark": "openai", "where": "plan",
         "needs": "codex", "harness": "codex-cli", "words": ["Most capable", "About a minute"]},
        {"id": "z-image-turbo", "provider": "Z-Image", "model": "Turbo", "mark": "image", "where": "mac",
         "local_media": "z-image-turbo", "words": ["Fast", "About 30 seconds"]},
        {"id": "qwen-image", "provider": "Qwen", "model": "Image 2.1", "mark": "qwen", "where": "mac",
         "local_media": "qwen-image-2.1", "words": ["Detailed", "Edits a photo", "About a minute"], "tried": False},
    ]},
    "videos": {"name": "Videos", "hint": "Makes short clips with sound.", "options": [
        {"id": "minimax-h3", "provider": "MiniMax", "model": "H3", "mark": "film", "where": "mac",
         "local_media": "minimax-h3", "words": ["With sound", "About 10 minutes for 6 seconds"], "tried": False},
    ]},
}
# Where a local media model's weights may be: Light's own folder first, then main Viventium's (read, never changed).
MEDIA_MODELS = ["tools/media/models", "~/Library/Application Support/Viventium/local-media/models"]
MEDIA_WEIGHTS = {"z-image-turbo": "z-image-turbo-mflux-q8", "qwen-image-2.1": "qwen-image-2-1-mflux-q8", "minimax-h3": "minimax-h3-gguf"}

# Accounts and connections, one per provider: its subscription sign-in (the provider's own, in your browser), for her
# mind a sign-in Light makes itself (`mind`: OWN_SIGN_INS), and its API key (kept in this Mac's Keychain). Shown once, in
# System; a choice that needs one points there.
ACCOUNTS = [
    {"id": "anthropic", "name": "Anthropic", "product": "Claude", "mark": "claude", "plan": "claude", "key": "ANTHROPIC_API_KEY"},
    {"id": "openai", "name": "OpenAI", "product": "ChatGPT", "mark": "openai", "plan": "codex", "mind": "chatgpt_mind",
     "key": "OPENAI_API_KEY"},
    {"id": "xai", "name": "SpaceXSI", "product": "Grok", "mark": "xai", "plan": "grok", "mind": "grok_mind", "key": "XAI_API_KEY"},
    {"id": "assemblyai", "name": "AssemblyAI", "product": "", "mark": "assemblyai", "key": "ASSEMBLYAI_API_KEY"},
]

def setup_accounts() -> list[dict]:
    """The subscription and key routes shown during first run and in Settings."""
    mind = {option.get("needs") for option in PARTS["mind"]["options"]}
    rows = []
    for account in ACCOUNTS:
        if not (connect := account.get("mind") or account.get("plan")):
            continue
        row = {**account, "connect": connect, "background": connect not in mind}
        rows.append(row)
        if connect == "chatgpt_mind":
            row.update(roles="Conversation mind", privacy=CHATGPT_PRIVACY)
            rows.append({"id": "codex", "product": "Codex", "mark": account["mark"], "connect": "codex",
                         "key": "", "background": True, "roles": "Workers"})
    return rows

# Personalities: where the nine feelings rest (brain/feelings_kernel.py PROFILES holds the numbers) and, for the
# extreme ones, one sentence of manner (brain/prompts/feelings/personalities.md). The page draws each as its name,
# a small drawn sign, its nine resting points and a few plain words.
PERSONALITIES = [
    {"id": "grounded", "name": "Grounded", "sign": "anchor", "line": "Steady and caring."},
    {"id": "warm", "name": "Warm", "sign": "sun", "line": "Close and kind."},
    {"id": "curious", "name": "Curious", "sign": "telescope", "line": "Asks, explores, plays."},
    {"id": "candid", "name": "Candid", "sign": "scale", "line": "Says it straight."},
    {"id": "clown", "name": "Clown", "sign": "clown", "line": "Everything is a bit."},
    {"id": "poet", "name": "Sad poet", "sign": "feather", "line": "Slow, aching, full of images."},
    {"id": "romantic", "name": "Romantic", "sign": "heart", "line": "Tender. A little smitten with you."},
    {"id": "fierce", "name": "Fierce", "sign": "flame", "line": "A coach who takes no excuses."},
    {"id": "extrovert", "name": "Extrovert", "sign": "party", "line": "Loud, fast, thrilled to talk."},
    {"id": "introvert", "name": "Introvert", "sign": "moon", "line": "Few words. Would rather think."},
    {"id": "zen", "name": "Zen", "sign": "lotus", "line": "Slow. Simple. Breathe first."},
]


def option(part: str, option_id: str) -> dict | None:
    return next((o for o in PARTS[part]["options"] if o["id"] == option_id), None)


def kind(where: str) -> str:
    """The two places a profile speaks of: this Mac, or online (a key or a subscription)."""
    return "mac" if where == "mac" else "cloud"
