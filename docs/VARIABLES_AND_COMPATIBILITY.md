# Variable Names and Compatibility

After renaming the role to `dirsrv_migrate`, variables now use the `dirsrv_` prefix as the primary interface. Existing inventories should migrate to `dirsrv_*`. The role does not expose `dsm_*` variables anymore; if you still have `dsm_*` in your inventories, update them to `dirsrv_*`.

Planned path (non‑breaking first, then major change):
- Current: prefer `dirsrv_*` in all new code and examples.
- Next major: optionally expose `dirsrv_migrate_*` as a role‑scoped alternative (still mapping to `dirsrv_*`).

URI naming: `dirsrv_dsconf_uri` is deprecated and not used by the role. Prefer `dirsrv_ldap_tcp_uri` for TCP connections and `dirsrv_ldapi_uri` for LDAPI. The defaults still define `dirsrv_dsconf_uri` for parity and mark it clearly as deprecated.

Notes for tests: `dirsrv_manage_source_backends` is a test‑only toggle kept in defaults for clarity; set it only in test var files. The `dirsrv_dse_ldif` default is intentionally relative to support archive include paths.

## Replication Role Variables

The replication role (`roles/dirsrv_repl`) uses `dirsrv_repl_*` variables exclusively.

- Topology and nodes:
  - `dirsrv_repl_suffixes`: list of suffix DNs (e.g., `o=example`).
  - `dirsrv_repl_nodes`: map of `inventory_hostname` to node details (role/instance/host/port/protocol).
  - `dirsrv_repl_replica_ids`: per suffix, replica IDs keyed by `inventory_hostname` for suppliers/hubs.
  - `dirsrv_repl_agreements`: per suffix, list of `{from,to,name,init}` agreements.

- Auth and admin:
  - `dirsrv_repl_auth`: SIMPLE or SSLCLIENTAUTH for agreements.
  - `dirsrv_dm_dn` and `dirsrv_password`: admin bind for dsconf/dsctl; store password in Vault.

- Tuning and monitoring:
  - `dirsrv_repl_schedule`, `dirsrv_repl_frac_list(_total)`, `dirsrv_repl_strip_list`.
  - `dirsrv_repl_set_release_timeout`, `dirsrv_repl_release_timeout`.
  - `dirsrv_repl_run_replcheck`, `dirsrv_replcheck_mode`.

Deprecated URIs: `dirsrv_dsconf_uri` remains deprecated. Prefer `dirsrv_ldapi_uri` for local admin operations (used in tests). For TCP operations, use `dirsrv_ldap_tcp_uri`.
