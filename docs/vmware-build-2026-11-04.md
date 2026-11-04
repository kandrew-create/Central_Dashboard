# VMware Central Server build verification — 4 November 2026

## Scope

The deployment target is **VMware Workstation → Ubuntu 24.04/Xfce → Docker Engine → Central Server 0.6.2**. The Collector stays on its separate PC. Defaults are four virtual CPUs, 8 GiB RAM and an 80 GiB thin disk. This is a fresh server, with no migration of current registrations, credentials or customer data.

At initial build time, VMware was not installed on the development PC. The builder uses existing Docker tooling for conversion; initial guest checks used QEMU software emulation in disposable tools containers with no published host ports. Building/testing does not install VMware, change host virtualization or replace the current Windows/WSL installations. Workstation was subsequently installed by the user; the PCIe follow-up below records native power-on verification.

See [build, private handoff and first-boot instructions](vmware-linux.md).

## Executed checks

- Eight VM input, integrity, private-key boundary, transfer archive and configuration-preservation cases passed with `python -m pytest -q -p no:cacheprovider tests/test_vmware.py`.
- 63 Linux/Qt regression cases passed: `server/tests/test_qt_docker_gui.py`, `test_docker_configuration.py`, `test_docker_manager.py`, `test_windows_docker.py` and `tests/test_wsl_installer.py`.
- The pinned Ubuntu cloud image passed SHA-256 verification. A read-only `qemu-img compare` confirmed identical logical contents between the VMware VMDK and the uninitialized QCOW base used by the disposable overlay.
- The disposable guest booted Ubuntu 24.04, expanded its root filesystem to about 77 GiB, installed Docker Engine 29.9.3 and the Linux desktop, built the application images, applied Central migrations on its private PostgreSQL 17.6 and verified HTTPS using its saved CA with the expected 401 response for an unauthenticated request. API, worker, database and gateway were running; the display manager started.
- The operational host Collector audit found zero Docker/native Collectors and no installed native Collector service. Existing operational storage was retained.

The completed guest installation used preserved-state retries. This is not evidence of an uninterrupted fresh installation of the final bundle on VMware hardware.

## Corrections found by guest testing

The original emulation run reached its 40-minute test limit. Its disk and state were retained for recovery. The Docker package guard initially mistook a `not-installed` dpkg entry for an installed distribution engine; it now checks package status and still refuses an installed/partially installed conflicting engine.

The 8.47 GB unpacked Docker Ollama runtime made first-time image extraction exceed the service startup allowance. VM installation now pulls missing runtime images in a separate bounded step before service readiness. No model is downloaded or invoked, and AI remains disabled.

API logs showed successful startup and normal shutdown without a traceback, while five-second health probes timed out under emulation. The VM's generated local/Network profiles now allow 30-second API health probes and 120 seconds of startup grace; the installer allows ten minutes for service readiness. Existing custom health settings remain intact. These changes are confined to VM installation and do not edit current Windows/WSL profiles.

The test harness also uses SSH connection reuse, tolerates temporary read-only SSH readiness timeouts and permits a longer GUI probe. Failed probes do not reset the guest, credentials or database.

## Final guest evidence and handoff

The preserved-disk recheck passed: server readiness, the empty isolated database, readable alarm analysis, disabled AI, the native Linux Qt management window and the active display manager. The Qt window displayed the Alarm analysis page with zero occurrences/versions/mappings and the **Linux / Docker** environment caption. Its screenshot is saved locally as `dist/vmware/0.6.2-774040beaa/validation-manager.png`. The disposable guest shut down normally and its tools container exited with code zero. All four stopped test containers were removed.

The initial verified Linux/application transfer archive was `dist/vmware/Linker-Central-Server-VMware-0.6.2-774040beaa-r1.zip`, with a matching `.zip.sha256` sidecar. Its historical SHA-256:

```text
1c2d8c2e9807fc340c9e0a517de777619dae0d199386a9d935059b8d9d86af02
```

Its eight allowlisted files are the VMX, uninitialized VMDK, corrected seed ISO, three checksum sidecars, build/validation metadata and the setup guide. ZIP integrity and artifact hashes passed. Initialized test disks, private credentials and logs are excluded. The original archive without a revision was intermediate; `r1` has since been superseded by the PCIe correction below.

The manifest retains build ID `0.6.2-774040beaa` and records packaging revision one. Its separately protected local login handoff is `secrets/vmware/0.6.2-774040beaa/login.txt`; the private SSH key stays beside it, outside the archive. No plaintext password or private SSH key was published.

## Remaining target checks

After the PCIe repair, native Workstation power-on and Linux kernel/root-filesystem boot were observed. The later NAT recovery below completed native provisioning and reached the graphical login screen. The user's subsequent test-only autologin request produced a logged-in Xfce session and a visibly ready Central Server window. The earlier live Qt check used the offscreen platform. Remote Collector connectivity/commissioning, production load and migration/recovery acceptance were not performed by this build task.

## Native PCIe correction

Workstation 26.0.1 build 25688693 reported `No PCIe slot available for Ethernet0` on the user's extracted copy. Its VMX lacked PCIe root ports and contained a VMXNET3 assignment to legacy slot 21. The generator now includes the standard PCI bridge and four eight-function PCIe root ports, with no fixed network slot. The existing topology test now checks PCIe capacity and absence of a fixed Ethernet slot; all eight VM tests passed.

With the selected VM stopped and its VMware window closed normally, the deployed VMX was backed up and patched in place. Only the missing bridge settings and invalid Ethernet slot assignment changed. Its disk/seed references, UUID, MAC and custom `VMnet0` network selection were preserved; the disk was not replaced. Workstation assigned Ethernet0 to slot 160, reported one running VM, and its new log had no PCIe slot error. A window-only capture showed Linux mounting its root filesystem. The VM was left running for the user's first-boot setup.

The updated handoff is `dist/vmware/Linker-Central-Server-VMware-0.6.2-774040beaa-r2.zip` with its own SHA-256 sidecar. It uses the same uninitialized disk, seed and separate private login handoff as `r1`; its factory VMX includes the PCIe fix. Existing deployments should repair their VMX in place using [the recovery steps](vmware-linux.md#ethernet0-pcie-slot-error-in-earlier-packages).

The r2 archive passed artifact and ZIP integrity checks. Its SHA-256 is `8ff568efd7471c2d2e4fe24e4c02d62fd49449820126c43e58d87f44e30dd03d`.

## Native missing-desktop recovery

The user's running VM initially showed only a console login. Guest inspection found provisioning failed at `docker-engine`: the desktop was absent, LightDM inactive, and its custom VMnet0 adapter had no IPv4 address or default route. Ubuntu repository downloads had failed. This was a connectivity failure before desktop installation, rather than completed installation without a graphical session.

The selected guest was shut down normally, its VMX backed up, and only its attachment changed to the documented NAT mode with VMware's CLI. Its MAC, disk, seed and credentials were retained. No host adapter, DHCP/NAT service configuration, Windows/WSL server setting or SCADA source was changed. After restart the guest obtained `192.168.224.128`, resolved repository names and reached the official Docker download endpoint. Guest diagnosis used authenticated in-memory VIX calls; the private password was not placed in command arguments or printed.

The same original seed was mounted read-only and its setup script resumed in a scoped systemd recovery unit after checking that the previous first-boot job was no longer running. The recovery exited successfully, created the Linker ready marker and activated LightDM. Docker PostgreSQL/API/Ollama health checks passed; the worker and HTTPS gateway were running, and migrations/runtime provisioning exited zero. The installer verified HTTPS with its saved CA and expected authentication rejection. A capture of only the selected VMware window confirmed the graphical **Central Server Administrator** login screen. That display name belongs to account `linker`; its private initial password remains unchanged.

The VM remains running on NAT. This proves recovered native provisioning and a visible graphical login, not an uninterrupted factory installation or remote Collector commissioning. The shipped r2 archive is unchanged; its earlier validation metadata reflects evidence available when that archive was built. The Collector remains on its separate PC and stopped on this development host.

## Local test autologin verification

At the user's explicit request, a local LightDM override enabled automatic login as `linker` into Xfce. It was applied while the VM was at the greeter; LightDM restarted without stopping the server containers. Account password state remained set, and no password change was performed. Read-only session inspection confirmed an active X11 user session, `xfce4-session` and the Central Server manager process. A window-only VMware capture confirmed the actual desktop and **Central Server - Linux / Docker** overview, with HTTPS API, PostgreSQL and background worker marked ready and zero registered sources, batches and saved versions. No credential entry was needed. This changes only the existing test VM's desktop login preference, not the factory builder, shipped archives or application/SSH authentication.

## Local container viewer

Added and opened a **Docker Containers** desktop shortcut on the current test VM. It launches an existing GNOME Terminal with a two-second `watch` of the local Docker socket, filtered to `linker-scada-vmware`, displaying container names, status and ports. Native user-context inspection verified the live viewer process, successful non-root Docker access and all five running services: caddy, worker, API, database and Ollama. No containers were started/stopped, no management port was opened and no additional software was installed. This local read-only convenience does not modify the builder or r2 archive.

## Missing-browser correction

The Web Browser launcher failed because no Firefox/Chromium/Web browser binary and no `xdg-utils` were installed. The existing VM received Ubuntu's `firefox` and `xdg-utils` packages in a scoped installation job, which exited zero. Mozilla's Firefox Snap version `159.0-1` was present. Xfce's helper and the user's HTTP/HTTPS/HTML associations were set to Firefox, preserving a backup of existing helper settings. A local Firefox desktop shortcut was added. Launching the public Docker documentation through Xfce's normal `exo-open` path returned zero; user-context inspection confirmed a running Firefox process, a **Docker Docs — Mozilla Firefox** X11 window and no display/permission/command-not-found launch errors.

The provisioner now includes both packages for future first boot, and the r3 handoff updates its seed. This verification used the existing recovered native VM; it is not an uninterrupted first boot of r3. Browser installation/configuration did not change the Central Server database, Docker projects, credentials or Collector runtime, and no web administration listener was installed.

The latest handoff is `dist/vmware/Linker-Central-Server-VMware-0.6.2-774040beaa-r3.zip`, with SHA-256 `7735c265cb8dbe324204facfa367b7d3f30b1073b9e3ce704c03197251cc8d8f` and a matching sidecar. Its eight-file allowlist, artifact hashes and ZIP integrity passed; its disk remains identical to the uninitialized r2 disk. The updated seed passes Bash syntax validation. Initialized disks, private credentials and local desktop preferences remain excluded.

## Test desktop password-prompt removal

The user's later request to remove the Central Dashboard login was traced to Light Locker: the `linker` desktop was still logged in, while a separate LightDM greeter was active. The manager has no separate dashboard sign-in. Kept the existing automatic-login override, disabled Light Locker's per-user autostart and Xfce lock-on-suspend/session settings, stopped only that user's locker with SIGTERM, and reactivated the existing desktop session. No logout, display-manager restart or account password removal was needed. Read-only checks reported `Active=yes`, `State=active`, `LockedHint=no`, a desktop window and no locker process/window. All five Central services remained running, with API/database/Ollama healthy. These local test preferences do not alter r3, factory provisioning, upload authentication or database credentials.

## Requested local Portainer installation

Following the user's clarification that Portainer was wanted to access Docker containers, installed Portainer CE 2.45.3 separately on the existing native VM. Docker Engine reports 29.9.3; this is newer than the vendor's listed 29.8.1 validation target, so verification below is limited to the exercised operations. The official LTS image resolved to `portainer/portainer-ce@sha256:3609c307943bca8e5c492f69ddd6965df177208b50678a4cff28391c8dd4e96e`; the container runs that digest, uses `linker-portainer-data` and restarts unless stopped. Only `127.0.0.1:9443` is published; ports 8000/9000 are not. No Central container was restarted and no host/WSL/Collector configuration changed.

Generated a separate random admin password in private files, supplied it through a read-only password-file mount, and retained protected Linux/Windows handoffs without printing credentials or placing them in process arguments. Added Portainer and private-login desktop shortcuts. HTTPS verification trusted the exact certificate fetched from the local installation, with SHA-256 `9123d7bc1c943b5b5b90a9f07d70cf29912eb5950746cae21366f093bcf60b60`. Authenticated API calls confirmed local Docker environment 1 and listed five running Central services, healthy API/database/Ollama, and two setup jobs exited zero. Checked the actual Docker port bindings, restart policy and image digest. Xfce browser launch returned zero. Interactive browser sign-in and container mutations were not exercised; no mutation was needed to verify container visibility. This local dashboard is not included in r3 or factory builds.

## Bridged LAN simulation

At the user's request to simulate two PCs on the same physical subnet, shut down the existing guest normally, backed up its VMX, and changed only its connection type from NAT to bridged with VMware's CLI while offline. Retained disk, UUID, MAC and PCIe topology. Dismissed VMware's informational side-channel mitigation hint without changing mitigations. Initial bridged boot had no IPv4 or received packets. Backed up VMware's network registry and used its elevated Virtual Network Editor, after the user approved Windows UAC, to map VMnet0 explicitly to the Intel I219-LM Ethernet adapter. Preserved the existing DHCP/NAT configuration files byte-for-byte and retained VMnet8 at `192.168.224.1`. VMware may serialize default network entries when its editor loads/saves; no Restore Defaults, host driver replacement or host network reset was used.

Renewing the guest interface's DHCP lease obtained `187.17.53.216/24` from `187.17.53.1`, on the host's `187.17.53.84/24` subnet. Windows neighbor discovery matched the retained VM MAC `00:0C:29:46:A9:D8`. No address was guessed or taken from another PC. The DHCP lease is not a reservation.

Closed the native manager through its normal WM_DELETE_WINDOW path, then used its existing backend to apply Network mode, server/listener `187.17.53.216` and retained HTTPS port 443. The first preflight failed before stopping/saving because unprivileged Linux bind returned `EACCES`; root's bind confirmed the port was free. Repeated only the uncommitted settings operation in a `linker` systemd job with temporary `CAP_NET_BIND_SERVICE`. That job exited zero with API/database/worker ready. No credential mutation was retried; no permanent capability, privileged-port sysctl or application validation change was made. The manager was reopened to load the saved settings.

Final checks confirmed unchanged non-network environment/credential hash, identical named-volume inventory, unchanged public CA and zero sources/batches/revisions before/after. Only VM LAN port 443 is published by the HTTPS gateway; HTTP 80 is no longer published, while Portainer 9443 stays loopback-only. Windows reached the VM's SSH/HTTPS ports, and CA/IP-verified HTTPS POSTs to both upload/check endpoints returned expected unauthenticated 401 responses. Ubuntu UFW was inactive; no firewall rules were changed. The original WSL project's five services retained their eleven-hour uptime, host IP stayed unchanged, and no native or Docker operational Collector was running here. Tests on the separate Collector PC, authenticated upload/replay and router reservation remain outstanding. This live configuration does not alter the r3 archive or factory NAT defaults.

## HTTPS 8443 and manager display update

At the user's request, changed only the native VM's saved HTTPS port from 443 to 8443 through the manager's normal stop/save/start backend. This ran as `linker` without extra capabilities. The manager closed normally before applying settings and updating its files, then reopened to load the new endpoint. Verified ready API/database/worker, unchanged source/batch/revision counts (all zero), unchanged non-network credential environment hash, identical named-volume inventory and unchanged public CA. Windows completed CA/IP-verified HTTPS POSTs to upload/check endpoints at `187.17.53.216:8443`, receiving the expected unauthenticated 401 responses. TCP 8443 connected; the old LAN port 443 no longer connected. Caddy maps only `187.17.53.216:8443` to its container port 443. Collector-PC authenticated delivery remains untested.

Removed the mapping-backlog metric/help text and source-list count column from both Windows/Tk and Linux/Qt manager source. Updated only the two manager files in the VM with validated checksums, preserved original files in a root-private backup, and reopened its manager. Kept backend counts, quarantine, approved mappings, original records and received-batch totals unchanged. The Linux/Qt UI regression suite ran against the VM's updated source with mocked services: 24 tests passed, none skipped. Windows manager regressions: 24 passed and two skipped. No PostgreSQL integration suite was run because no database/protocol/queue implementation changed. Existing r3/Windows release artifacts were not replaced. Source formatting checks passed.

## Stored warehouse implementation and deployment

First pushed the accumulated desktop/network/status work to origin/main as `f9e0da0`. Then implemented `0011_stored_warehouse` (stored alarm/event facts, durable incremental occurrence/day queues and maintained summaries) and `0012_shared_source_storage` (new sources share storage, existing native table OIDs/history remain compatible). Added an independent bounded worker refresh loop, safe source-scoped freshness feedback and runtime-owner checks. Canonical revisions, receipts, original fields/timestamps and mapping rules are retained.

Executed the warehouse/delivery/security matrix on two freshly initialized, private loopback-only disposable PostgreSQL clusters: **132 passed, 6 skipped on each of PostgreSQL 17 and 18**. The 16 warehouse acceptance cases include stored grain/version deduplication, UTC/ordering uncertainty, separate registered-event identity, mapping/AI separation, customer RLS, denied maintenance/raw reads, owner-membership rejection, locked-queue recovery, failed projection retry, committed authenticated API processing/replay, new shared-source registration, and real upgrade/downgrade backfill with original payload/OID preservation. The six skips per version are Linux-only Docker-agent vault integration checks; these were not executed by the Windows matrix. Existing Starlette/httpx deprecation warning remains.

The native VM upgrade shut down only `linker-scada-vmware`, brought back its existing database for backup, retained its old application image under a private local rollback tag, encrypted a custom-format pg_dump plus original files/settings/vaults, and verified GCM decryption/authentication plus pg_restore archive listing. It copied only allowlisted files with checksums, rebuilt the selected server images, and applied Alembic head before restarting. PostgreSQL reported `0012_shared_source_storage`; original registration/generation/credential/history fingerprints, native OIDs, complete environment hash, CA and named-volume inventory matched. The VM had zero sources/batches/versions before and after; no live SCADA data was used. It now has nine warehouse/reporting physical tables and no pending occurrence work.

The actual restricted worker account successfully ran bounded refresh, with no recent warehouse-error log entry. Windows CA/IP-verified HTTPS on `187.17.53.216:8443` returned the expected unauthenticated 401. Reopened the native manager with the new source and ran Linux/Qt/deployment-manager regressions against mocked services: **48 passed, none skipped**. Windows manager regressions: **24 passed, two skipped** because those cases could not create a desktop display. Python syntax, Compose configuration and Git whitespace checks passed.

Private upgrade/backup records remain in `/root/linker-warehouse-upgrade`; its separately protected key remains in `/root/linker-warehouse-backup-keys`. No initialized disk, private key, database backup, decrypted state or handoff was staged. Existing WSL/Windows deployments, Collector state and factory/r3 release artifacts were retained. Production load/thousands-source capacity, full backup restoration, historical dimension labels, retention/partitioning and authenticated delivery from the actual remote Collector remain unverified or future work as described in [warehouse scope](central-server-analysis.md#stored-warehouse-architecture).
