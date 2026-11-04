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

The cloud image remains uninitialized in the delivered boot disk. **First boot needs approved Internet access** to Ubuntu/Docker repositories, the Snap Store, Python packages and container registries. Allow several GiB of downloads, including the Docker Ollama runtime image. It installs the Linux desktop, Firefox, XDG browser integration and Docker Engine, builds/starts the separate Central PostgreSQL/API/worker/HTTPS project, creates the private GUI environment and desktop shortcut, then presents the login screen. Runtime image downloads have a separate bounded step before service readiness is checked. A slow first boot is installation work; the application is not ready until provisioning succeeds.

Docker Engine follows [Docker's Ubuntu installation procedure](https://docs.docker.com/engine/install/ubuntu/). Local first-boot configuration uses cloud-init's [NoCloud datasource](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html). The VM defaults to Docker-hosted local AI support, but AI is disabled and no model is downloaded or invoked by setup. Preserve its AI settings/model volumes if models are provisioned later.

## Private login handoff

The desktop account is `linker`. Each build generates a unique initial password and SSH key. The password and private key stay outside the VM bundle in the ignored, account-protected `secrets/vmware/<build-id>/` directory. The builder prints only those file paths, never their contents. Transfer login details separately through an approved secure channel. The seed contains the public SSH key and a salted password hash, not the plaintext password or private SSH key. SSH password authentication/root login are disabled; desktop login uses the initial password.

Do not put the private handoff in Git, a release archive or a public share. The Linux user is a trusted administrator with sudo and Docker access. Change its password through the desktop after first login as part of local account commissioning. Once a VM has booted, its disk contains newly generated server credentials and certificate keys; treat the running VM and its backups as private operational state.

### Automatic desktop login on the local test VM

The user requested automatic desktop login for the existing test VM. Its local `/etc/lightdm/lightdm.conf.d/60-linker-test-autologin.conf` contains:

```ini
[Seat:*]
autologin-user=linker
autologin-user-timeout=0
user-session=xfce
autologin-session=xfce
```

This setting was applied at the graphical login screen, then LightDM was restarted. An active X11 session for `linker` and the visible Central Server window with ready API/database/worker were verified. The existing account password was retained; no shared password was added to source or packages. Factory builds still require the separately supplied login handoff. To restore normal desktop login on this test VM, remove only this override while the graphical session is closed and restart LightDM; restarting it closes graphical sessions. This local preference does not change application credentials or remote authentication.

The test VM also disables its per-user Light Locker autostart with `~/.config/autostart/light-locker.desktop` containing `Hidden=true`. Xfce's `xfce4-power-manager` property `/xfce4-power-manager/lock-screen-suspend-hibernate` and `xfce4-session` property `/shutdown/LockScreen` are both false. This prevents the idle/suspend screen lock from requesting the retained account password after automatic login. The existing locker was stopped normally and the original desktop session reactivated without restarting LightDM or the containers. Current-session screen blanking/DPMS were disabled as well. Verification found an active, unlocked desktop, no locker process/window and all five Central services still running. These are local testing preferences; factory archives keep their existing login behavior. To restore locking, remove only the per-user autostart override, enable both Xfce properties and log out/in after saving work.

## Open in VMware

1. Check the artifact hashes and keep `Central Server.vmx`, `central-server.vmdk` and `seed.iso` in the same folder. Open the VMX in VMware Workstation Pro. If asked whether it was moved/copied, select **copied** for a new instance.
2. Retain the default NAT adapter for first setup. Allow outbound installation traffic according to local policy. Leave the seed ISO connected during provisioning.
3. Wait for provisioning to finish and the Xfce login screen to appear. Sign in as `linker` using the separately supplied initial password. The Central Server management window opens at desktop login; the Desktop shortcut reopens it later. Closing it leaves the server containers running.
4. Verify database/API/worker readiness in the manager. The VM is a **fresh Central Server** with no existing registrations or customer records. Its project is `linker-scada-vmware`; native PostgreSQL is private to Docker. No SCADA source database is installed or changed.

### View the containers on the local test VM

The existing test VM has a **Docker Containers** desktop shortcut. Minimize Central Server to see it, or use Alt+Tab to select the already-open **Docker-Containers** terminal window. Its read-only list refreshes every two seconds and shows running Central Server container names, status and published ports. Closing the viewer or pressing Ctrl+C stops only the display; the containers continue running.

This local shortcut uses GNOME Terminal and `/home/linker/.local/bin/linker-docker-containers`, with the VM's local Docker socket and the `linker-scada-vmware` project filter. It adds no management listener or Docker Desktop installation. The shortcut is a local test convenience and is not included in the existing r2 archive. On any deployment, `docker ps` in the Ubuntu terminal lists running containers; `docker ps -a` includes stopped containers and completed setup jobs.

### Portainer web dashboard on the existing test VM

At the user's request for Portainer access, the existing VMware VM now runs a separate local Portainer CE 2.45.3 container, `linker-portainer`. In Firefox **inside the VM**, open **https://localhost:9443**, or use the **Portainer** desktop shortcut. Its separate username is `admin`; the **Portainer Login** desktop shortcut opens the private password handoff. On first connection, Firefox may show the dashboard's self-signed certificate notice. Select the local environment, then **Containers** to see running containers and completed migration/provisioning jobs.

Only guest loopback `127.0.0.1:9443` is published; this address is not a Windows-host or remote-PC dashboard link. Edge/HTTP ports 8000/9000 are not published. The container uses the VM's local Docker socket, a separate persistent `linker-portainer-data` volume, a digest-pinned official image and `unless-stopped` restart policy. It can administer the VM's Docker engine. It is independent of the Central Compose project and was added without restarting its services. Portainer login is separate from the test desktop's automatic login.

Private initialization material is under `/root/linker-portainer` (0700; password file 0600). The user handoff is `/home/linker/.local/share/linker-portainer/login.txt` (0600 in a 0700 directory); its protected Windows copy is `secrets/vmware/0.6.2-774040beaa/portainer-login.txt`. Never commit these files or publish initialized volumes/disks. The existing Portainer volume/password must be preserved on upgrades; initial password-file provisioning does not reset an existing admin. This local installation and its shortcuts are not included in factory provisioning/r3. See [official installation](https://docs.portainer.io/start/install-ce/server/docker/linux) and [initial setup](https://docs.portainer.io/start/install-ce/server/setup).

### Browser launcher fails in earlier packages

The r2 desktop included Xfce's generic Web Browser launcher without an installed browser or XDG utilities. The current provisioner/r3 handoff installs `firefox` and `xdg-utils`; Ubuntu 24.04's Firefox package installs Mozilla's Firefox Snap. Existing VMs can install those packages without replacing their disk or server data.

The current test VM has Firefox installed, Xfce's WebBrowser helper set to Firefox and HTTP/HTTPS/HTML associations set to `firefox_firefox.desktop`. Its **Firefox Web Browser** desktop shortcut opens the installed browser. Launch through `exo-open --launch WebBrowser` was verified against the public Docker documentation, with a live Firefox process and its Docker Docs window. Browser installation does not install a Docker web administration dashboard; the local container viewer remains separate.

The builder does not install VMware itself. The PCIe-corrected configuration has powered on and reached Linux boot on Workstation 26.0.1; full first-boot provisioning and interactive desktop acceptance still need verification on the target host. Keep the existing Docker Desktop/WSL installation intact if this PC is used; do not disable Hyper-V/WSL or replace host drivers to make a VM boot without an approved separate host change.

### Ethernet0 PCIe slot error in earlier packages

Revision `r1` omitted the PCIe root ports needed by VMXNET3, allowing Workstation to assign its network adapter a legacy slot. Use the corrected `r2` package for a new extraction. For an existing VM, preserve its disk, seed, credentials, MAC and selected network: power it off, close its VMware tab/application and back up the VMX before editing. Add the missing bridge settings below, and remove the `ethernet0.pciSlotNumber` line if it contains a legacy slot below 160 (or a failed allocation of `-1`). Reopen the same VMX so Workstation assigns a suitable PCIe slot.

```text
pciBridge0.present = "TRUE"
pciBridge4.present = "TRUE"
pciBridge4.virtualDev = "pcieRootPort"
pciBridge4.functions = "8"
pciBridge5.present = "TRUE"
pciBridge5.virtualDev = "pcieRootPort"
pciBridge5.functions = "8"
pciBridge6.present = "TRUE"
pciBridge6.virtualDev = "pcieRootPort"
pciBridge6.functions = "8"
pciBridge7.present = "TRUE"
pciBridge7.virtualDev = "pcieRootPort"
pciBridge7.functions = "8"
```

Inspect an existing bridge topology before changing it; avoid duplicate keys. Do not replace an existing VMX wholesale with the factory file, because Workstation may have saved its identity, device settings or a custom network. Do not replace an initialized disk with the uninitialized package disk to repair this configuration error.

## Network commissioning and existing data

Initial HTTPS is local to the guest (`localhost`); it does not take over the current Windows/WSL endpoint. For actual remote Collectors, select an approved bridged/routed VM network and stable VM address. Stop the VM's configured server, select **Deployment → Network server**, save the VM hostname/listener/HTTPS port and restart. The listener must belong to the VM, not the Collector PC or Windows host. Network mode provides no implicit firewall permission. Keep the private database/AI ports unpublished.

### Existing test VM on the physical LAN

The current native test VM was changed to **Bridged / VMnet0**, explicitly mapped to **Intel(R) Ethernet Connection (7) I219-LM**. The host remains `187.17.53.84/24`; the LAN DHCP server assigned the VM **`187.17.53.216/24`**, gateway `187.17.53.1`. The VM has its own retained MAC, `00:0C:29:46:A9:D8`. Its previous `192.168.224.128` NAT address no longer applies. Request a DHCP reservation for this MAC before relying on the address long term; no DHCP server reservation or guessed static address was configured by this task.

Central Server now uses **Network server** mode with server/listener `187.17.53.216`, HTTPS port **`8443`** and upload endpoint `https://187.17.53.216:8443/v1/uploads`. Its public CA and private credentials/volumes were retained. From Windows, both `/v1/collector-check` and `/v1/uploads` on 8443 returned the expected `401` without a token, with full CA/IP certificate verification. Port 443 is no longer published on the VM's LAN address. This establishes host-to-VM HTTPS connectivity, not authenticated delivery from the separate Collector PC. The existing VM database remains empty with no registered sources.

Register the intended test source in this VM and export its encrypted setup to a separate test Collector profile. The new export supplies port 8443; earlier exported endpoints are not changed automatically. Keep any existing commissioned Collector identities, queue and original-server backlog intact; do not replace its setup to bypass those guards. On the actual Collector PC, verify TCP port 8443 connectivity and **Test server** before collecting. Portainer remains local to the VM at `https://localhost:9443`; bridging did not expose it to other PCs. The existing Windows/WSL installations and source database were not changed. Factory archives retain NAT for first-boot installation.

The Linux user's direct bind check for privileged port 443 encountered `EACCES`, which the existing manager reports as a bound port. Root verification confirmed the selected VM address/443 was free. The settings operation therefore ran once as `linker` in a scoped systemd job with only temporary `CAP_NET_BIND_SERVICE`, using the normal manager stop/save/start path and journaled settings backups. No permanent capabilities, global port-permission settings or port changes were introduced. A future stopped-manager settings save on a privileged port may need the same scoped administrator-assisted validation; this task did not change manager validation code.

The subsequent requested switch to 8443 used the normal, unprivileged manager stop/save/start path and required no capability grant. The VM's manager was updated to remove the mapping-backlog metric and source-list column, then reopened. Registered sources, received batches, saved versions, health and failed-job status remain visible; storage and mapping approval remain intact. Only the two manager Python files were updated with checksums and private backups. This live change does not rebuild the existing r3 archive or published Windows installers.

The current VM has subsequently been upgraded to `0012_shared_source_storage` with the [stored warehouse architecture](central-server-analysis.md#stored-warehouse-architecture). Original storage remains in `platform`, stored alarm/event facts in `warehouse`, and maintained summaries in `reporting`. New sources share the fixed schemas. The updated manager shows warehouse freshness and opens on the retained Network endpoint `187.17.53.216:8443`. The database remains an empty test installation, with no live source registered or remote Collector commissioned.

Deployment stopped only this Central project, validated an encrypted backup, rebuilt its application images and migrated/restarted with the original environment, private vaults, CA and named volumes. Portainer remains independent and loopback-only. The database/key backup locations and recovery scope are documented in [operations](operations.md#stored-warehouse-operation). Existing r3/Windows installer artifacts remain unchanged; future builds use the updated source.

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

### Text login appears instead of the desktop

The Ubuntu base can show a console login before online provisioning completes. A console prompt alone does not mean the desktop/server installation finished. Inspect the current setup state locally:

```bash
sudo cat /var/lib/linker-vm/phase
sudo test -f /var/lib/linker-vm/ready && echo 'Desktop and application setup completed'
sudo systemctl status lightdm --no-pager
ip -br address
ip route
```

If the VM has no IPv4 address/default route, desktop downloads cannot finish. Use the documented NAT adapter for initial online setup and check guest DNS/Internet access. A custom VMnet0/bridged adapter needs a working approved LAN/DHCP or static configuration. Changing only this VM's attachment to NAT does not repair the LAN bridge or commission remote Collectors; review the eventual network deployment separately.

Read the root-private provisioning log to distinguish failed downloads from an installation still in progress. After repairing connectivity, resume the same seed script in the existing VM, retaining its disk and state. Mount the original `cidata` seed read-only if it is no longer mounted after a reboot. Do not run a second provisioner alongside an active one. A reboot can report cloud-init `done` without replaying the earlier failed one-time script, so also check the Linker ready marker and recovery job result. Avoid changing existing registrations or re-extracting an empty disk to resolve a missing desktop.

VM snapshots are useful maintenance checkpoints but do not replace [database/credential backup and restore procedures](operations.md). Do not distribute a clone of an already commissioned VM as a new independent server without reviewing its identities, credentials and data.

For this development build's final artifact, executed checks, recovered guest test and remaining VMware-host acceptance, see [4 November verification evidence](vmware-build-2026-11-04.md).
