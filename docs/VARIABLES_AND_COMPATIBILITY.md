# Variable Names and Compatibility

After renaming the role to `dirsrv_migrate`, variables now use the `dirsrv_` prefix as the primary interface. Existing inventories should migrate to `dirsrv_*`. The role does not expose `dsm_*` variables anymore; if you still have `dsm_*` in your inventories, update them to `dirsrv_*`.

Planned path (non‑breaking first, then major change):
- Current: prefer `dirsrv_*` in all new code and examples.
- Next major: optionally expose `dirsrv_migrate_*` as a role‑scoped alternative (still mapping to `dirsrv_*`).

URI naming: `dirsrv_dsconf_uri` is deprecated and not used by the role. Prefer `dirsrv_ldap_tcp_uri` for TCP connections and `dirsrv_ldapi_uri` for LDAPI. The defaults still define `dirsrv_dsconf_uri` for parity and mark it clearly as deprecated.

Notes for tests: `dirsrv_manage_source_backends` is a test‑only toggle kept in defaults for clarity; set it only in test var files. The `dirsrv_dse_ldif` default is intentionally relative to support archive include paths.
