# VMware Central Server build verification — 4 November 2026

## Scope

The deployment target is **VMware Workstation → Ubuntu 24.04/Xfce → Docker Engine → Central Server 0.6.2**. The Collector stays on its separate PC. Defaults are four virtual CPUs, 8 GiB RAM and an 80 GiB thin disk. This is a fresh server, with no migration of current registrations, credentials or customer data.

VMware is not installed on the development PC. The builder uses existing Docker tooling for conversion; guest checks use QEMU software emulation in disposable tools containers with no published host ports. Building/testing does not install VMware, change host virtualization or replace the current Windows/WSL installations.

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

The final transfer archive is `dist/vmware/Linker-Central-Server-VMware-0.6.2-774040beaa-r1.zip`, with a matching `.zip.sha256` sidecar. SHA-256:

```text
1c2d8c2e9807fc340c9e0a517de777619dae0d199386a9d935059b8d9d86af02
```

Its eight allowlisted files are the VMX, uninitialized VMDK, corrected seed ISO, three checksum sidecars, build/validation metadata and the setup guide. ZIP integrity and artifact hashes passed. Initialized test disks, private credentials and logs are excluded. The earlier archive without `-r1` was an intermediate build; use this corrected handoff.

The manifest retains build ID `0.6.2-774040beaa` and records packaging revision one. Its separately protected local login handoff is `secrets/vmware/0.6.2-774040beaa/login.txt`; the private SSH key stays beside it, outside the archive. No plaintext password or private SSH key was published.

## Remaining target checks

Actual VMware boot, graphics and host compatibility remain unverified because VMware is absent here. The live Qt check uses the offscreen platform; an active display manager does not establish interactive VMware desktop acceptance. Remote Collector connectivity/commissioning, production load and migration/recovery acceptance were not performed by this build task.
