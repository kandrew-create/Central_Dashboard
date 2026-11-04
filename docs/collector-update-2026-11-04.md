# Collector punchlist update — 4 November 2026

## Scope and handoff

Collector 0.4.1 is a separate Windows installation package and independent Docker image/project. Install it on the designated **other PC** using [the installation guide](collector-installation.md). This task does not install the package or run an operational Collector on the Central development PC. Existing Collector volumes, identity/queue state, SCADA databases and published X3 packages are retained.

| Punchlist item | Result |
| --- | --- |
| Installation and driver/software safety | Included an installation/upgrade guide with vendor-approved Docker/WSL prerequisites, maintenance/reboot boundaries, unchanged SCADA drivers/listeners/TLS/schema and bounded read-only source checks. No blanket driver-coexistence guarantee is claimed. |
| Hidden fixed HTTPS URL | No editor in Collection & upload; encrypted setup still supplies the actual endpoint. Test server success does not echo it. |
| Interval hidden for daily/weekly | Both interval label and entry are hidden. Daily/weekly time and weekly weekday appear only for relevant modes; saved interval values are retained. |
| Ollama RAM | Measured separately on Central Server; no model or inference runs on the Collector PC. See below. |
| Encrypted, hidden API key | Existing Windows DPAPI and Linux Fernet storage is retained. Saved credentials never populate the UI, manual input is masked and cleared, and RPC configuration responses contain only presence flags. |
| Automatic Docker startup | App opening starts an already-installed Docker Desktop and resumes only an existing enabled, identified setup with required stored credentials. Work stays off Tk. Missing volumes/key/configuration fail safely; no replacement queue is created. |
| Separate container and installer | `deploy/collector/Dockerfile` and its locked dependencies replace the Central-derived build. The context contains Collector/shared code only. Installer outputs and checksums use fresh versioned folders and include a companion context ZIP and guide. |

Already-running collection is reused. Stop remains effective during the current session; refresh does not restart it. App reopening resumes an eligible enabled setup. A native profile with prior state and no completed migration marker blocks automatic Docker startup pending a reviewed migration. No remote commands, listeners, credential synchronization or automatic database/driver changes were introduced.

## Local AI memory measurement

Ollama runs on **Central Server**, not the Collector. The Collector package installs no Ollama service or model. Docker/Collector/OS memory on the source PC is a separate resource budget.

The existing Central `qwen3:4b` model was measured with one synthetic prompt, CPU inference (`num_gpu=0`), a 4,096-token context and at most eight output tokens. No AI setting was enabled/changed, no model was downloaded and no SCADA/Central record was read or written by the request.

| Observation | Measured value |
| --- | --- |
| Ollama idle, no model loaded | About 70 MiB |
| Largest of 16 sampled Docker memory readings during the test | **3.18 GiB** |
| Docker memory immediately after the request | 3.178 GiB |
| Reported loaded-model size | 3,186,108,660 bytes |
| Reported VRAM | 0 bytes |

These are observed container readings, not total Windows/WSL RAM, a production peak or a universal hardware requirement. Model weights, context, concurrency and backend affect memory. Ollama documents [loaded-model CPU/GPU reporting and memory/concurrency behavior](https://docs.ollama.com/faq) and the read-only [`/api/ps` endpoint](https://docs.ollama.com/api/ps). The synthetic request used the normal five-minute keep-alive; the model can remain resident during that idle period. Do not equate model file size with total inference RAM.

The final audit found no loaded model and about 211 MiB of Ollama container memory after automatic unloading. The initial 70 MiB baseline is therefore an observation before the test, not a fixed idle-memory promise.

## Verification boundaries

Tests use synthetic temporary profiles, mocked desktop/runtime services and disposable databases. No operational Collector is started for testing. The separate runtime was built and checked as UID 10001 in a network-disabled disposable container: Collector 0.4.1 and psycopg imported successfully, with no Central Server or Ollama modules present.

Initial Windows checks passed 143 tests with 33 skips; WSL passed 141 with 35 skips. The skips include platform-only cases, disposable PostgreSQL checks not enabled in those runs and one transient Windows desktop skip (covered in WSL). A separate Linux test container against disposable PostgreSQL 17 passed 123 tests with 53 Windows/display skips, covering the actual source fixture and Linux credential/migration paths. No live SCADA database was used.

A Windows rerun against a new, verified disposable PostgreSQL 18 cluster passed 167 tests with ten Linux/display skips. Additional startup-state guard checks passed in the final 24-case focused Windows startup/control/packaging run. All **178 collected Collector cases** passed at least once across the appropriate environments; this is combined regression coverage, not 178 tests on each platform. One Windows cluster-start helper initially waited on inherited process output pipes; its task-owned cluster was stopped normally, the helper switched to file output, and the rerun passed. Both disposable Windows clusters are stopped; no unrelated PostgreSQL service was stopped.

The final separate package is at `dist/installer/collector/0.4.1-b2f43dd017/`: `Linker-SCADA-Collector-Setup.exe`, its SHA-256 sidecar, `Collector-Docker-Context-0.4.1.zip` with its sidecar, and the installation guide. The four corresponding executable artifacts are under `dist/collector/0.4.1-b2f43dd017/`. All six executable/installer/ZIP checksums passed. ZIP entries match the allowlisted staged files; the GUI's embedded Python modules/context contain no Central Server. Frozen `--verify-package` and CLI `--version` exited successfully without opening the manager or starting Docker/collection. Previous root-level Collector and Central Server installer hashes still match their original sidecars. This package was built, not installed on this PC or published to GitHub Releases.

The final local audit found zero operational Docker Collectors, zero native collection processes and no installed `LinkerScadaCollector` Windows service. Original operational volumes were not reset or deleted. The intended installation remains the other PC.

Actual remote installation, vendor-driver coexistence, source load, HTTPS/firewall trust, reboot/outage recovery, cold Docker Desktop startup and production acceptance still require validation on the other PC. Unit mocks do not prove those conditions.
