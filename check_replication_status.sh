#!/bin/bash
# Quick Replication Status Checker

echo "🔍 Replication Status Check"
echo "=========================="

# Check container status
echo "📦 Container Status:"
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(ds-|NAMES)"

echo -e "\n🌐 Network Connectivity:"
for host in ds-s1 ds-s2 ds-c1 ds-c2; do
    echo -n "  $host: "
    if podman exec "$host" ldapsearch -x -H ldap://localhost:3389 -s base -b '' 1.1 >/dev/null 2>&1; then
        echo "✅ LDAP responding"
    else
        echo "❌ LDAP not responding"
    fi
done

echo -e "\n🔄 Replication Agreements:"
for host in ds-s1 ds-s2; do
    echo "  === $host ==="
    podman exec "$host" dsconf -D "cn=Directory Manager" -w "${DIRSRV_PASSWORD:-password}" ldap://localhost:3389 repl-agmt list --suffix dc=example,dc=com 2>/dev/null | grep -E "cn:|nsds5replicaLastUpdateStatusJSON" | head -10 || echo "    No agreements found"
done

echo -e "\n📊 RUV Status:"
for host in ds-s1 ds-s2; do
    echo "  === $host RUV ==="
    podman exec "$host" ldapsearch -x -D "cn=Directory Manager" -w "${DIRSRV_PASSWORD:-password}" -H ldap://localhost:3389 -b "cn=replica,cn=dc\\3Dexample\\2Cdc\\3Dcom,cn=mapping tree,cn=config" nsds50ruv 2>/dev/null | grep "nsds50ruv:" | head -3 || echo "    No RUV found"
done

echo -e "\n✅ Status check complete!"
