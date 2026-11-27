"""Ears and mouth. The active profile (profiles/*.env) picks the providers.

Cloud providers talk over an HTTP session that LiveKit gives only inside a call; outside one (Telegram
voice notes) the caller passes its own."""
import asyncio
import os
import tempfile
import wave
from pathlib import Path

import aiohttp
import openai as openai_sdk
from livekit.agents import APIConnectionError, APIStatusError, tokenize, utils
from livekit.agents import tts as lk_tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins import assemblyai, openai, xai

KEY_OF = {"xai": "XAI_API_KEY"}  # (an online voice and the key it needs)


def vocabulary() -> list[str]:
    """His own words for her ears to know (STT_VOCABULARY: names, places, comma-separated), given to the chosen engine
    its own way: Whisper as its prompt, AssemblyAI as its key terms. None unless he gives them; never a replacement of
    what was heard after the fact ("optional user-authorized vocabulary uses the selected engine's native
    support")."""
    return [word.strip() for word in os.environ.get("STT_VOCABULARY", "").split(",") if word.strip()]


def stt(http_session=None):
    provider = os.environ.get("STT", "whisper_local")
    words = vocabulary()
    if provider == "whisper_local":  # whisper.cpp server, OpenAI-compatible endpoint
        return openai.STT(base_url=os.environ["STT_URL"], api_key="local", model="whisper-1",
                          language=os.environ.get("STT_LANGUAGE", "en"),
                          **({"prompt": "Names and words that may come up: " + ", ".join(words) + "."} if words else {}))
    if provider == "assemblyai":  # streaming only; ASSEMBLYAI_API_KEY
        return assemblyai.STT(http_session=http_session,
                              **({"model": os.environ["STT_MODEL"]} if os.environ.get("STT_MODEL") else {}),
                              **({"keyterms_prompt": words} if words else {}))
    if provider == "xai":
        return xai.STT(http_session=http_session)
    if provider == "openai":
        return openai.STT(model="gpt-4o-mini-transcribe", language=os.environ.get("STT_LANGUAGE", "en"))
    raise ValueError(f"Unknown STT provider: {provider}")


class _Streamed(openai.tts.ChunkedStream):
    """One sentence from the local voice server as it renders (stream: true, raw PCM chunks), instead of
    after the whole sentence: her first words start sooner (main Viventium streams)."""

    async def _run(self, output_emitter) -> None:
        import httpx2 as httpx
        from livekit.agents import APIConnectionError, APIStatusError
        try:
            async with self._tts._client.audio.speech.with_streaming_response.create(
                    input=self.input_text, model=self._opts.model, voice=self._opts.voice, response_format="pcm",
                    speed=self._opts.speed, extra_body={"stream": True, "streaming_interval": STREAM_SECONDS},
                    timeout=httpx.Timeout(30, connect=self._conn_options.timeout)) as stream:
                output_emitter.initialize(request_id=stream.request_id or "", sample_rate=self._tts.sample_rate,
                                          num_channels=1, mime_type="audio/pcm")
                async for chunk in stream.iter_bytes():
                    output_emitter.push(chunk)
                output_emitter.flush()
        except openai_sdk.APIStatusError as e:
            raise APIStatusError(e.message, status_code=e.status_code, request_id=e.request_id, body=e.body) from None
        except Exception as e:
            raise APIConnectionError() from e


class _StreamedTTS(openai.TTS):
    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        text = _local_text(self, text)
        return _Streamed(tts=self, input_text=text, conn_options=conn_options)


def _local_text(engine, text):
    from speech.sounds import native_text
    name = engine._opts.model.rstrip("/").split("/")[-1] + "-" + engine._opts.voice
    return native_text(text, name)


class _LocalTTS(openai.TTS):
    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return super().synthesize(_local_text(self, text), conn_options=conn_options)


STREAM_SECONDS = float(os.environ.get("TTS_STREAM_SECONDS", "1.0"))  # audio per streamed chunk


class _LightSpeech(lk_tts.TTS):
    def __init__(self, provider, voice, http_session):
        super().__init__(capabilities=lk_tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        self._provider = provider
        self.voice = voice
        self.http_session = http_session

    @property
    def provider(self) -> str:
        return self._provider

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        if self.provider == "mac_say":
            from speech.sounds import native_text
            text = native_text(text, "mac-speech")
        return _LightSpeechChunk(tts=self, input_text=text, conn_options=conn_options)


class _LightSpeechChunk(lk_tts.ChunkedStream):
    async def _run(self, output_emitter):
        request = utils.shortuuid()
        output_emitter.initialize(request_id=request, sample_rate=24000, num_channels=1, mime_type="audio/pcm")
        if self._tts.provider == "mac_say":
            output_emitter.push(await asyncio.to_thread(_say, self.input_text))
            return
        from core import grok_sign_in
        from speech.live import read
        from settings.runtime import own_is_off
        try:
            voice = await asyncio.to_thread(read, ("KEYS_OFF",))
            if own_is_off(grok_sign_in.NEEDS) or grok_sign_in.NEEDS in (voice or {}).get("KEYS_OFF", "").split():
                raise grok_sign_in.NotSignedIn()
            token = await asyncio.to_thread(grok_sign_in.token)
            if own_is_off(grok_sign_in.NEEDS):
                raise grok_sign_in.NotSignedIn()
            session = self._tts.http_session or utils.http_context.http_session()
            async with session.post(
                grok_sign_in.api_url() + "/tts",
                headers={"Authorization": f"Bearer {token}", "User-Agent": grok_sign_in.UA},
                json={"text": self.input_text, "voice_id": self._tts.voice or "eve", "language": "en",
                      "output_format": {"codec": "pcm", "sample_rate": 24000}},
                allow_redirects=False, timeout=aiohttp.ClientTimeout(total=self._conn_options.timeout),
            ) as response:
                if response.status != 200:
                    raise APIStatusError("Grok speech is unavailable", status_code=response.status, request_id=request)
                async for chunk in response.content.iter_chunked(8192):
                    output_emitter.push(chunk)
        except (grok_sign_in.NotSignedIn, grok_sign_in.Unavailable, aiohttp.ClientError, TimeoutError):
            raise APIConnectionError("Grok speech is unavailable") from None


def _say(text):
    import subprocess
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "speech.wav"
        try:
            subprocess.run(["/usr/bin/say", "-o", str(path), "--data-format=LEI16@24000", "-f", "-"],
                           input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12, check=True)
            with wave.open(str(path), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000):
                    return audio.readframes(audio.getnframes())
        except (OSError, ValueError, wave.Error, subprocess.SubprocessError):
            pass
    raise APIConnectionError("The macOS voice is unavailable")


def tts(http_session=None):
    """Her voice. With TTS_FALLBACK set, a second voice takes over when the first cannot be reached (LiveKit's
    FallbackAdapter: it keeps trying the first in the background and returns to it). A declared choice in the
    profile. During local voice preparation, use its declared backup or the existing macOS voice."""
    from speech.selection import apply
    apply()
    first, backup = os.environ.get("TTS", "mlx_local"), os.environ.get("TTS_FALLBACK", "")
    if first in ("xai", "xai_plan") and os.environ.get("SMALL_MAC_TIER") in ("8", "16") and backup == "mlx_local":
        backup = "mac_say"  # these profiles do not budget for the local voice model
    from core.downloads import voice_status
    if first in ("xai", "xai_plan") and backup == "mac_say" and os.environ.get("SMALL_MAC_TIER") not in ("8", "16") \
            and voice_status() == "ready":
        backup = "mlx_local"
    if voice_status() in ("preparing", "downloading", "failed"):
        # No connection timeout before the backup while the local files are unavailable.
        if first == "mlx_local":
            return _voice(backup if backup and backup != "mlx_local" else "mac_say", http_session,
                          os.environ.get("TTS_FALLBACK_VOICE"))
        backup = "mac_say" if backup == "mlx_local" else backup
    if first == "small_auto":
        first = "xai" if os.environ.get("XAI_API_KEY") else "openai" if os.environ.get("OPENAI_API_KEY") else "mac_say"
        backup = "mac_say"
    if not backup or backup == first:
        return _voice(first, http_session, os.environ.get("TTS_VOICE"))
    if (key := KEY_OF.get(first)) and not os.environ.get(key):  # (its key off or missing: not built at all, its backup
        return _voice(backup, http_session, os.environ.get("TTS_FALLBACK_VOICE"))  # speaks, as her mind's: brain/queen.py)
    return lk_tts.FallbackAdapter([_voice(first, http_session, os.environ.get("TTS_VOICE")),
                                   _voice(backup, http_session, os.environ.get("TTS_FALLBACK_VOICE"))], max_retry_per_tts=1)


def _voice(provider: str, http_session, name: str | None):
    if provider in ("xai_plan", "mac_say"):
        return _LightSpeech(provider, name, http_session)
    if provider == "openai":
        return openai.TTS(model="gpt-4o-mini-tts", voice=name or "alloy", response_format="wav")
    if provider == "mlx_local":  # mlx-audio's OpenAI-compatible server (speech/tts): Ming, Chatterbox, …
        voice = _StreamedTTS if os.environ.get("TTS_STREAM") == "1" else _LocalTTS
        return voice(base_url=os.environ.get("TTS_URL", "http://127.0.0.1:8940/v1"), api_key="local",
                     model=os.environ.get("TTS_MODEL", "mlx-community/chatterbox-turbo-8bit"),
                     voice=name or "default", response_format="wav")
    if provider == "xai":  # XAI_API_KEY. Its default word tokenizer drops the spaces between words, so they can
        # run together; main Viventium keeps them (retain_format), as here. TTS_OPTIMIZE_LATENCY: xAI's own streaming
        # latency level (LiveKit's optimize_streaming_latency), left to xAI unless a measured run sets it.
        level = os.environ.get("TTS_OPTIMIZE_LATENCY", "")
        return xai.TTS(voice=name or "eve", http_session=http_session,
                       tokenizer=tokenize.basic.WordTokenizer(ignore_punctuation=False, retain_format=True),
                       **({"optimize_streaming_latency": int(level)} if level.strip().isdigit() else {}))
    raise ValueError(f"Unknown TTS provider: {provider}")
