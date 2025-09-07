directories.ds API

ds_repl_info (module)
- Purpose: Read replica status and agreements under a suffix.
- Args:
  - instance (str, required): 389-DS instance (e.g., localhost).
  - suffix (str, required): e.g., dc=example,dc=com.
  - use_ldapi (bool, default true): Prefer LDAPI + SASL/EXTERNAL.
  - ldaps_host (str), ldaps_port (int, default 636): Fallback endpoint.
  - bind_method (simple|sslclientauth, default simple), bind_dn, bind_pw (no_log): Remote bind (LDAPS only).
  - tls_ca, tls_client_cert, tls_client_key: TLS trust/identity files.
  - connect_timeout (5), op_timeout (30): Timeouts.
- Returns: changed (false),
  - replica { dn, enabled, ruv },
  - agreements [ { dn, host, port, bind_dn, enabled, last_init_status, last_init_code, last_init_end, last_init_epoch, last_update_status, last_update_code, last_update_end, last_update_epoch } ].
- Failure: Missing replica → failed with hint.

Example:
- name: Read replication state
  directories.ds.ds_repl_info:
    instance: "localhost"
    suffix: "dc=example,dc=com"
  register: info

ds_repl_agreement (module)
- Purpose: Ensure supplier→consumer agreement present/absent and attributes match.
- Args:
  - instance, suffix (required);
  - consumer_host, consumer_port (default 636) (required);
  - transport (LDAPS|StartTLS|LDAP, default LDAPS);
  - bind_method (simple|sslclientauth, default simple), bind_dn, bind_pw (no_log);
  - tls_ca, tls_client_cert, tls_client_key;
  - backoff_min, backoff_max, purge_delay, compression (bool);
  - state (present|absent, default present);
  - use_ldapi, ldaps_host, ldaps_port, connect_timeout, op_timeout.
- Returns: changed, agreement_dn, effective { host, port, bind_method, transport, backoff_min, backoff_max, purge_delay, compression }, warnings.
- Idempotency: create when missing; update on drift; delete on absent.

Example:
- name: Ensure agreement to c1 via LDAPS (SIMPLE)
  directories.ds.ds_repl_agreement:
    instance: "localhost"
    suffix: "dc=example,dc=com"
    consumer_host: "c1.dsnet.test"
    consumer_port: 636
    transport: LDAPS
    bind_method: simple
    bind_dn: "cn=Directory Manager"
    bind_pw: "{{ dirsrv_password }}"
    backoff_min: 3
    backoff_max: 300
    purge_delay: 604800

ds_repl_wait (module)
- Purpose: Poll inside the module until agreement(s) are healthy.
- Args:
  - instance, suffix (required);
  - agreements (list[str]) or all (bool, default false);
  - stale_seconds (default 300), steady_ok_polls (default 3), poll_interval (default 10), timeout (default 900);
  - require_init_success (default true);
  - use_ldapi, ldaps_host, ldaps_port, connect_timeout, op_timeout.
- Returns:
  - Success: changed (false), observations [ { dn, update_code, update_age, init_code, status } ].
  - Failure: failed, reason: timeout, observations, hints.

Example:
- name: Wait until agreements healthy on supplier
  directories.ds.ds_repl_wait:
    instance: "localhost"
    suffix: "dc=example,dc=com"
    all: true
    stale_seconds: 300
    steady_ok_polls: 3
    poll_interval: 10
    timeout: 900

Filter: generalized_time_to_epoch
- Input: LDAP Generalized Time (UTC Z) `YYYYmmddHHMMSSZ` or fractional `YYYYmmddHHMMSS.ffffffZ`.
- Output: int epoch seconds UTC, or null if invalid.

See also
- Design: ../../../docs/DESIGN.md
- Module specs: ../../../docs/MODULE_SPECS.md
