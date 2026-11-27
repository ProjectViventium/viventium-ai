"""Resolve the shipped voice default. A saved voice is never an automatic choice."""
import os


def resolve(env: dict, *, subscription: bool | None = None, key: bool | None = None) -> dict:
    if env.get("TTS") != "auto":
        return dict(env)
    from settings import catalog, runtime

    off = set(env.get("KEYS_OFF", "").split())
    if subscription is None:
        subscription = runtime.own_signed_in("grok_mind")
    if key is None:
        key = runtime.has_key("XAI_API_KEY", env)
    subscription = subscription and "grok_mind" not in off and not runtime.own_is_off("grok_mind")
    key = key and "XAI_API_KEY" not in off and not runtime.own_is_off("XAI_API_KEY")
    local = env.get("SMALL_MAC_TIER") not in ("8", "16")
    name = "eve-plan" if subscription else "eve" if key else "chatterbox" if local else "mac-speech"
    voice = dict(catalog.option("talk", name)["env"])
    # Keep this instance's local endpoint/model, including isolated test servers.
    for setting in catalog.LOCAL_VOICE:
        if env.get(setting):
            voice[setting] = env[setting]
    if name in ("eve", "eve-plan") and not local:
        voice["TTS_FALLBACK"] = "mac_say"
    return {**env, **voice}


def apply() -> None:
    if os.environ.get("TTS") == "auto":
        os.environ.update(resolve(dict(os.environ)))
