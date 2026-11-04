#!/usr/bin/env bash
# Executed only inside the newly created Linux guest, never on Windows/WSL.
set -euo pipefail
umask 077
exec >>/var/log/linker-vm-provision.log 2>&1
chmod 600 /var/log/linker-vm-provision.log
[[ $(id -u) == 0 ]]
[[ -f /etc/linker-vm-build.json ]]
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]]
if [[ -f /var/lib/linker-vm/ready ]]; then exit 0; fi
mkdir -p /var/lib/linker-vm /opt/linker-vm
chmod 755 /opt/linker-vm
printf 'docker-engine\n' >/var/lib/linker-vm/phase
mountpoint -q /run/linker-seed || { mkdir -p /run/linker-seed; mount -o ro -L cidata /run/linker-seed; }
install -m 644 /run/linker-seed/package/* /opt/linker-vm/
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg openssh-server sudo
# Docker CE can leave an uninstalled docker.io entry in dpkg's database.
# Preserve an installed/partially installed distribution engine, while allowing
# safe reruns of this script's own Docker CE installation.
docker_distribution_state=$(dpkg-query -W -f='${db:Status-Status}' docker.io 2>/dev/null || true)
case "$docker_distribution_state" in
  ''|not-installed|config-files) ;;
  *) echo 'Unexpected existing Docker installation; preserving it and stopping setup.'; exit 1 ;;
esac
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: noble\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/docker.asc\n' >/etc/apt/sources.list.d/docker.sources
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker.service
usermod -aG docker linker
# Present the desktop only after application provisioning is complete.
systemctl mask lightdm.service
printf 'linux-desktop\n' >/var/lib/linker-vm/phase
printf 'lightdm shared/default-x-display-manager select lightdm\n' | debconf-set-selections
apt-get install -y xfce4 lightdm xorg dbus-x11 open-vm-tools-desktop \
  libegl1 libopengl0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxkbcommon-x11-0
install -m 755 /run/linker-seed/package/install_guest.py /opt/linker-vm/install_guest.py
printf 'central-server\n' >/var/lib/linker-vm/phase
runuser -l linker -s /bin/bash -c 'python3 /opt/linker-vm/install_guest.py'
systemctl unmask lightdm.service
systemctl enable lightdm.service
systemctl set-default graphical.target
systemctl start lightdm.service
systemctl is-active --quiet lightdm.service
printf 'ready\n' >/var/lib/linker-vm/ready
chmod 644 /var/lib/linker-vm/ready
