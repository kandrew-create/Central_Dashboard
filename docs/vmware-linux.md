# VMware Linux desktop with Docker Central Server

This builds a **VMware virtual machine running Ubuntu 24.04 LTS, Xfce, Docker Engine and the Central Server manager**. Docker runs inside Linux. The host needs VMware Workstation Pro (or a compatible VMware host); Docker Desktop inside the guest and nested hypervisor extensions are not required. The SCADA Collector remains on its separate PC and is not configured as a VM service.

The builder uses a Docker tools container for image conversion and isolated guest validation. That container is build tooling, not the deployment architecture. No VMware Windows drivers, BIOS features, host services, firewall rules or existing Windows/WSL application settings are changed by building the bundle.

## Build and artifacts

From the repository with its development Python environment and a running local Linux Docker engine:

```powershell
& .venv/Scripts/python.exe -m deploy.vmware.build
```

Default allocation is 4 vCPUs, 8 GiB RAM and an 80 GiB thin-provisioned disk. Options `--cpus` and `--memory-mb` adjust the allocation. The Ubuntu image is pinned to release build `20261017` and checked against its [official SHA-256 manifest](https://cloud-images.ubuntu.com/releases/noble/release-20261017/SHA256SUMS). Build inputs include only allowlisted application files, not this PC's databases, queues, tokens, private certificates or `.env`.

Fresh outputs are under `dist/vmware/0.6.2-<build-id>`:

- `Central Server.vmx`: VMware machine configuration using UEFI, a generated network identity and NAT.
- `central-server.vmdk`: thin VMware boot disk.
- `seed.iso`: first-boot configuration and verified application/installation tools.
- SHA-256 sidecars and `build.json`: artifact integrity and resource metadata.

Create a transfer archive after building:

```powershell
& .venv/Scripts/python.exe -m deploy.vmware.package --bundle 'dist/vmware/0.6.2-<build-id>'
```

The archive uses an explicit file allowlist and verifies the VM artifact hashes and ZIP integrity. It excludes private login files, initialized validation disks, local logs and work directories. A separate SHA-256 sidecar accompanies the ZIP. Transfer the login handoff separately.

The cloud image remains uninitialized in the delivered boot disk. **First boot needs approved Internet access** to Ubuntu/Docker repositories, Python packages and container registries. Allow several GiB of downloads, including the Docker Ollama runtime image. It installs the Linux desktop and Docker Engine, builds/starts the separate Central PostgreSQL/API/worker/HTTPS project, creates the private GUI environment and desktop shortcut, then presents the login screen. Runtime image downloads have a separate bounded step before service readiness is checked. A slow first boot is installation work; the application is not ready until provisioning succeeds.

Docker Engine follows [Docker's Ubuntu installation procedure](https://docs.docker.com/engine/install/ubuntu/). Local first-boot configuration uses cloud-init's [NoCloud datasource](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html). The VM defaults to Docker-hosted local AI support, but AI is disabled and no model is downloaded or invoked by setup. Preserve its AI settings/model volumes if models are provisioned later.

## Private login handoff

The desktop account is `linker`. Each build generates a unique initial password and SSH key. The password and private key stay outside the VM bundle in the ignored, account-protected `secrets/vmware/<build-id>/` directory. The builder prints only those file paths, never their contents. Transfer login details separately through an approved secure channel. The seed contains the public SSH key and a salted password hash, not the plaintext password or private SSH key. SSH password authentication/root login are disabled; desktop login uses the initial password.

Do not put the private handoff in Git, a release archive or a public share. The Linux user is a trusted administrator with sudo and Docker access. Change its password through the desktop after first login as part of local account commissioning. Once a VM has booted, its disk contains newly generated server credentials and certificate keys; treat the running VM and its backups as private operational state.

## Open in VMware

1. Check the artifact hashes and keep `Central Server.vmx`, `central-server.vmdk` and `seed.iso` in the same folder. Open the VMX in VMware Workstation Pro. If asked whether it was moved/copied, select **copied** for a new instance.
2. Retain the default NAT adapter for first setup. Allow outbound installation traffic according to local policy. Leave the seed ISO connected during provisioning.
3. Wait for provisioning to finish and the Xfce login screen to appear. Sign in as `linker` using the separately supplied initial password. The Central Server management window opens at desktop login; the Desktop shortcut reopens it later. Closing it leaves the server containers running.
4. Verify database/API/worker readiness in the manager. The VM is a **fresh Central Server** with no existing registrations or customer records. Its project is `linker-scada-vmware`; native PostgreSQL is private to Docker. No SCADA source database is installed or changed.

The builder does not install VMware itself. VMware availability, host/guest compatibility, graphics and boot behavior need verification on the actual VMware host. Keep the existing Docker Desktop/WSL installation intact if this PC is used; do not disable Hyper-V/WSL or replace host drivers to make a VM boot without an approved separate host change.

## Network commissioning and existing data

Initial HTTPS is local to the guest (`localhost`); it does not take over the current Windows/WSL endpoint. For actual remote Collectors, select an approved bridged/routed VM network and stable VM address. Stop the VM's configured server, select **Deployment → Network server**, save the VM hostname/listener/HTTPS port and restart. The listener must belong to the VM, not the Collector PC or Windows host. Network mode provides no implicit firewall permission. Keep the private database/AI ports unpublished.

This build does not migrate the existing Central database, source IDs, generations, credentials or pending Collector state. Do not replace an assigned Collector's setup to switch servers while it has old identity/queue state. Use a reviewed migration when continuing the existing installation. For a genuinely new source/server relationship, register the source, export an encrypted Collector setup and verify **Test server** on each actual remote PC before declaring commissioning complete.

## Validation and recovery

`deploy/vmware/validate_guest.py` can boot a disposable overlay of the base disk under software-emulated QEMU, inside an isolated Docker tools container without published host ports. It checks Linux Docker readiness, the fresh database, alarm analysis, disabled AI, the native Linux Qt window and display manager, then shuts down that disposable guest. It does not initialize the delivered disk or touch current host servers.

With a fresh bundle and its private key kept outside it, use the portable validation wrapper:

```powershell
& .venv/Scripts/python.exe -m deploy.vmware.verify --bundle '<fresh VM folder>' --ssh-key '<private id_ed25519 path>'
```

It verifies checksums first, limits the test container to 6 GiB/4 CPUs (4 GiB guest RAM), publishes no host ports and stops/removes only its own test container. Software CPU emulation can take up to two hours for online desktop/application provisioning. Existing validation state is preserved; use a new extracted copy for another run. Guest validation does not establish actual VMware graphics/boot compatibility or remote Collector commissioning.

First-boot status/logs inside the guest are `/var/lib/linker-vm/phase`, `/var/lib/linker-vm/ready` and the root-private `/var/log/linker-vm-provision.log`. A failed provision retains its partial settings, data and logs. Diagnose it through the supplied SSH key and retry the same guest script after fixing the underlying network/package issue; never clear data, replace keys or reset Docker volumes to bypass a failure. The installer preserves existing settings and refuses identity/storage mismatches on rerun.

The VM's generated local and Network profiles provide extra API health startup grace for slower virtual CPUs. Custom health settings are retained on rerun. Failed components still block installation, and the ready marker is written only after application provisioning and the display manager succeed.

VM snapshots are useful maintenance checkpoints but do not replace [database/credential backup and restore procedures](operations.md). Do not distribute a clone of an already commissioned VM as a new independent server without reviewing its identities, credentials and data.

For this development build's final artifact, executed checks, recovered guest test and remaining VMware-host acceptance, see [4 November verification evidence](vmware-build-2026-11-04.md).
