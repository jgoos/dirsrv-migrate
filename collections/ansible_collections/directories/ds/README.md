directories.ds — 389-DS replication helper collection

Overview
- Purpose: lightweight modules and helpers to create/read/wait replication agreements on 389-DS/RHDS.
- Transport: LDAPI first (SASL/EXTERNAL); LDAPS fallback (SIMPLE or client-cert).
- Scope: agreement CRUD, health polling, facts export. Topology design is out of scope.

Modules
- `directories.ds.ds_repl_info`: Read replica/agreements status under a suffix.
- `directories.ds.ds_repl_agreement`: Ensure a supplier→consumer agreement is present/absent.
- `directories.ds.ds_repl_wait`: Poll until agreements become healthy.

Filter
- `generalized_time_to_epoch`: LDAP Generalized Time (UTC Z) to epoch seconds (fractional seconds truncated).

Shared Utils
- `module_utils.dsldap`: Minimal LDAP client surface; LDAPI-first, LDAPS fallback; retries + timeouts.

Quickstart
1) Build and install the collection locally (preferred):
   - `make collection_build`
   - `make collection_install_dev`
2) Verify discovery:
   - `ansible-doc -t module directories.ds.ds_repl_info`

Examples (lab topology)
- Ensure agreements from local supplier (instance `localhost`) to a consumer using LDAPS SIMPLE:

  - name: Ensure agreement to consumer c1
    directories.ds.ds_repl_agreement:
      instance: "localhost"
      suffix: "dc=example,dc=com"
      consumer_host: "c1.dsnet.test"
      consumer_port: 636
      transport: LDAPS
      bind_method: simple
      bind_dn: "cn=Directory Manager"
      bind_pw: "{{ dirsrv_password }}"   # from Vault

- Wait for health of all agreements on this supplier (staleness gating):

  - name: Wait until agreements are healthy
    directories.ds.ds_repl_wait:
      instance: "localhost"
      suffix: "dc=example,dc=com"
      all: true
      stale_seconds: 300
      steady_ok_polls: 3
      poll_interval: 10
      timeout: 900

- Gather facts for dashboards:

  - name: Collect replication info
    directories.ds.ds_repl_info:
      instance: "localhost"
      suffix: "dc=example,dc=com"
    register: info
  - copy:
      dest: ".ansible/artifacts/{{ inventory_hostname }}-repl.json"
      content: "{{ info | to_nice_json }}"

Security Notes
- Prefer LDAPI (SASL/EXTERNAL) where possible; no secrets needed and no network exposure.
- When LDAPS SIMPLE is used, supply `bind_dn` and `bind_pw` from Ansible Vault. All password params are `no_log: true`.
- For client-auth (mTLS), set `tls_client_cert`/`tls_client_key` and optionally `tls_ca`.

Health Semantics (ds_repl_wait)
- Replica enabled (`nsds5ReplicaEnabled` on supplier replica).
- Last update status code equals 0.
- Last update end time not stale (> `stale_seconds` is considered unhealthy).
- If `require_init_success` is true (default), last init status code equals 0 when present.

Cross-links
- Repo design: docs/DESIGN.md
- Module specs: docs/MODULE_SPECS.md

