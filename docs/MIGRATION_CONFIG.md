# RHDS 11 → RHDS 12 Migration: Configuration Guide

This document lists configuration areas to migrate when moving data from RHDS 11 to RHDS 12 using export/import. It reflects 389‑Directory Server/RHDS guidance to avoid copying `dse.ldif` across major versions and to apply configuration via supported tools.

## Approach Overview
- Export data (LDIF) from each backend on RHDS 11 using vendor-supported tools.
- Prepare RHDS 12 instance(s) fresh; ensure schema parity.
- Import data into RHDS 12 per backend.
- Recreate configuration via `dsconf` where required (do not copy `dse.ldif`).

## Mapping 35 Pairs and Avoiding Overwrites

- Define all 35 source→target pairs in `group_vars/all/dirsrv_mapping.yml` under `dirsrv_host_map`.
- The playbook validates a strict 1:1 mapping and that every mapped host exists in the appropriate group (`dsm_source` or `dsm_target`).
- Artifacts are staged on the controller under `{{ dirsrv_artifact_root_effective }}/<source-host>/` and targets pull from their mapped source.
- To avoid overwriting artifacts across distinct migration runs, set an optional run label:
  - `-e dirsrv_artifact_run=2024-09-01A` (or any descriptive label)
  - This creates `{{ dirsrv_artifact_root }}/2024-09-01A/<source-host>/...`
  - Leaving it empty keeps paths stable for idempotent reruns.

Example invocation with vault and run label:

```
ansible-playbook -i inventory.yml site.yml \
  --ask-vault-pass \
  -e dirsrv_artifact_run=2024-09-01A
```

## What To Migrate
- Schema (server‑side):
  - Copy custom schema LDIF files from `/etc/dirsrv/slapd-<instance>/schema/` on the source to the same location on the target before import.
  - Keep vendor/stock schema from the RHDS 12 package; only add your custom files.

- Indices:
  - Ensure required attribute indexes exist after import. Create or adjust using `dsconf` (per backend).
  - Example: `dsconf <inst> backend index create --attr mail --type eq` then `dsconf <inst> backend reindex userroot`.

- Access Control (ACIs):
  - ACIs stored in entries under your suffix migrate with the LDIF.
  - ACIs under `cn=config` or global access settings must be reapplied via `dsconf`.

- Plugins and Operational Features:
  - MemberOf, Referential Integrity, USN, DNA, and similar plugins should be enabled/configured via `dsconf` on RHDS 12. Do not copy plugin entries from the old `dse.ldif`.
  - Reindex or run plugin fix‑up tasks if required (e.g., memberOf fixup after import if not automatically updated).

- Password Policies and Storage Schemes:
  - If fine‑grained policies live under your suffix, they migrate with data.
  - Default/global policy and password storage schemes must be set via `dsconf` on the target.

- TLS and Certificates:
  - Install server certificates/keys on RHDS 12 and configure TLS via `dsconf` (secure port, NSS DB, trust).
  - Do not copy legacy `nsslapd-*` security blocks from source `dse.ldif`.

- Replication:
  - Recreate replication topology on RHDS 12 using `dsconf` after imports. Do not copy replica/agreements from old config.
  - Initialize agreements explicitly once peers are in place.

- Logging and Rotation:
  - If you rely on non‑default log paths, rotation, or levels, reapply via `dsconf`.

## Access Control (ACIs)

ACIs that live in entries under your data suffix migrate automatically with LDIF export/import. ACIs under `cn=config` are configuration and must be reapplied on RHDS 12. Do not copy `dse.ldif` between versions.

- Entry ACIs in data (automatic):
  - Stored as the `aci` attribute on entries under your suffix (for example `o=example`).
  - Included by backend export (`db2ldif`) and re‑created on import. No extra steps.

- Global/config ACIs (manual):
  - Defined on `cn=config` or other config entries; not part of backend LDIF exports.
  - Reapply via `ldapmodify` or `dsconf` after the new instance is created.

Export global/config ACIs from source:

```
ldapsearch -H ldap://source-host:389 \
  -D "cn=Directory Manager" -W \
  -b "cn=config" -s sub "(aci=*)" aci
```

Import global/config ACIs to target (Option A: ldapmodify LDIF):

```
dn: cn=config
changetype: modify
add: aci
aci: (version 3.0; acl "Allow RO to app X";
  allow (read, search, compare)
  (userdn = "ldap:///uid=app-x,ou=svc,dc=example,dc=com"); )
```

Apply with:

```
ldapmodify -H ldap://target-host:389 \
  -D "cn=Directory Manager" -W -x -f add-global-aci.ldif
```

Import global/config ACIs to target (Option B: dsconf):

```
dsconf <instance> aci add --entry 'cn=config' --aci \
  '(version 3.0; acl "Allow RO to app X"; allow (read, search, compare)
    (userdn = "ldap:///uid=app-x,ou=svc,dc=example,dc=com"); )'

# List and verify
dsconf <instance> aci list --entry 'cn=config'
```

Checklist for ACIs:
- Confirm entry ACIs exist under the imported suffix (spot‑check a few representative entries).
- Export and reapply only the needed global ACIs from `cn=config` (avoid blanket copies).
- Review DN subjects in ACIs (userdn/groupdn/roledn) and adjust for new suffix/DN layout.
- Verify effective access using test binds for representative roles/service accounts.

## What NOT To Migrate
- Do not copy `dse.ldif` between major versions (contains version‑specific config and runtime state).
- Do not copy the changelog database or replication agreements.
- Avoid copying package‑managed schema files; use RHDS 12’s stock versions.

## Minimal Checklist (per target)
- Schema parity: custom schema files present under `/etc/dirsrv/slapd-<instance>/schema/`.
- Backends: definitions created; indexes present (create/reindex as needed).
- Plugins: memberOf, referential integrity, etc., enabled and configured.
- Security: TLS configured; certificates installed and trusted.
- Policies: default/global password policy and storage schemes set.
- Replication: agreements created and initialized (if applicable).

## Export/Import Commands (Vendor Guidance)

- Export (online, recommended):
  - `dsconf <inst> backend export --suffix <suffix> -l <file.ldif>`
- Export (offline):
  - `dsctl <inst> db2ldif <suffix> <file.ldif>` and stop/start instance around export.
- Import (online):
  - `dsconf <inst> backend import --suffix <suffix> <file.ldif>`

Notes:
- Prefer the explicit `--suffix` flag with `dsconf` to target the root suffix. Some versions accept the suffix positionally, but using `--suffix` is clearer and avoids ambiguity.
- This role uses suffix‑based export/import so backend name changes do not affect the migration. It ensures a backend exists for each configured suffix on both source and target.
- For constrained test containers, you can set `dirsrv_export_method: ldapsearch` to simulate export without relying on systemd.

## Notes on Scale (35 servers)
- Concurrency-safe on controller: per-source artifact directories prevent collisions between hosts.
- Use `--limit` to scope subsets during staged rollouts (e.g., `--limit dsm_source[0:9]` then `dsm_target[0:9]`).
- Set `dirsrv_artifact_run` for each batch if you want distinct artifact snapshots retained.

## Local Testing with Podman

The repo includes Podman Compose setups to spin up a source and target 389-DS and exercise the migration end-to-end.

Local test — 389-DS prebuilt image (no SSH):
- `compose/podman-compose.389ds.yml`: `ds-s1` (supplier) and `ds-c1` (consumer) using `quay.io/389ds/dirsrv`.
- `test/inventory.compose.pod.yml`: uses the Podman connection plugin.
- `test/compose_mapping.yml`: source→target map (`ds-s1` → `ds-c1`).
- `test/compose_vars.yml`: test vars including `dirsrv_password`.

Usage:
Run (prebuilt 389-DS + Podman connection):
  podman-compose -f compose/podman-compose.389ds.yml up -d
  make seed_389ds   # import example LDIF into source container
  ansible-galaxy collection install containers.podman
  make migrate_pod

Re-run safely: artifacts land under `.ansible/artifacts/compose-dev/ds-s1/…`. You can change `dirsrv_artifact_run` in `test/compose_vars.yml` to keep multiple snapshots.

## Runtime Variables (Tuning)

These variables can be overridden in `group_vars`, inventory, or at runtime with `-e`:

- `dirsrv_ldap_tcp_uri`: TCP LDAP URI used by ldapsearch fallback or external tools. Default: `ldap://localhost:389`.
- `dirsrv_ldapi_socket_path`: Local LDAPI socket path for the instance. Default: `/var/run/dirsrv/slapd-<instance>.socket`.
- `dirsrv_ldapi_uri`: Computed LDAPI URI based on `dirsrv_ldapi_socket_path`. Default: `ldapi://%2Fvar%2Frun%2Fdirsrv%2Fslapd-<instance>.socket`.
- `dirsrv_dsconf_timeout`: Seconds for `dsconf` export/import operations when supported (applies `--timeout <seconds>`). Default: `600`.
- `dirsrv_collect_config`: Whether to collect and transfer server config archive (used for schema extraction). Default: `true`. In container tests: `false`.
- `dirsrv_manage_source_backends`: Test-only; allow creating the source backend/suffix if missing. Default: `false` (prod safe). In container tests: `true`.

Notes:
- The role auto-detects `dsconf` path and capabilities (e.g., `--suffix`, `--timeout`) per host; when supported, timeout is applied automatically.
- In production, `dirsrv_manage_source_backends` should remain `false` so the source is not mutated by the role.

## Commands Reference (illustrative)
- Index management:
  - List: `dsconf <inst> backend index list <be-name>`
  - Create: `dsconf <inst> backend index create --attr uid --type eq` (repeat for needed types)
  - Reindex: `dsconf <inst> backend reindex <be-name>`

- MemberOf plugin:
  - Enable: `dsconf <inst> plugin memberof enable`
  - Fixup: `dsconf <inst> plugin memberof fixup <suffix>`

- Referential Integrity plugin:
  - Enable: `dsconf <inst> plugin referential-integrity enable`

- TLS basics:
  - Enable secure port: `dsconf <inst> security set --startTLS on --securePort 636`
  - Manage certs/keys using `dsconf <inst> tls` or documented NSS tools.

- Replication (high‑level):
  - Create changelog: `dsconf <inst> replication set-changelog --suffix <suffix> --create`
  - Create agreement(s): `dsconf <inst> repl-agmt create ...` and initialize per peer.

## Notes & Rationale
- 389‑DS/RHDS recommends export/import or replication for migrations; avoid transplanting `dse.ldif`. Reapply server config with `dsconf` to match new defaults and schema of RHDS 12.
- ACIs embedded in data entries migrate with LDIF. Server‑global settings must be configured on the new instance.

## Sources (to verify and read further)
- Red Hat Directory Server 12 documentation: https://access.redhat.com/documentation/en-us/red_hat_directory_server/12/
- 389 Directory Server documentation: https://directory.fedoraproject.org/docs/389ds/
