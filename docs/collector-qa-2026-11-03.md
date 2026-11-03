# Collector QA — 3 November 2026

Scope: the current single-Docker Collector desktop, its CLI/runtime, protected setup,
read-only extraction, durable queue, scheduling and Central Server acceptance contract.
Published X3 remains the earlier native Collector 0.4.0; this review does not publish
or replace that release.

## Assessment

Automated acceptance passes after the fixes below. Customer commissioning remains
conditional on the outstanding checks at the end of this report. Fixture coverage
does not establish complete capture of a customer's mutable source history or safe
load on its SCADA PC.

Saved operational settings, credentials, identities, pending batches and databases
were retained. No SCADA records, database settings, schemas or permissions were
changed. Docker Desktop was started for QA; operational projects were not rebuilt,
stopped or reconfigured. Container tests used generated `collector-qa-*` resources,
with disposable PostgreSQL on a private Docker network and no published database port.

## Defects corrected

| Finding | Result |
|---|---|
| Docker import was disabled by unsaved source IDs, HTTPS/upload options and CA path, even though the imported file supplies them. | Import uses the last saved local configuration. Local database/history/schedule edits still require saving and receive an explanation. |
| Direct setup-import dispatch could open the file selector while the Docker scheduler was running. | Both the button and handler block import until the selected Collector stops; lower-level identity/queue/lock guards remain. |
| The Docker deployment Start button bypassed the Collection page's saved/enabled checks. | Both Start buttons and their shared handler require saved, enabled collection and stored entered credentials. |
| Manual Stop signalled cancellation but left the repeat Stop control enabled. | Controls refresh immediately while bounded cancellation finishes; the scheduler stop command is not substituted for a manual operation's cancellation. |
| Refresh raised an error for missing, inaccessible or timed-out Docker commands. | These engine-probe failures return unavailable status, preserving previews. Start failures and actual stop failures still report errors; no automatic mutation retry was added. |
| Future frozen Windows GUI builds lacked Compose files and a complete Docker build context. | The build stages allowlisted application files and bundles them. Frozen controls resolve that context and use a persistent handoff location outside the temporary executable extraction directory. |
| Relative PyInstaller icon/data paths failed when the spec lived in another directory. | The build passes absolute icon and context paths. A separate QA GUI executable was built and its embedded inputs compared with the staged originals. |
| Stopping immediately after container creation could reach Python before its signal handlers existed and consume Docker's stop allowance. | Collector containers use Docker init forwarding. Normal ready-scheduler shutdown and immediate startup shutdown are tested separately. |
| The full Linux test image omitted a packaging input and retained root execution. | The `test` target includes `.dockerignore` and returns to UID/GID 10001, matching the installer tests' normal-user prerequisite. Runtime targets remain separate. |

Database-password feedback now identifies the Docker key when using the Docker GUI.
Sixteen regression/boundary/packaging tests were added. Initial failing regression
runs are development evidence, not part of the final passing totals.

## Feature coverage

| Feature | Evidence and limit |
|---|---|
| Local configuration, validation, stale edit protection, CLI dispatch | `test_config`, `test_desktop`, `test_cli`, `test_docker_agent`; malformed settings and stale management requests are rejected. |
| Windows and Linux credential protection | `test_secrets`, `test_posix_secrets`, `test_docker_agent`, `test_docker_migration`; actual DPAPI/ACL and Linux ownership/encryption checks run on their respective platforms. Missing/wrong keys do not regenerate credentials. |
| Read-only SCADA access and approved tables | `test_source_reader`, `test_source_fixture`; unsafe accounts, writes, schema mismatches and out-of-scope tables are rejected on disposable fixtures. No write test targets a real SCADA database. |
| Alarm/event previews and original values | `test_gui`, `test_records`, `test_source_reader`; bounded rows/fields/output, masked operator fields, nullable values, strings, flags, milliseconds and timestamp uncertainty. |
| Incremental extraction and initial history | `server/tests/test_delivery`; ID-range and marker pagination, equal/NULL markers, older-ID changes, overlap, late commits, reconciliation, persistent history scope and new IDs. Source reset faults remain conservative. |
| Durable staging, immutable retries and replay | `collector/tests/test_delivery`, `server/tests/test_delivery`; atomic rollback, hard process exit, quotas, matching receipts, lost replies, deduplication and generation recovery. |
| Privacy policies | `test_delivery`, `test_records`; upload-all, omission and keyed HMAC. Preview omission remains independent of upload policy. |
| Schedules and cancellation | `test_delivery`, `test_cli`, `test_gui`, `test_docker_gui`; interval/daily/weekly timing, DST gaps/folds, interrupted occurrences, missed-slot coalescing, manual/automatic cancellation and close behavior. |
| HTTPS and server authentication | `test_tls`, `test_server_connection`, `server/tests/test_delivery`; real TLS handshake, untrusted-CA rejection, explicit CA success, source/generation authorization, strict receipts, redirect rejection and replay. |
| Encrypted server setup | `test_setup_import`, `test_docker_agent`, `test_docker_gui`; wrong password, oversize requests, stale configuration, assigned identity, pending state and scheduler guards. Credentials remain out of RPC responses. |
| Central processing, quarantine and isolation | `server/tests/test_delivery`, `test_foundation`; durable acceptance, unknown mappings, approved reprocessing, worker retries, tenant isolation and preservation of native history. A committed receipt does not mean mapping is approved. |
| Docker management | `test_docker_control`, `test_docker_agent`, `test_docker_gui`; local engine/project routing, stdin requests, redacted faults, no native scheduler, and close-leaves-running behavior. |
| Container persistence and hardening | Separate disposable runtime smoke test: nonroot user, read-only root/key mount, init forwarding, restart policy, no published ports, credential encryption, stale-save rejection and unchanged pending payload SHA-256 across stop/restart. |
| Windows packaging | `test_docker_packaging`, allowlisted-context Docker image build, and separate PyInstaller GUI build/archive inspection. Full installation/upgrade is a remaining gate. |

## Executed checks

| Final check | Passed | Skipped | Failed | Duration |
|---|---:|---:|---:|---:|
| Windows / Python 3.13.17 / disposable PostgreSQL 17, full repository suite | 314 | 43 | 0 | 91.22 s |
| Linux container / Python 3.12 / disposable PostgreSQL 17, full repository suite | 254 | 103 | 0 | 35.25 s |
| Collector cases within Windows run | 156 | 9 | 0 | Included above |
| Collector cases within Linux run | 117 | 48 | 0 | Included above |

All **165 distinct Collector test cases passed on at least one platform**. Windows
skips cover Linux ownership/migration cases; those ran on Linux. Linux skips cover
Windows DPAPI/ACL/process cases and desktop displays; those Collector cases ran on
Windows. Optional Central Server Qt GUI tests remain skipped on both hosts because
that dependency is absent. The full runs logged one Windows warning and two Linux
warnings, with no failures or errors.

The disposable runtime smoke test passed: protected credentials, stale-save
rejection, two ready-scheduler restarts with exit code 0, and identical pending
payload bytes. Immediate startup stop completed within 15 seconds with exit code
143 (SIGTERM before scheduler readiness), retained the queued bytes, and did not
reach a forced-kill exit. The container used UID/GID 10001, read-only root and key
mounts, Docker init, `unless-stopped` restart policy and zero published ports.

An image built from the staged package context passed the runtime checks. A
separate Windows GUI executable built successfully; its embedded Compose files,
Dockerfile, dependency lock and application build inputs matched the staged files.
The existing release executables/installers were retained. Its local build report
is `.tools/collector-qa-20261103/frozen.json`.

Central Compose, base Collector Compose and Collector-plus-host Compose all passed
`config --quiet` without starting services. PowerShell parsed the updated Windows
build script successfully; `git diff --check` passed.

The Windows integration runner checks the PostgreSQL data directory against
`.tools/collector-postgres-test` before enabling fixture tests. Linux uses a new
PostgreSQL 17 container. Fixture databases/roles and QA Docker projects are removed
after testing; operational data/key volumes are retained. PostgreSQL compatibility
and SQL were not changed; PostgreSQL 18 was not exercised in this review.

A separate synthetic benchmark used 150,000 alarms and 150,000 events, with primary
keys only. Bounds took 339.412 ms; 50-row ID pages took 58.042–62.368 ms; marker pages
took 202.836–250.438 ms. After 10,000 fixture changes, bounds plus one page took
452.035 ms. A 1 ms statement timeout cancelled the query as required. These figures
describe this development machine and run, not a production capacity guarantee.

Private, PC-specific orchestration and XML/build/runtime reports are under
`.tools/collector-qa-20261103/`; Windows acceptance XML is
`.tools/collector-acceptance-results.xml`. These are ignored local evidence, not CI
infrastructure or release artifacts. The regular automated entry point remains
`python -m pytest -q`, with disposable PostgreSQL configured as documented in
[Collector development verification](../collector/README.md#development-verification).

## Outstanding acceptance gates

- Verify a newly occurring alarm/event from each actual remote Collector PC through
  its HTTPS endpoint, committed receipt and Central mapping/processing status.
  Existing operational source records were not edited or replayed to manufacture
  this evidence.
- Commission actual source timezone/change-marker semantics, retention/reset
  evidence, peak-load impact, and recovery targets. Changes overwritten between
  reads cannot be reconstructed by the Collector.
- Run host reboot/sign-in/Docker Desktop recovery and extended source/server outage
  checks in an approved commissioning window. Disposable container restart checks
  do not establish host reboot recovery.
- Verify the new complete Windows installer on a clean PC and as an upgrade,
  including Docker prerequisites and its persistent volumes. This task built only
  a separate QA GUI executable; existing X3 packages were preserved.
- Install/run a legacy Windows service only in an isolated installation with a
  separate identity; no native scheduler/service was started beside the migrated
  operational Docker Collector.

See [Collector operation](../collector/README.md),
[Docker setup](collector-wsl-docker.md), and
[operations and recovery](operations.md) for the supported workflows and limits.
