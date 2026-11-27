# Licences

Viventium AI by xPerfect.ai uses [FSL-1.1-ALv2](../LICENSE), copyright 2026 xPerfect.ai.
It is source-available (Fair Source), not OSI open source. Each release becomes Apache 2.0
two years after that release.

The Mac app is not signed with a Developer ID or notarized yet; see [Build, sign and package](distribution.md).

The candidate DMG includes the native launcher, Viventium AI source, dependencies' lockfiles, the LiveKit starter code, fonts,
provider marks and factory audio. The public source leaves the factory audio out: those clips are research and build
assets that the product never plays. Dependencies and model weights download from their upstream distributors.
The package excludes the GPL sound-check tool, its test classifier, tests, the unused Aura visualizer and
unused fonts. See [dependencies.csv](dependencies.csv) for the dependency inventory.

## Included notices

| Part | Licence and notice |
| --- | --- |
| LiveKit starter code | MIT. See [LiveKit's licence](../call/ui/LICENSE). Viventium AI removes the Polyform Non-Resale Aura visualizer. |
| Inter Tight, Public Sans and Commit Mono | SIL OFL 1.1. The full notices are [beside the fonts](../call/ui/fonts/), including the [Commit Mono font licence](../call/ui/fonts/CommitMono-OFL.txt). |
| Provider marks | See [mark provenance](../call/ui/public/marks/PROVENANCE.md) and the [LobeHub MIT notice](notices/LobeHub-MIT.txt). Brand rights remain with the mark holders. |
| Viventium AI and copied Viventium code, prompts, Life template and media package | FSL-1.1-ALv2 for Viventium AI; permission to distribute copied parts remains to be confirmed. |

The pinned [xPerfect source](https://github.com/xPerfectAI/xPerfect) downloads with its Apache-2.0 licence
and NOTICE. When changing the xPerfect pin, update `brain/xperfect.archive.sha256.txt` with the SHA-256
of GitHub's archive for that commit. Viventium AI's patches are in the source tree. Homebrew tools, Ollama and the Python and JavaScript
packages keep their upstream distribution terms. [Ollama 0.40.15](https://github.com/ollama/ollama/blob/v0.40.15/LICENSE)
uses MIT. Its release also carries licences for bundled parts. LiveKit's optional Krisp package has its own
terms and the call page does not import it.

## System tools

Viventium AI downloads and verifies the pinned [official Homebrew installer](https://github.com/Homebrew/brew/releases/tag/7.0.15).
macOS Installer handles approval. The Mac’s Homebrew owner installs and upgrades formulae in the normal Homebrew prefix.
Viventium AI’s maintainers update the installer pin and checksum. Apple owns updates to any Command Line Tools the Mac needs.
The apps and formulae carry notices for their bundled dependencies.

| Tool | Licence | Upgrade owner |
| --- | --- | --- |
| Homebrew | BSD-2-Clause | Homebrew owner |
| uv | Apache-2.0 or MIT | Homebrew owner |
| pnpm | MIT | Homebrew owner |
| Node.js / npm | MIT / Artistic-2.0 | Homebrew owner |
| Python | Python-2.0 | Homebrew owner |
| LiveKit server | Apache-2.0 | Homebrew owner |
| whisper.cpp | MIT | Homebrew owner |
| FFmpeg Homebrew formula | GPL-3.0-or-later | Homebrew owner |
| ripgrep | MIT or Unlicense | Homebrew owner |
| Git Homebrew formula | GPL-2.0, LGPL-2.1, BSD-3-Clause and MIT across its parts | Homebrew owner |
| Xcode Command Line Tools and macOS speech | Apple software terms | Apple and the Mac’s administrator |

## Downloaded models

| Model | Terms checked |
| --- | --- |
| Qwen 3.6 and Qwen3 1.7B | Apache-2.0 in the [Qwen 3.6](https://ollama.com/library/qwen3.6) and [Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b) Ollama entries. |
| Qwen3 Embedding 0.6B | Apache-2.0 from [Qwen](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B). |
| Whisper large-v3-turbo and Silero VAD 5.1.2 | MIT from [OpenAI](https://huggingface.co/openai/whisper-large-v3-turbo), [whisper.cpp's Whisper conversion](https://huggingface.co/ggerganov/whisper.cpp), and [whisper.cpp's VAD conversion](https://huggingface.co/ggml-org/whisper-vad). |
| LiveKit turn detector | [LiveKit Model License](https://huggingface.co/livekit/turn-detector). Viventium AI uses it only through LiveKit Agents. |
| Chatterbox Turbo MLX 8-bit | Apache-2.0 in the [conversion card](https://huggingface.co/mlx-community/chatterbox-turbo-8bit). |
| S3TokenizerV2 MLX | The [conversion card](https://huggingface.co/mlx-community/S3TokenizerV2) identifies [CosyVoice2-0.5B](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B), which declares Apache-2.0. The conversion publishes no licence of its own. |
| Z-Image Turbo MLX Q8 | Apache-2.0 in the [pinned model card](https://huggingface.co/mflux-community/z-image-turbo-mflux-q8/tree/4ccff28917346aa9daae49cd3c477cf5260a242c). |
| Qwen Image 2.1, optional | [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE) allows research and evaluation. Commercial use requires a separate licence. |
| MiniMax H3, optional | [MiniMax H3 Community License](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE) sets territorial, attribution and commercial terms. |
| AST AudioSet, test only | BSD-3-Clause in the [model card](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593). Excluded with the sound check. |

Known limits: the optional restricted models (Qwen Image 2.1, MiniMax H3) stay under their own terms, and the
S3TokenizerV2 conversion publishes no licence of its own, so its terms are not confirmed.
