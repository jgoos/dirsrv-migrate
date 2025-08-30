# RHDS 11 → RHDS 12 Migration: Configuration Guide

This document lists configuration areas to migrate when moving data from RHDS 11 to RHDS 12 using export/import. It reflects 389‑Directory Server/RHDS guidance to avoid copying `dse.ldif` across major versions and to apply configuration via supported tools.

## Approach Overview
- Export data (LDIF) from each backend on RHDS 11.
- Prepare RHDS 12 instance(s) fresh; ensure schema parity.
- Import data into RHDS 12 per backend.
- Recreate configuration via `dsconf` where required (do not copy `dse.ldif`).

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
