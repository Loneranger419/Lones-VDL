#!/usr/bin/env bash
# Collect Lone's VDL host / Docker / mount status into a report file.
# Usage (on the Debian host):
#   sudo bash scripts/host-status.sh
#   sudo bash scripts/host-status.sh /tmp/lones-vdl-status.txt

set -u

OUT="${1:-./lones-vdl-host-status-$(date +%Y%m%d-%H%M%S).txt}"
ARCHIVE_MNT="${LONES_VDL_ARCHIVE_MNT:-/mnt/lones-vdl-archive}"
MARKER="${ARCHIVE_MNT}/.lones-vdl-mounted"

# Best-effort locate deploy dir (override with LONES_VDL_DEPLOY_DIR).
DEPLOY_DIR="${LONES_VDL_DEPLOY_DIR:-}"
if [[ -z "${DEPLOY_DIR}" ]]; then
  for candidate in \
    /root/Lones-VDL/deploy \
    /home/*/Lones-VDL/deploy \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy"
  do
    # shellcheck disable=SC2086
    for path in ${candidate}; do
      if [[ -f "${path}/compose.yaml" ]]; then
        DEPLOY_DIR="${path}"
        break 2
      fi
    done
  done
fi

section() {
  printf '\n======== %s ========\n' "$1"
}

run() {
  local label="$1"
  shift
  printf '\n--- %s ---\n' "${label}"
  printf '+ %s\n' "$*"
  if "$@" 2>&1; then
    :
  else
    printf '(exit %s)\n' "$?"
  fi
}

{
  section "Lone's VDL host status report"
  printf 'Generated: %s\n' "$(date -Is)"
  printf 'Host: %s\n' "$(hostname -f 2>/dev/null || hostname)"
  printf 'User: %s (uid=%s)\n' "$(id -un)" "$(id -u)"
  printf 'Archive mount: %s\n' "${ARCHIVE_MNT}"
  printf 'Deploy dir: %s\n' "${DEPLOY_DIR:-"(not found)"}"

  section "System"
  run "uname" uname -a
  run "uptime" uptime
  run "timedatectl" timedatectl

  section "Enabled / active units"
  run "is-enabled docker" systemctl is-enabled docker
  run "is-enabled lones-vdl" systemctl is-enabled lones-vdl.service
  run "is-active docker" systemctl is-active docker
  run "is-active lones-vdl" systemctl is-active lones-vdl.service
  run "is-active archive mount" systemctl is-active "mnt-lones-vdl-archive.mount"

  section "Unit status"
  run "docker.service" systemctl status docker --no-pager -l
  run "lones-vdl.service" systemctl status lones-vdl.service --no-pager -l
  run "mnt-lones-vdl-archive.mount" systemctl status mnt-lones-vdl-archive.mount --no-pager -l

  section "Boot journal (this boot)"
  run "journalctl lones-vdl" journalctl -u lones-vdl.service -b --no-pager
  run "journalctl docker (tail)" journalctl -u docker.service -b --no-pager -n 80

  section "Archive mount"
  run "findmnt" findmnt "${ARCHIVE_MNT}"
  run "ls -ld mountpoint" ls -ld "${ARCHIVE_MNT}"
  run "stat mountpoint" stat "${ARCHIVE_MNT}"
  run "marker file" test -f "${MARKER}"
  if [[ -f "${MARKER}" ]]; then
    printf 'MARKER_OK %s\n' "${MARKER}"
  else
    printf 'MARKER_MISSING %s\n' "${MARKER}"
  fi
  run "fstab lones lines" grep -n -i 'lones\|cifs\|nfs' /etc/fstab || true
  run "mount -a dry verify" findmnt --verify

  section "Docker"
  run "docker version" docker version
  run "docker info (short)" docker info --format 'ServerVersion={{.ServerVersion}} Swarm={{.Swarm.LocalNodeState}} RootDir={{.DockerRootDir}}'
  run "docker ps -a" docker ps -a
  run "docker volume ls" docker volume ls

  if [[ -n "${DEPLOY_DIR}" && -f "${DEPLOY_DIR}/compose.yaml" ]]; then
    section "Compose (${DEPLOY_DIR})"
    run "compose ps" docker compose -f "${DEPLOY_DIR}/compose.yaml" --project-directory "${DEPLOY_DIR}" ps -a
    if [[ -f "${DEPLOY_DIR}/.env" ]]; then
      run "deploy .env (redacted)" bash -c "
        grep -E '^[A-Z0-9_]+=' '${DEPLOY_DIR}/.env' \
          | sed -E 's/(TOKEN|PASSWORD|SECRET|CREDENTIAL|COOKIE)=.*/\1=***REDACTED***/I'
      "
    else
      printf 'No %s/.env\n' "${DEPLOY_DIR}"
    fi
  else
    section "Compose"
    printf 'Deploy directory with compose.yaml not found.\n'
    printf 'Set LONES_VDL_DEPLOY_DIR=/path/to/Lones-VDL/deploy and re-run.\n'
  fi

  section "HTTP health (localhost)"
  run "curl health" curl -sS -m 5 http://127.0.0.1:8080/api/health || true

  section "Disk"
  run "df -h" df -h
  run "df archive" df -h "${ARCHIVE_MNT}" 2>/dev/null || true

  section "End of report"
} | tee "${OUT}"

printf '\nReport written to: %s\n' "$(readlink -f "${OUT}" 2>/dev/null || realpath "${OUT}" 2>/dev/null || echo "${OUT}")"
