"""mlx-audio's own server. Sampling settings a caller leaves out (LiveKit sends
none) are the voice model's own defaults, as it was compared and chosen with
(Chatterbox Turbo: temperature 0.8, top_k 1000, repetition_penalty 1.2). The stock server put its
generic 0.7 / 40 / 1.0 there, and the laugh-and-sigh line stretched from 4.7 s to 6.3-7.2 s.
The typed voice capability can refine those defaults (Chatterbox top_p 0.8: measured word
fidelity). An explicit request always wins. Raw 16-bit PCM, OpenAI's "pcm": a streamed sentence arrives as chunks that simply
join, where each WAV chunk would carry its own header (speech/factory.py streams the local voice).
(Chatterbox performs its sound markers natively in the same request as their words.)"""
import inspect
import json
from pathlib import Path

import mlx_audio.server as server
import numpy as np

_stock = server._resolve_sampling_params
_voices = json.loads((Path(__file__).resolve().parents[2] / "brain" / "prompts" / "feelings" /
                     "tts_provider_capabilities.json").read_text())["providers"]


def _model_defaults(model, request):
    params = _stock(model, request)
    own = inspect.signature(model.generate).parameters
    for name in server._SAMPLING_FIELDS:
        if name not in request.model_fields_set and name in own and own[name].default is not inspect.Parameter.empty:
            params[name] = own[name].default
    for voice in _voices.values():
        if any(model["id"] == request.model for model in voice["runtime_models"]):
            for name, value in voice.get("generation_defaults", {}).items():
                if name in server._SAMPLING_FIELDS and name not in request.model_fields_set:
                    params[name] = value
            break
    return params


server._resolve_sampling_params = _model_defaults

_write = server.audio_write


def _write_pcm(file, data, sample_rate, format=None, **kwargs):
    if (format or "").lower() != "pcm":
        return _write(file, data, sample_rate, format=format, **kwargs)
    samples = np.asarray(data.tolist() if hasattr(data, "tolist") and not hasattr(data, "__array__") else data,
                         dtype=np.float32).reshape(-1)
    file.write((np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes())


server.audio_write = _write_pcm

if __name__ == "__main__":
    server.main()
