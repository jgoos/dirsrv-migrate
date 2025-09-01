#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="${1:-ldap://localhost:1389}"
ROOT_DN="${ROOT_DN:-cn=Directory Manager}"
ROOT_PW="${ROOT_PW:-password}"
LDIF_PATH="${LDIF_PATH:-/root/example.ldif}"

echo "[seed] Adding LDIF ${LDIF_PATH} to ${SERVER_URL}..."
ldapadd -x -H "${SERVER_URL}" -D "${ROOT_DN}" -w "${ROOT_PW}" -f "${LDIF_PATH}"
echo "[seed] Done"

