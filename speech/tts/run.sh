#!/usr/bin/env bash
# Local Chatterbox Turbo (MLX) via mlx-audio's own OpenAI-compatible server on :8940 (serve.py: the
# voice model's own sampling defaults, as it was compared and chosen with).
# Offline: load the cached model only; no update checks to Hugging Face (`./vx setup` downloads it once).
set -euo pipefail
cd "$(dirname "$0")"
root=$(cd ../.. && pwd)
export HF_HUB_CACHE="${VX_STATE:-$root/state}/downloads/hub"
export HF_HUB_OFFLINE=1
if [ "${VX_PREPARE_VOICE:-}" = 1 ]; then
  if [ "${TTS_MODEL:-mlx-community/chatterbox-turbo-8bit}" != mlx-community/chatterbox-turbo-8bit ]; then
    echo "This voice has no verified download yet. Choose Chatterbox in Settings."
    exit 1
  fi
  .venv/bin/python "$root/core/downloads.py" voice --prepare
fi
.venv/bin/python "$root/core/downloads.py" voice --check
exec .venv/bin/python serve.py --host 127.0.0.1 --port 8940
