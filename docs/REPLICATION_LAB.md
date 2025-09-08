Replication Lab (Podman)

This lab spins up prebuilt 389‑DS containers to exercise the replication role locally, without SSH.

Containers
- ds-s1: supplier 1 (seeds example LDIF)
- ds-c1: consumer 1
- ds-s2: supplier 2 (mesh test)
- ds-c2: consumer 2 (mesh test)

Bring up and seed
```
make up_389ds
make init_389ds
make seed_389ds
```

Single supplier → consumer
```
make test_repl
```

Mesh (2 suppliers + 2 consumers)
```
make test_repl_mesh
```

Troubleshooting
- macOS Podman warnings like "proxy already running": re‑run targets — the Makefile force‑removes stale containers and avoids host ports.
- Suffixes must exist before enabling replication. The replication role asserts presence and will fail fast if a suffix is missing; create it during migration/seed steps.
