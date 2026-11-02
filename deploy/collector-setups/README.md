# WSL Collector setup export

The user explicitly authorized committing this encrypted setup on 2026-11-01. Other setup exports remain ignored by default. Its unlock password, decrypted contents and local password viewer are kept outside Git.

- [Encrypted setup](wsl-network-20261101-235729.linker-collector)
- [SHA-256 checksum](wsl-network-20261101-235729.linker-collector.sha256)
- Central endpoint: `https://187.17.53.84:8443/v1/uploads` (Network mode).

This export reuses the single existing WSL source's active identity and credential. It contains the source/generation IDs, upload credential, destination and public CA certificate under password encryption. It does not contain SCADA database access settings, collection history approval or schedules; configure those locally on the actual Collector PC.

Download the setup and checksum, verify the file hash, then open **Collection & upload → Import server setup** in the Collector. Obtain the unlock password separately. Save required local settings and stop automatic collection before import. An assigned Collector's different identity or pending queue must be preserved; plan a migration instead of replacing them. Use **Test server** on that Collector PC before **Collect now**.

For the [Docker Collector](../../docs/collector-wsl-docker.md), copy the encrypted file into that PC's existing ignored `collector-handoff/` folder. With its scheduler stopped and local configuration saved, run these commands on the Collector PC and enter the password at the hidden prompt:

```powershell
docker compose -f deploy/docker-compose.collector.yml run --rm collector import-setup /handoff/wsl-network-20261101-235729.linker-collector
docker compose -f deploy/docker-compose.collector.yml run --rm collector test-server
```

On the Central PC, the unlock password is protected with the current Windows user's DPAPI under `%LOCALAPPDATA%\Linker\collector-export-passwords\wsl-network-20261101-235729\unlock-password.dpapi`. Open **Show setup password.cmd** in that same private folder to view it locally, then transfer the password through a separate private channel. The DPAPI file is tied to this Windows account and is not the portable password handoff.

On 2026-11-02, this export was imported on the actual Windows Collector PC into a separate saved profile, `collector-local/wsl-ELT250330DB/config.toml`, because its source/generation differed from the previous local setup. The original settings, identities and queues were retained. Authenticated HTTPS checks passed through both the CLI and the GUI's **Test server** action against `https://187.17.53.84:8443/v1/uploads`. The Start menu shortcut opens the imported profile and retains it when refreshed. Collection remains disabled, initial history awaits approval and no records were uploaded. Docker authentication and live collection/upload remain unverified. See [WSL deployment](../../docs/wsl-deployment.md) for server operation and source setup.
