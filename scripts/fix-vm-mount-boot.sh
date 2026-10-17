#!/usr/bin/env bash
# One-shot fix for CIFS mount + lones-vdl boot on the Debian Docker VM.
# Run as root on docker-1:
#   bash /opt/Lones-VDL/scripts/fix-vm-mount-boot.sh
#
# What it does:
# - Removes broken hyphenated systemd .mount unit (path/- mismatch)
# - Comments fstab CIFS line for this share (avoid double management)
# - Mounts //192.168.0.15/lonesvdl at /mnt/lonesvdl via a oneshot service
# - Rewires lones-vdl.service to require that mount service
# - Updates deploy/.env archive path
# - Enables units and starts the stack

set -euo pipefail

SHARE="//192.168.0.15/lonesvdl"
MNT="/mnt/lonesvdl"
CRED="/etc/samba/lones-vdl.cred"
DEPLOY="/opt/Lones-VDL/deploy"
MARKER="${MNT}/.lones-vdl-mounted"
MOUNT_SVC="/etc/systemd/system/lones-vdl-archive.service"
APP_SVC="/etc/systemd/system/lones-vdl.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (su -)." >&2
  exit 1
fi

if [[ ! -f "${CRED}" ]]; then
  echo "Missing ${CRED}" >&2
  exit 1
fi

if [[ ! -f "${DEPLOY}/compose.yaml" ]]; then
  echo "Missing ${DEPLOY}/compose.yaml" >&2
  exit 1
fi

echo "==> Cleaning broken mount unit / old mountpoint"
systemctl disable --now mnt-lones-vdl-archive.mount 2>/dev/null || true
rm -f /etc/systemd/system/mnt-lones-vdl-archive.mount
if findmnt /mnt/lones-vdl-archive >/dev/null 2>&1; then
  umount /mnt/lones-vdl-archive || true
fi
if findmnt "${MNT}" >/dev/null 2>&1; then
  umount "${MNT}" || true
fi
mkdir -p "${MNT}"

echo "==> Commenting matching CIFS line in /etc/fstab (if present)"
if grep -qE '^[^#].*lones-vdl-archive|/lonesvdl' /etc/fstab; then
  cp -a /etc/fstab "/etc/fstab.bak.$(date +%Y%m%d-%H%M%S)"
  sed -i -E 's@^([^#].*[[:space:]]+/mnt/lones-vdl-archive[[:space:]].*)@# \1@' /etc/fstab
  sed -i -E 's@^([^#].*//192\.168\.0\.15/lonesvdl[[:space:]].*)@# \1@' /etc/fstab
fi

echo "==> Writing ${MOUNT_SVC}"
cat >"${MOUNT_SVC}" <<EOF
[Unit]
Description=Mount Lones VDL CIFS archive
After=network-online.target
Wants=network-online.target
Before=lones-vdl.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/mkdir -p ${MNT}
ExecStart=/bin/mount -t cifs ${SHARE} ${MNT} -o credentials=${CRED},uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8
ExecStart=/usr/bin/test -f ${MARKER}
ExecStop=/bin/umount ${MNT}
TimeoutStartSec=60

[Install]
WantedBy=multi-user.target
EOF

echo "==> Writing ${APP_SVC}"
cat >"${APP_SVC}" <<EOF
[Unit]
Description=Lones VDL Docker Compose
After=network-online.target docker.service lones-vdl-archive.service
Wants=network-online.target
Requires=docker.service lones-vdl-archive.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${DEPLOY}
ExecStartPre=/usr/bin/test -f ${MARKER}
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/docker compose up -d --build
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

echo "==> Updating ${DEPLOY}/.env archive path"
if [[ -f "${DEPLOY}/.env" ]]; then
  if grep -q '^LONES_VDL_HOST_ARCHIVE=' "${DEPLOY}/.env"; then
    sed -i "s|^LONES_VDL_HOST_ARCHIVE=.*|LONES_VDL_HOST_ARCHIVE=${MNT}|" "${DEPLOY}/.env"
  else
    echo "LONES_VDL_HOST_ARCHIVE=${MNT}" >>"${DEPLOY}/.env"
  fi
else
  echo "WARNING: ${DEPLOY}/.env missing — create from .env.example" >&2
fi

echo "==> Enabling docker"
systemctl enable docker >/dev/null
systemctl start docker

echo "==> Mounting share (first time may need marker created)"
systemctl daemon-reload
systemctl reset-failed lones-vdl-archive.service lones-vdl.service 2>/dev/null || true
systemctl enable lones-vdl-archive.service lones-vdl.service

# Mount once without marker check so we can create the marker on a fresh share.
mount -t cifs "${SHARE}" "${MNT}" \
  -o "credentials=${CRED},uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8" \
  || true
if findmnt "${MNT}" >/dev/null; then
  touch "${MARKER}"
  chmod 644 "${MARKER}" || true
  umount "${MNT}"
fi

systemctl restart lones-vdl-archive.service
systemctl restart lones-vdl.service

echo "==> Status"
systemctl --no-pager --full status lones-vdl-archive.service lones-vdl.service || true
echo
findmnt "${MNT}" || true
echo
curl -sS -m 5 http://127.0.0.1:8080/api/health || echo "health check failed"
echo
echo "Done. Reboot test: reboot; then: systemctl is-active lones-vdl-archive lones-vdl; curl -s localhost:8080/api/health"
