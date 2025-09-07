# SPECS: 389-DS / RHDS Replication Automation Modules

**Audience:** AI developer implementing Ansible modules & helper plugins
**Scope:** Create, inspect, and wait-for-health for replication agreements at scale (\~30 masters).
**Targets:** RHDS 11/12 and upstream 389-DS 1.4+ (systemd-managed instances, optional containers).
**Non-Goals:** Continuous monitoring/alerting (export results instead), topology design logic.

---

## 0) Architecture Overview

We will ship a **small Ansible collection** e.g. `directories.ds` with:

1. **Module** `ds_repl_agreement` – idempotently ensure a replication agreement (supplier→consumer) exists and is configured as desired.
2. **Module** `ds_repl_info` – read agreements & replica health/status from LDAP and return machine-parseable facts.
3. **Module** `ds_repl_wait` – poll (inside the module) until specified agreement(s) are healthy, with tunable timeouts and staleness windows.
4. **Filter plugin** `generalized_time_to_epoch` – convert LDAP Generalized Time to epoch (UTC).
5. **Shared lib** `module_utils/dsldap.py` – minimal LDAP client with ldapi (SASL/EXTERNAL) first, LDAPS fallback, robust timeouts/retries.

**Execution model:**

* Modules run **on the supplier host** (via `delegate_to: <supplier>` or running the play on that host) using `ldapi://` + SASL/EXTERNAL (root or dirsrv user).
* For remote reads (rare), support LDAPS with SIMPLE or SSLCLIENTAUTH (mTLS).
* No parsing of `dsconf` output; use LDAP entries/attributes directly.

---

## 1) Data Model & LDAP Paths

* **Replica (per suffix)**:
  DN: `cn=replica,cn=<SUFFIX DN>,cn=mapping tree,cn=config`
  Key attrs:

  * `nsds50ruv` (text RUV)
  * `nsds5ReplicaEnabled` (`on|off`)

* **Replication Agreement objects** (children under the replica entry):
  `objectClass=nsDS5ReplicationAgreement`
  Typical attrs we consume/set:

  * Identity/endpoint: `nsds5ReplicaHost`, `nsds5ReplicaPort`, `nsds5ReplicaBindDN`, `nsds5ReplicaTransportInfo` (`SSL`, `TLS`, `LDAP`)
  * Status (read-only):

    * `nsds5replicaLastInitStatus` (string, leading integer code)
    * `nsds5replicaLastInitEnd` (Generalized Time)
    * `nsds5replicaLastUpdateStatus` (string, leading integer code)
    * `nsds5replicaLastUpdateEnd` (Generalized Time)
  * Tunables (where supported):

    * `nsds5ReplicaBackoffMin`, `nsds5ReplicaBackoffMax` (seconds)
    * `nsds5ReplicaPurgeDelay` (seconds)
    * Compression flags (if available on target version)

**Health semantics (what `ds_repl_wait` enforces):**

* Agreement **enabled** (`nsds5ReplicaEnabled` on the supplier replica).
* `LastUpdateStatus` code == **0**.
* `LastUpdateEnd` **not stale** (≤ `stale_seconds` ago).
* If `require_init_success`: `LastInitStatus` code == **0**.
* Optional steady-state: RUV unchanged for `steady_ok_polls` polls or matches reference (future).

---

## 2) Collection Layout

```
collections/
└── directories/ds/
    ├── plugins/
    │   ├── modules/
    │   │   ├── ds_repl_agreement.py
    │   │   ├── ds_repl_info.py
    │   │   └── ds_repl_wait.py
    │   ├── filter/
    │   │   └── generalized_time_to_epoch.py
    │   └── module_utils/
    │       └── dsldap.py
    ├── README.md
    ├── docs/
    │   ├── REPLICATION_DESIGN.md
    │   └── API.md
    └── molecule/
        └── 4node/
            ...
```

---

## 3) Shared LDAP Helper (`module_utils/dsldap.py`)

**Responsibilities:**

* Build URLs for `ldapi://%2Frun%2F{instance}.socket/`
* SASL/EXTERNAL bind over ldapi (default)
* LDAPS bind (SIMPLE or mTLS) fallback
* `search_one(base, scope, filter, attrs)` with timeouts
* `modify(dn, changes)` / `add(dn, attrs)` / `delete(dn)`
* Small retry wrapper for transient network errors (3 attempts, jittered backoff)

**Config & Timeouts (defaults, overridable per call):**

```python
CONNECT_TIMEOUT = 5     # seconds
OP_TIMEOUT      = 30
RETRIES         = 3
BACKOFF_BASE    = 0.5   # seconds
```

**Return conventions:** raise `DsLdapError` with `.code` and `.hint` for module to map to `failed=True` and useful messages.

**Implementation:** Prefer `python-ldap`. If unavailable in environment, we can shell out to `ldapsearch/add/modify` as a fallback (but aim for python-ldap).

---

## 4) Filter Plugin: `generalized_time_to_epoch`

**Signature:**
`generalized_time_to_epoch(value: str) -> int | None`

* Accept `YYYYmmddHHMMSSZ` (strict) and optionally fractional seconds (`YYYYmmddHHMMSS.fffffZ`) – truncate fraction.
* Return **int epoch** UTC, or `None` if unparsable.

**Test vectors:**

* `20250101123045Z` → `1735734645`
* `20240229120000Z` (leap day)
* Invalid: `20250101123045+0100` → `None`

---

## 5) Module: `ds_repl_info`

**Purpose:** Read agreements & replica status under a suffix; return structured data.

**Args:**

```yaml
instance:         {type: str, required: true}     # e.g. slapd-example
suffix:           {type: str, required: true}     # e.g. dc=example,dc=com
use_ldapi:        {type: bool, default: true}
ldaps_host:       {type: str, required: false}    # fallback endpoint
ldaps_port:       {type: int, default: 636}
bind_method:      {type: str, choices: [simple, sslclientauth], default: simple}
bind_dn:          {type: str, required: false}
bind_pw:          {type: str, required: false, no_log: true}
tls_ca:           {type: path, required: false}
tls_client_cert:  {type: path, required: false}
tls_client_key:   {type: path, required: false}
connect_timeout:  {type: int, default: 5}
op_timeout:       {type: int, default: 30}
```

**Behavior:**

* Resolve `REPL_BASE = "cn=replica,cn={suffix},cn=mapping tree,cn=config"`.
* Ensure replica exists; fetch `nsds5ReplicaEnabled`, `nsds50ruv`.
* Search child agreements `(objectClass=nsDS5ReplicationAgreement)`.
* For each, read:

  * `dn`, `nsds5ReplicaHost`, `nsds5ReplicaPort`, `nsds5ReplicaBindDN`
  * `nsds5replicaLastInitStatus`, `nsds5replicaLastInitEnd`
  * `nsds5replicaLastUpdateStatus`, `nsds5replicaLastUpdateEnd`
* Parse leading integer codes from both status strings (regex `^(-?\d+)`)
* Convert times to epoch with the filter.

**Return (`ansible_facts`-style structure):**

```json
{
  "changed": false,
  "replica": {
    "dn": "cn=replica,...",
    "enabled": true,
    "ruv": "..."
  },
  "agreements": [
    {
      "dn": "cn=agmt to x,...",
      "host": "x.example.com",
      "port": 636,
      "bind_dn": "uid=repl,cn=replication,cn=config",
      "enabled": true,                 // derived from replica.enabled
      "last_init_status": "0 Total init succeeded",
      "last_init_code": 0,
      "last_init_end": "20250907091531Z",
      "last_init_epoch": 1757246131,
      "last_update_status": "0 Update OK",
      "last_update_code": 0,
      "last_update_end": "20250907091740Z",
      "last_update_epoch": 1757246260
    }
  ]
}
```

**Failure modes:**

* Replica not found → `failed: true, msg: "Replica entry missing for suffix X"`
* LDAP bind/search errors → map `DsLdapError` to `failed` with `hint`.

**Idempotency:** Always `changed: false`.

---

## 6) Module: `ds_repl_agreement`

**Purpose:** Ensure an agreement from this **supplier** to a **consumer** exists & matches desired settings.

**Args (subset):**

```yaml
instance:         {type: str, required: true}
suffix:           {type: str, required: true}
consumer_host:    {type: str, required: true}
consumer_port:    {type: int,  default: 636}
bind_method:      {type: str,  choices: [simple, sslclientauth], default: simple}
bind_dn:          {type: str,  required: false}   # req. if simple
bind_pw:          {type: str,  required: false, no_log: true}
transport:        {type: str,  choices: [LDAPS, StartTLS, LDAP], default: LDAPS}
tls_ca:           {type: path, required: false}
tls_client_cert:  {type: path, required: false}   # req. if sslclientauth
tls_client_key:   {type: path, required: false}
backoff_min:      {type: int,  required: false}
backoff_max:      {type: int,  required: false}
purge_delay:      {type: int,  required: false}
compression:      {type: bool, default: false}
state:            {type: str,  choices: [present, absent], default: present}

use_ldapi / ldaps_* / timeouts… same as ds_repl_info
```

**DN Convention**

* If an existing agreement with matching `nsds5ReplicaHost/Port` exists → manage that DN.
* Else create a new child under the replica with `cn="agmt to {consumer_host}:{consumer_port}"` (safe, readable).

**Create/Update logic**

* Ensure replica entry exists; abort if not.
* **Present:**

  * Existing? Compare target attributes; build modify list; apply if drift.
  * Missing? Build full attribute set and `add`.
* **Absent:**

  * If present, `delete`.
  * If missing, `changed: false`.

**Attributes we set (where supported):**

* `nsds5ReplicaHost` = consumer\_host
* `nsds5ReplicaPort` = consumer\_port
* `nsds5ReplicaBindDN` (if simple)
* Transport:

  * `nsds5ReplicaTransportInfo` = `SSL` for LDAPS, `TLS` for StartTLS, `LDAP` otherwise
* Tunables when provided:

  * `nsds5ReplicaBackoffMin`, `nsds5ReplicaBackoffMax`, `nsds5ReplicaPurgeDelay`
* Compression flag(s) if available in the target version (detect & set; otherwise warn once).

**Return:**

```json
{
  "changed": true,
  "agreement_dn": "cn=agmt to c1.example.com:636,cn=replica,cn=...",
  "effective": {
    "host": "c1.example.com",
    "port": 636,
    "bind_method": "sslclientauth",
    "transport": "LDAPS",
    "backoff_min": 3,
    "backoff_max": 300,
    "purge_delay": 604800,
    "compression": false
  }
}
```

**Safety & Idempotency**

* No restarts; live changes only.
* Do not touch unrelated agreements.
* Never store secrets on disk; rely on Ansible vars / vault.
* Validate mutually exclusive args (e.g., `sslclientauth` requires client cert/key; `simple` requires `bind_dn`+`bind_pw`).

**Errors with pushback hints**

* Missing replica → “Enable replication on suffix before creating agreements.”
* Bind method/transport mismatch → clear message.
* Unsupported attribute (older RHDS) → “Attribute X unsupported; skipped setting; continue? (we log a warning in `warnings`)”

---

## 7) Module: `ds_repl_wait`

**Purpose:** Poll inside the module until specified agreement(s) are **healthy**.

**Args:**

```yaml
instance:             {type: str, required: true}
suffix:               {type: str, required: true}
agreements:           {type: list[str], required: false} # explicit DNs
all:                  {type: bool, default: false}       # wait on all under replica if true and agreements not set
stale_seconds:        {type: int,  default: 300}
steady_ok_polls:      {type: int,  default: 3}
poll_interval:        {type: int,  default: 10}
timeout:              {type: int,  default: 900}
require_init_success: {type: bool, default: true}

# Same connection & TLS args as ds_repl_info
```

**Algorithm (pseudocode):**

```
deadline = now + timeout
ok_streak = 0
target_dns = resolve_agreement_dns()

while now < deadline:
    states = read_all(target_dns)
    unhealthy = []
    for s in states:
        if not replica.enabled: unhealthy.append("replica disabled")
        if s.update_code != 0: unhealthy.append("update_code!=0")
        if require_init_success and s.init_code not in (None,0): unhealthy.append("init_code!=0")
        if now - s.update_epoch > stale_seconds: unhealthy.append("stale")

    if unhealthy is empty:
        ok_streak += 1
        if ok_streak >= steady_ok_polls:
            return success with detailed states
    else:
        ok_streak = 0

    sleep(poll_interval)

return failure with last observed states + reasons + suggestions
```

**Return (success):**

```json
{
  "changed": false,
  "waited_seconds": 130,
  "agreements": [
    {
      "dn": "...",
      "update_code": 0,
      "update_age": 12,
      "init_code": 0,
      "status": "healthy"
    }
  ]
}
```

**Return (failure):**

* `failed: true`
* `reason: "timeout"`
* `observations`: per-agreement snapshot (codes, ages)
* `hints`: array of human-helpful strings (e.g., “Update stale >300s; check network to consumer x:636”, “init\_code=49 (auth) – verify bind DN/credentials or mTLS trust”)

**Performance:**

* One LDAP roundtrip per poll; use `serial` in playbooks to cap concurrency (doc this in README).
* No controller-side loops; the module owns the loop.

---

## 8) Examples (Playbook Snippets)

**Create agreements from supplier to listed consumers**

```yaml
- hosts: s1
  gather_facts: false
  vars:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
  tasks:
    - name: Ensure agreements
      directories.ds.ds_repl_agreement:
        instance: "{{ instance }}"
        suffix: "{{ suffix }}"
        consumer_host: "{{ item.host }}"
        consumer_port: "{{ item.port | default(636) }}"
        bind_method: "sslclientauth"
        transport: "LDAPS"
        tls_ca: "/etc/dirsrv/certs/ca.pem"
        tls_client_cert: "/etc/dirsrv/certs/repl-client.crt"
        tls_client_key: "/etc/dirsrv/certs/repl-client.key"
        backoff_min: 3
        backoff_max: 300
        purge_delay: 604800
        state: present
      loop: "{{ hostvars[inventory_hostname].repl_edges }}"
```

**Wait for health (all agreements on this supplier)**

```yaml
- name: Wait until agreements are healthy
  directories.ds.ds_repl_wait:
    instance: "{{ instance }}"
    suffix: "{{ suffix }}"
    all: true
    stale_seconds: 300
    steady_ok_polls: 3
    poll_interval: 10
    timeout: 900
```

**Gather facts for dashboards / Splunk**

```yaml
- name: Collect replication info
  directories.ds.ds_repl_info:
    instance: "{{ instance }}"
    suffix: "{{ suffix }}"
  register: info

- copy:
    dest: ".ansible/artifacts/{{ inventory_hostname }}-repl.json"
    content: "{{ info | to_nice_json }}"
```

---

## 9) Validation & Edge Cases

* **Replica entry missing** → All modules must fail fast with a clear hint:
  “Suffix replication not enabled: cn=replica,cn={{suffix}},cn=mapping tree,cn=config not found.”
* **Multiple agreements to same host\:port** → manage the first exact match; warn that multiple exist; include DNs in `warnings`.
* **Generalized Time missing or unparsable** → treat as stale; include `observed_value` in observations.
* **Clock skew** → mention in `hints` if negative ages are computed.
* **Access control** → if SASL/EXTERNAL fails, suggest running as root/dirsrv or using LDAPS + SIMPLE/mTLS.
* **Version differences** → if a requested attribute isn’t present in schema, skip setting, append to `warnings`.

---

## 10) Testing (Molecule Scenario `4node`)

**Topology:** 4 masters (s1…s4).
**Sequence:**

1. Enable replication on suffix (pre-created or via separate role).
2. On s1, create agreements to s2 and s3; from s2 to s4 (partial mesh).
3. `ds_repl_wait` on s1 and s2 (should pass).
4. CRUD probe (optional sanity): write on s1, read on s3 within 60s.
5. Negative test: break trust (wrong client cert) → `ds_repl_wait` must fail with auth hint, then fix and pass.

**Assertions:**

* `ds_repl_agreement` is idempotent (second run → `changed: false`).
* `ds_repl_info` returns numeric codes and epochs.
* `ds_repl_wait` respects `timeout`, `stale_seconds`, `steady_ok_polls`.

---

## 11) Error Messages & Hints (Examples)

* `update_code != 0` → `"Replication update failed (code {{code}}). Check consumer availability and credentials."`
* `init_code != 0` → `"Last init failed (code {{code}}). Trigger re-init after fixing credentials or connectivity."`
* `stale` → `"Last update stale ({{age}}s > {{stale_seconds}}s). Possible link outage or hung consumer."`
* `auth` hints if code in `{49, 401, -1}` → point to bind DN/password or mTLS CA/chain issues.
* `conn` hints for codes typical of TCP problems → point to firewall/DNS.

---

## 12) Security & Secrets

* Never log `bind_pw`; mark `no_log=True`.
* Prefer ldapi + SASL/EXTERNAL (no secrets).
* For SIMPLE bind, accept only LDAPS/StartTLS; refuse plaintext by default.
* For SSLCLIENTAUTH, require both `tls_client_cert` & `tls_client_key`.
* Allow users to source secrets from Ansible Vault or external lookup plugins.

---

## 13) Performance & Scale Guidance

* Recommend `serial: 5` for agreement creation/wait steps.
* Encourage **wave-based init** (hub seeds spokes, then spokes seed further).
* Each `ds_repl_wait` run does O(1) queries per poll; default poll interval 10s, timeout 900s.
* Avoid controller `until:` loops; keep the loop inside `ds_repl_wait`.

---

## 14) Acceptance Criteria (Definition of Done)

* All three modules + filter plugin implemented with docs & examples.
* Idempotent behavior verified by Molecule.
* Clear, structured returns suitable for dashboards.
* Helpful failures with actionable `hints`.
* Works on RHDS 11/12 and 389-DS 1.4+; gracefully downgrades features when unsupported.
* No external CLI dependencies required when `python-ldap` is present.
* CI passes lint (`ansible-lint`, `flake8`), and basic unit tests for the filter plugin.

---

## 15) Stretch Goals (Optional)

* `ds_repl_ruv_compare` module to pull `nsds50ruv` from a host list and emit divergence reports.
* CRUD probe module to validate end-to-end replication within an SLO window.
* Mermaid graph generator from `ds_repl_info` output for topology docs.

---

### Ready-to-use Prompts for Implementation Tasks

* **Implement `module_utils/dsldap.py`** to support ldapi SASL/EXTERNAL and LDAPS SIMPLE/mTLS, with retry/timeout, and `search_one/add/modify/delete` helpers.
* **Build `generalized_time_to_epoch` filter** with exhaustive tests including leap day and fractional seconds.
* **Implement `ds_repl_info`** to enumerate agreements and parse codes/epochs.
* **Implement `ds_repl_agreement`** with drift detection and safe adds/mods/deletes.
* **Implement `ds_repl_wait`** with internal polling loop, success streak, and rich failure `observations`+`hints`.
* **Create Molecule `4node`** scenario validating idempotency and wait behavior.

If any attribute names differ on a target version, **detect at runtime** (schema check) and **warn + skip** rather than failing hard.
