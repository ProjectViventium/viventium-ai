# Download inventory and verification

Scope: a clean Mac, the app installer, `vx up`, and the Settings install actions.
The package contains source and locks; it does not contain a model.

| Input / execution path | Pin and verification | Remaining limit |
| --- | --- | --- |
| Native app payload | The package builder exports selected source, records its release digest, then signs the app and checks the installed copy. | Developer ID signing and notarization are not done yet. The launcher's copy check is a release stamp, not a fresh hash of every product file. |
| Apple's developer tools | Not installed by app setup. Needed only to build the native app from source (`./vx app`). | Existing developer tools are left in place. |
| Homebrew, app path | `Homebrew.pkg` 7.0.15, SHA-256 in `vx`, plus `pkgutil --check-signature` before Installer opens it. | Homebrew's own bootstrap and package catalogue remain vendor managed. |
| Homebrew, Terminal path | Without Apple's tools, the same signed package as the app, installed with one sudo approval. With Apple's tools, official `install.sh` commit `c9c975046f78e6e6d662deb801bd461ebd6a54ed`, SHA-256 in `vx` and `core/downloads.json`; fetched whole before sudo or bash. | The script's later Homebrew checkout is vendor managed. |
| System programs | `brewed`: uv, pnpm, node/npm, Python, LiveKit server, whisper.cpp when used, ffmpeg, ripgrep, git. Homebrew verifies bottles/source against formula checksums. Existing programs are reused. | Formula versions and their transitive dependencies are selected by Homebrew, not a Viventium AI lock. No shared program is upgraded. |
| Claude Code / Codex | New Viventium AI-owned installs: official npm native archives, Claude 2.1.331 and Codex 0.172.0, Darwin arm64/x64 SHA-512 values in `core/downloads.json`. No npm lifecycle script executes. Extract to a private stage, then publish the entry point. Verify installed files in full on startup. | Existing shared CLIs are reused; their reported version and path go to private `state/downloads/shared-NAME.json`. Their bytes are outside Viventium AI's control. Settings uses the last verified file stats, and rejects changed files. |
| Grok Build | npm `@xai-official/grok` 1.0.50, scripts disabled, native binary SHA-256 per Mac architecture in `tools/grok-build-pin.json`. A stage replaces the entry point only after verification. Settings uses this same installer. | npm transport uses registry integrity; only the checked native binary is executed. |
| xPerfect | Gitlink `07dac785b8d5398dc5722b16e7d89784fe43a07e`; exports carry `brain/xperfect.pin`. Archive SHA-256 in `brain/xperfect.archive.sha256.txt`. Full ordered patch proof precedes application. `brain/xperfect.files.json` records all 838 resulting source files, execute bits, the base pin and every patch digest. Startup and status check those bytes, including files outside patch hunks. A Git install also retains the existing HEAD/index verdict. | Drift stops startup. It is preserved for review, not overwritten. Install a fresh copy to repair it. |
| Root Python packages | `uv.lock`, distribution URLs and hashes; `uv sync --locked --group test`. Includes LiveKit, Silero's packaged ONNX VAD, and Transformers/HF code. | Python `3.12` selects a patch release. uv's own Python catalogue supplies and verifies a managed interpreter if needed. Package build scripts are trusted code from these locked inputs. |
| Voice Python packages | `speech/tts/uv.lock`, hashes; `uv sync --locked`, mlx-audio 0.6.4, and webrtcvad-wheels 2.0.14.post1 in place of the source-only webrtcvad dependency. | Voice setup permits wheels only (`no-build`); no Apple compiler is needed. |
| xPerfect Python packages | Its pinned archive includes the runtime and UI uv locks. Its host uses `uv sync --frozen --no-dev`. | Editable local source is covered by the source-file verdict; installed environments remain runtime state. |
| Call UI / npm | `call/ui/pnpm-lock.yaml` has exact versions and integrity; `pnpm install --frozen-lockfile`. `package.json` names pnpm 9.15.9. | Homebrew's pnpm executable is shared. Package lifecycle/build code is trusted from the lock. Developer-only `shadcn@latest` is not an installer action. |
| Voice snapshot | `mlx-community/chatterbox-turbo-8bit` at `2f2e21a03863f86a1274d1060dcc188e7cde77e1`. Each runtime file has its upstream LFS SHA-256 or Git blob digest and size in `core/downloads.json`. | Custom, unreviewed voice models stop with a way to select the shipped voice. |
| Speech tokenizer snapshot | `mlx-community/S3TokenizerV2` at `e0c9886f0e1c35ae85b1f27277416fb19fc72bec`, every runtime file checked as above. | mlx-audio's nested default-branch lookup resolves only to this verified private cache, offline. |
| LiveKit turn snapshots | English `ebcab0c09c2b62d926e92180d364df3aaae68a09`; multilingual `87e35fcb1e60a569bea70346191c4886ea92e281`. Required tokenizer/config/language files and quantized ONNX files have checked digests and sizes. The plugin's tag aliases resolve to these commits in Viventium AI's private cache. | No training weights or other ONNX variants are fetched. This replaces the plugin's mutable-tag download step. |
| Whisper hearing / VAD | Immutable HF commits `5359861c739e955e79d9a303bcbc70fb988958b1` and `9ffd54a1e1ee413ddf265af9913beaf518d1639b`; both binary SHA-256 values remain in `vx`. | Existing Whisper cache location is unchanged. Each file verifies before the hearing server starts. |
| Ollama server | 0.40.15 Darwin archive SHA-256 in `vx`; stage unpack, then publish. | Existing executable installs are reused; there is no full executable-file audit for Ollama. |
| Ollama model pulls | Selected profile names: Qwen 3.6, Qwen 3 1.7B, embedding models, or the person's selected model. Ollama checks content-addressed blobs before it publishes its model manifest. | Tags, including `latest`, remain mutable. Viventium AI adds no model-digest pins to Ollama. |
| Optional picture/video tools | Settings has immutable HF media revisions and file verification; MFLUX has its own requirements, stable-diffusion.cpp its qualified source commit. `tools/media/make` builds it. | Optional runtimes and their transitive dependencies are not frozen. See `settings/install.py` and `tools/media`. |
| Optional add-ons | Settings checks the supplied package digest when configured and every declared file digest before readiness. | A locally supplied package is trusted by whoever supplies it. No add-on is required by startup. |
| Optional audio classifier | `vx sound_check`: `tools/soundcheck/requirements.txt`, uv environment, classifier's own model loader. | On-demand test tool; its requirements and model downloads are outside the required install path. |
| Browser | A person's installed Chrome; no browser executable is downloaded by the normal app installer. | Playwright browser downloads belong to developer QA, not first use. |

The detailed Python/UI dependency list remains in `docs/dependencies.csv` and the locks above.
HF file identities were read from the official model API at each immutable revision. Native harness archive
integrities were read from the official npm registry version metadata.

## Repair and updates

- A dropped or changed managed download: reopen Viventium AI, or run `./vx up` again. Known bad bytes are replaced only by
  bytes with the expected digest. Interrupted transfers remain `.part`; they never publish an executable or model
  reference. Voice/hearing files live in `state/downloads/hub` (or `VX_STATE/downloads/hub`), separate from shared HF caches.
- The native setup window says **Download paused. Retrying…** and retries. Settings never counts a failed harness
  install as installed. The voice launcher checks both snapshots before it imports the server.
- xPerfect drift: keep the changed checkout; install a fresh copy of the matching release. Startup does not discard
  edits. A developer changing the pin or patch series must review the new source and regenerate the file list with
  `python3 tools/package/xperfect_files.py VERIFIED_UPSTREAM_ARCHIVE.tgz`. This command checks the archive's recorded
  SHA-256 and applies the complete patch series before it writes anything. Commit the pin, digest, patches and file list together.
- To update a HF or harness pin, review the official immutable revision/version and its file digests, update
  `core/downloads.json`, and run the download and affected install tests. Local manifests are the trust anchors;
  remote metadata alone cannot mark a downloaded file ready.

## Existing installs

Shared HF snapshots and blobs are read in place, including files under older revisions. Each candidate must match
the manifest's size and every digest. Viventium AI tries an APFS clone, then a hard link, then a copy. It verifies the
staged file again before publishing it. Shared files and refs are never edited. Only unmatched files are fetched.

`vx up` prepares the voice, turn models and Whisper in background processes. Setup called by `up` also defers the
HF files. The agent and conversation do not wait for these downloads or for voice warm-up. Missing turn files keep
the optional local inference runners out of agent startup; that worker uses the existing turn fallback until its
next restart. The voice reports preparation, downloading or failure in the conversation. It uses its configured
backup, or the existing macOS voice, then changes back in the same call when the verified download completes.

Read-only first-restart plan: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python core/downloads.py upgrade-report`.
