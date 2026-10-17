#!/usr/bin/env bash
# One-shot fix for CIFS mount + lones-vdl boot on the Debian Docker VM.
# Run as root on docker-1:
#   cd /opt/Lones-VDL && git pull origin main
#   bash /opt/Lones-VDL/scripts/fix-vm-mount-boot.sh
#
# Boot strategy: oneshot units run bash retry loops (Restart= is unreliable
# for Type=oneshot). Mount waits for NAS reachability; app waits for marker.

set -euo pipefail

SHARE="//192.168.0.15/lonesvdl"
NAS_IP="192.168.0.15"
MNT="/mnt/lonesvdl"
CRED="/etc/samba/lones-vdl.cred"
DEPLOY="/opt/Lones-VDL/deploy"
MARKER="${MNT}/.lones-vdl-mounted"
MOUNT_SVC="/etc/systemd/system/lones-vdl-archive.service"
APP_SVC="/etc/systemd/system/lones-vdl.service"
MOUNT_HELPER="/usr/local/sbin/lones-vdl-mount-archive.sh"
APP_HELPER="/usr/local/sbin/lones-vdl-start.sh"

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

echo "==> Writing helpers ${MOUNT_HELPER} / ${APP_HELPER}"
cat >"${MOUNT_HELPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SHARE="${SHARE}"
NAS_IP="${NAS_IP}"
MNT="${MNT}"
CRED="${CRED}"
MARKER="${MARKER}"
mkdir -p "\${MNT}"
# Already mounted with marker → success
if findmnt "\${MNT}" >/dev/null 2>&1 && [[ -f "\${MARKER}" ]]; then
  exit 0
fi
# Retry until NAS is reachable and mount succeeds (boot race).
for i in \$(seq 1 60); do
  if ping -c1 -W2 "\${NAS_IP}" >/dev/null 2>&1; then
    if findmnt "\${MNT}" >/dev/null 2>&1 || \\
      mount -t cifs "\${SHARE}" "\${MNT}" \\
        -o "credentials=\${CRED},uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8"
    then
      if [[ -f "\${MARKER}" ]]; then
        exit 0
      fi
      echo "mounted but marker missing: \${MARKER}" >&2
      exit 1
    fi
  fi
  sleep 2
done
echo "gave up mounting \${SHARE} after retries" >&2
exit 1
EOF
chmod 755 "${MOUNT_HELPER}"

cat >"${APP_HELPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
MARKER="${MARKER}"
DEPLOY="${DEPLOY}"
# Wait for archive marker (mount unit / helper may still be settling).
for i in \$(seq 1 60); do
  if [[ -f "\${MARKER}" ]] && findmnt "$(dirname "${MARKER}")" >/dev/null 2>&1; then
    cd "\${DEPLOY}"
    exec docker compose up -d --build
  fi
  sleep 2
done
echo "gave up waiting for \${MARKER}" >&2
exit 1
EOF
chmod 755 "${APP_HELPER}"

echo "==> Writing ${MOUNT_SVC}"
cat >"${MOUNT_SVC}" <<EOF
[Unit]
Description=Mount Lones VDL CIFS archive
After=network-online.target docker.service
Wants=network-online.target
Before=lones-vdl.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${MOUNT_HELPER}
ExecStop=/bin/umount ${MNT}
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF

echo "==> Writing ${APP_SVC}"
cat >"${APP_SVC}" <<EOF
[Unit]
Description=Lones VDL Docker Compose
After=network-online.target docker.service lones-vdl-archive.service
Wants=network-online.target lones-vdl-archive.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${DEPLOY}
ExecStart=${APP_HELPER}
ExecStop=/usr/bin/docker compose -f ${DEPLOY}/compose.yaml --project-directory ${DEPLOY} down
TimeoutStartSec=180

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

echo "==> Enabling docker + network-online wait"
systemctl enable docker >/dev/null
systemctl start docker
if command -v apt-get >/dev/null 2>&1; then
  if ! systemctl list-unit-files ifupdown-wait-online.service 2>/dev/null | grep -q ifupdown-wait-online; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y ifupdown iputils-ping >/dev/null 2>&1 || true
  else
    DEBIAN_FRONTEND=noninteractive apt-get install -y iputils-ping >/dev/null 2>&1 || true
  fi
fi
if systemctl list-unit-files systemd-networkd-wait-online.service >/dev/null 2>&1; then
  systemctl enable systemd-networkd-wait-online.service >/dev/null 2>&1 || true
fi
if systemctl list-unit-files NetworkManager-wait-online.service >/dev/null 2>&1; then
  systemctl enable NetworkManager-wait-online.service >/dev/null 2>&1 || true
fi
if systemctl list-unit-files ifupdown-wait-online.service >/dev/null 2>&1; then
  systemctl enable ifupdown-wait-online.service >/dev/null 2>&1 || true
fi

echo "==> Ensuring marker exists on share"
systemctl daemon-reload
systemctl reset-failed lones-vdl-archive.service lones-vdl.service 2>/dev/null || true
systemctl enable lones-vdl-archive.service lones-vdl.service

mount -t cifs "${SHARE}" "${MNT}" \
  -o "credentials=${CRED},uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8" \
  || true
if findmnt "${MNT}" >/dev/null; then
  touch "${MARKER}"
  chmod 644 "${MARKER}" || true
  umount "${MNT}" || true
fi

systemctl start lones-vdl-archive.service
systemctl start lones-vdl.service

echo "==> Status"
systemctl --no-pager --full status lones-vdl-archive.service lones-vdl.service || true
echo
findmnt "${MNT}" || true
echo
curl -sS -m 5 http://127.0.0.1:8080/api/health || echo "health check failed"
echo
echo "Done. Reboot test:"
echo "  reboot"
echo "  systemctl is-active lones-vdl-archive.service lones-vdl.service"
echo "  curl -s http://127.0.0.1:8080/api/health"
echo "If still bad: journalctl -u lones-vdl-archive.service -u lones-vdl.service -b --no-pager"
