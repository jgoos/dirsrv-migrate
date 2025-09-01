#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/compose/podman-compose.389ds.yml"
COMPOSE_CMD=${COMPOSE_CMD:-"podman compose -f ${COMPOSE_FILE}"}

ANS_INVENTORY="${REPO_ROOT}/test/inventory.compose.pod.yml"
ANS_VARS_MAP="${REPO_ROOT}/test/compose_mapping.yml"
ANS_VARS_TEST="${REPO_ROOT}/test/compose_vars.yml"
PLAYBOOK="${REPO_ROOT}/site.yml"

export ANSIBLE_LOCAL_TEMP="${REPO_ROOT}/.ansible/tmp"
export ANSIBLE_REMOTE_TEMP="${REPO_ROOT}/.ansible/tmp"

mkdir -p "${ANSIBLE_LOCAL_TEMP:-${ANSIBLE_LOCAL_TEMP}}" >/dev/null 2>&1 || true

wait_port() {
  local host="$1" port="$2" timeout="${3:-60}" start
  start=$(date +%s)
  echo "[wait] ${host}:${port} (timeout ${timeout}s)"
  while true; do
    if (echo > "/dev/tcp/${host}/${port}") >/dev/null 2>&1; then
      echo "[wait] ${host}:${port} is up"
      return 0
    fi
    if (( $(date +%s) - start > timeout )); then
      echo "[wait] Timeout waiting for ${host}:${port}" >&2
      return 1
    fi
    sleep 1
  done
}

cmd_up() {
  ${COMPOSE_CMD} up -d
}

cmd_bootstrap() {
  podman exec rhds11 /bin/sh -lc '/usr/local/bin/init-389ds-container.sh || sh /usr/local/bin/init-389ds-container.sh' || true
  podman exec rhds12 /bin/sh -lc '/usr/local/bin/init-389ds-container.sh || sh /usr/local/bin/init-389ds-container.sh' || true
}

cmd_migrate() {
  ansible-galaxy collection install containers.podman >/dev/null 2>&1 || true
  ansible-playbook -i "${ANS_INVENTORY}" \
    -e @"${ANS_VARS_MAP}" \
    -e @"${ANS_VARS_TEST}" \
    ${PLAYBOOK} "$@"
}

cmd_down() {
  ${COMPOSE_CMD} down
}

cmd_reset() {
  ${COMPOSE_CMD} down -v || true
  rm -rf "${REPO_ROOT}/.ansible/artifacts/compose-dev" || true
}

cmd_help() {
  cat <<EOF
Usage: $(basename "$0") <command> [args]

Commands:
  up           Bring up prebuilt 389-DS containers
  bootstrap    Initialize instances, import example LDIF
  migrate      Run Ansible migration via Podman connection (pass extra args)
  down         Stop 389-DS containers
  reset        Stop and remove volumes; clear test artifacts
  help         Show this help

Examples:
  $(basename "$0") up && $(basename "$0") bootstrap
  $(basename "$0") migrate --check --diff
  $(basename "$0") migrate --limit dsm_source
EOF
}

case "${1:-help}" in
  up) shift; cmd_up "$@" ;;
  bootstrap) shift; cmd_bootstrap "$@" ;;
  migrate) shift; cmd_migrate "$@" ;;
  down) shift; cmd_down "$@" ;;
  reset) shift; cmd_reset "$@" ;;
  help|--help|-h) cmd_help ;;
  *) echo "Unknown command: ${1}" >&2; cmd_help; exit 1 ;;
esac
