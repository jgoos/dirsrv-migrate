dirsrv_repl — RHDS 12 Replication (389‑DS)

Idempotent Ansible role to configure replication for Red Hat Directory Server 12 / 389‑DS instances across supplier, consumer, and hub topologies. Uses dsconf/dsctl and aligns to RHDS 12 replication docs.


Supported
- Single‑supplier, multi‑supplier, and cascaded (hub) topologies
- Multiple suffixes (default userRoot equivalent)
- SIMPLE or certificate‑based (SSLCLIENTAUTH) agreement auth
- Online init or offline init (ldif2db)
- Fractional replication, schedule, release timeout, changelog purge
- Monitoring via dsconf and optional ds‑replcheck


Quick Start
- Ensure Directory Manager password is in Vault as `dirsrv_password`.
- Define `dirsrv_repl_nodes`, `dirsrv_repl_suffixes`, `dirsrv_repl_replica_ids`, and `dirsrv_repl_agreements` in group_vars.
- Apply on all participating hosts.

Example Inventory (group‑driven)
```
[rhds_suppliers]
ldap1.example.com instance=slapd-prod host=ldap1.example.com port=636 protocol=LDAPS
ldap2.example.com instance=slapd-prod host=ldap2.example.com port=636 protocol=LDAPS

[rhds_consumers]
replica01.example.com instance=slapd-prod host=replica01.example.com port=636 protocol=LDAPS
```

Example Vars (group_vars/all/dirsrv_repl.yml)
```
dirsrv_repl_suffixes:
  - "dc=example,dc=com"

dirsrv_repl_nodes:
  ldap1.example.com: { role: supplier, instance: "slapd-prod", host: "ldap1.example.com", port: 636, protocol: LDAPS }
  ldap2.example.com: { role: supplier, instance: "slapd-prod", host: "ldap2.example.com", port: 636, protocol: LDAPS }
  replica01.example.com: { role: consumer, instance: "slapd-prod", host: "replica01.example.com", port: 636, protocol: LDAPS }

dirsrv_repl_replica_ids:
  "dc=example,dc=com":
    ldap1.example.com: 1
    ldap2.example.com: 2

dirsrv_repl_auth:
  method: SIMPLE
  bind_dn: "cn=replication manager,cn=config"
  bind_password: "{{ vault_repl_bind_password }}"  # from vault

dirsrv_repl_agreements:
  "dc=example,dc=com":
    - { from: "ldap1.example.com", to: "ldap2.example.com", name: "s1-to-s2", init: true }
    - { from: "ldap2.example.com", to: "ldap1.example.com", name: "s2-to-s1", init: false }
    - { from: "ldap1.example.com", to: "replica01.example.com", name: "s1-to-r01", init: true }

dirsrv_repl_frac_list: [authorityRevocationList, accountUnlockTime, memberof]
dirsrv_repl_frac_list_total: [accountUnlockTime]
dirsrv_repl_strip_list: [modifiersname, modifytimestamp, internalmodifiersname]

dirsrv_repl_release_timeout: 90
dirsrv_repl_changelog:
  purge_enabled: true
  max_age: "1d"
  encrypt: false
```

Playbook Snippet
```
- hosts: all
  become: true
  roles:
    - role: dirsrv_repl
```


Behavior & Safety
- Unique replica IDs: `dirsrv_repl_require_unique_replica_ids` enforces uniqueness per suffix.
- Guard bidirectional init: `dirsrv_repl_guard_bidirectional_init` aims to prevent A↔B both with `init: true`.
- Schedules: If `dirsrv_repl_schedule` set and any agreement uses `init: true`, a warning is emitted (schedule might pause init).
- Offline init: Only runs on consumers; stops `dirsrv@<instance>`, runs `dsctl <inst> ldif2db`, and restarts.
- Changelog encryption: Surfaced as a guarded, manual step (requires stop→enable→verify→start per site policy).


Auth Modes
- SIMPLE: agreements pass `--bind-dn`/`--bind-passwd` and `--bind-method SIMPLE`.
- SSLCLIENTAUTH: agreements use `--bind-method SSLCLIENTAUTH`; ensure user entries have certs and mTLS is configured.


Monitoring
- `dsconf replication monitor` snapshot is printed.
- For each local agreement, `repl-agmt status` is run.
- Optional `ds-replcheck` supports `state|online|offline` modes and prints results.


Notes & Remedies
- Generation ID mismatch / stuck agreements: consider reinit from a known‑good supplier.
- Time skew: ensure chronyd/ntpd/timesyncd is active; replication CSNs depend on time.
- Changelog too big: tune `dirsrv_repl_changelog.max_age` and ensure purge is enabled.
- Locked replica / monopolization: adjust `dirsrv_repl_release_timeout`.


Variables
See `defaults/main.yml` and `meta/arg_specs.yml` for all variables and types.

