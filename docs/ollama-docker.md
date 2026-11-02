# Local AI inside Docker

The development Central Server now runs Ollama 0.40.13 as the `ollama` service in `linker-scada-wsl`. The copied model is `qwen3:4b`. The worker and management agent use the fixed internal address `http://ollama:11434`; the Windows Ollama application is retained as a fallback and is no longer the active inference service.

The WSL override enables this with private `.env` setting `LINKER_AI_PROVIDER=container` and Compose profile `local-ai`. A missing setting or value `1` retains the Windows-host provider for older installations. Manager start/stop and installer reruns honor the selected profile. Local/Network deployment saves retain this unrelated setting. Restart an already-open manager after an external provider change.

Ollama has no published host port, belongs only to the internal `local-ai` Docker network and has cloud features disabled. Its container logs are disabled so prompts are not copied into Docker logs. Model files persist in `linker-scada-wsl_ollama-models`; enabled/model choices remain in the separate `linker-scada-wsl_ai-settings` volume. Preserve both alongside the existing database, certificate and credential storage. Do not remove volumes or reset Docker to troubleshoot inference. This configuration uses CPU inference, matching the existing application policy; GPU commissioning was not performed.

The container uses the [official Ollama image and persistent storage layout](https://docs.ollama.com/docker). Local-only mode uses the documented [`OLLAMA_NO_CLOUD=1` setting](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features). The runtime version is pinned to the existing Windows version; the local image digest is `sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429`.

## Transfer and verification — 2026-11-02

The transfer copied only the existing model manifest and its six referenced blobs (approximately 2.5 GB) into the new named volume. Every blob's size and SHA-256 matched before and after copying; the manifest digest is `31d9857b5705086d352d4d6db04e86c5d0f6a2b5d59a4dc7ce5cdb271ccf9141`. Windows model files and Ollama private keys were not changed; no Windows private keys were copied. Local commissioning helpers remain ignored under `.tools/` and are not portable deployment tooling.

Protected pre-switch settings and fingerprints are retained under the WSL workspace's private `secrets/docker-ollama-*` backup. The selected server was stopped before replacing code, and its runtime images were rebuilt and started with the model profile. Its enabled choice, selected model, upload credentials and public CA matched pre-switch state. No source registrations, native records or mapping approvals were replaced.

The actual Docker worker passed the model-list/digest check and a production-timeout synthetic inference: `Oven 1 temperature high` identified `Oven 1`. The management agent also verified the model through the container service. A different synthetic equipment message remained uncertain; model output still requires original-message evidence and never approves a mapping. No synthetic upload or native record was inserted. Container inspection verified a healthy model service, no published port and only an internal network.

Future model transfers require explicit provisioning of verified model files; this isolated service does not automatically download models or use a cloud fallback. Reading Equipment Identification never enables AI or calls a model. Existing Collector uploads continue through the saved HTTPS endpoint.
