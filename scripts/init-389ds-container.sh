#!/usr/bin/env bash
set -euo pipefail

INSTANCE_NAME=${INSTANCE_NAME:-localhost}
ROOT_DN=${ROOT_DN:-cn=Directory Manager}
ROOT_PW=${ROOT_PW:-password}
SUFFIX=${SUFFIX:-o=example}
PORT=${PORT:-389}

echo "[init] Creating instance '${INSTANCE_NAME}' on port ${PORT}..."
cat > /root/instance.inf <<EOF
[general]
config_version = 2
full_machine_name = localhost.localdomain
start = False

[slapd]
instance_name = ${INSTANCE_NAME}
root_dn = ${ROOT_DN}
root_password = ${ROOT_PW}
suffix = ${SUFFIX}
port = ${PORT}
secure_port = 0
EOF

if ! dsctl ${INSTANCE_NAME} status >/dev/null 2>&1; then
  dscreate from-file /root/instance.inf
fi

echo "[init] Starting ns-slapd as dirsrv user..."
if command -v runuser >/dev/null 2>&1; then
  runuser -u dirsrv -- ns-slapd -D "/etc/dirsrv/slapd-${INSTANCE_NAME}" -d 0 &
else
  su -s /bin/sh -c "ns-slapd -D /etc/dirsrv/slapd-${INSTANCE_NAME} -d 0 &" dirsrv
fi

# wait for LDAP port
for i in $(seq 1 30); do
  ldapsearch -x -H ldap://localhost:${PORT} -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break
  sleep 1
done

echo "[init] Ensure backend exists..."
if ! dsconf ${INSTANCE_NAME} backend suffix list 2>/dev/null | grep -q "^${SUFFIX}$"; then
  dsconf ${INSTANCE_NAME} backend create --suffix "${SUFFIX}" --be-name userRoot || true
fi

echo "[init] Importing example data (if present)..."
if [[ -f /root/example.ldif ]]; then
  ldapadd -x -H ldap://localhost:${PORT} -D "${ROOT_DN}" -w "${ROOT_PW}" -f /root/example.ldif || true
fi

echo "[init] Done."
