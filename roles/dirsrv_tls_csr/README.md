# dirsrv_tls_csr — Generate & Collect RHDS/389-DS CSRs

Purpose: Generate a standards-compliant TLS CSR for each RHDS/389-DS instance on a host, then fetch artifacts to the controller for CA submission. Supports RHDS 12 native `dsctl` flow (DNS SANs) and an NSS `certutil` fallback (RHDS 11 or when IP SANs are required).

Highlights
- Multiple instances per host (auto-discover or explicit list).
- CN = host FQDN (`inventory_hostname`); SANs required, sourced from host vars.
- Prefers `dsctl ... tls generate-server-cert-csr` (RHDS 12); falls back to `certutil --extSAN`.
- Idempotent: skip if CSR exists unless `dirsrv_csr.force: true`.
- Artifacts fetched to controller under `{{ dirsrv_csr.artifacts_root }}/tls/{{ inventory_hostname }}/` with a manifest.

Inventory and variables
- Host SANs (ensure the host FQDN is included):

  dirsrv_csr_sans:
    dns:
      - "{{ inventory_hostname }}"
      - ldap.example.com
    ip:            # optional — triggers certutil fallback
      - 10.0.0.11

- Main defaults (override in group_vars/host_vars as needed):

  dirsrv_csr:
    subject_defaults:        # RFC1485/RFC4514
      C: PT
      ST: Lisboa
      L: Lisbon
      O: "Your Company LDA"
      OU: "IAM Directories"
      emailAddress: ops@example.com

    key_type: rsa            # rsa|ecdsa (certutil path)
    key_size: 4096
    ecdsa_curve: prime256v1
    sig_algo: SHA256

    instance_discovery: auto # auto|list
    instances: []            # if list, e.g., ["prod", "m1"]

    # Reuses repo standard if present; falls back to .ansible/artifacts
    artifacts_root: "{{ dirsrv_artifact_root_effective | default([playbook_dir, '.ansible', 'artifacts'] | path_join) }}"

    force: false

Behavior (vendor-aligned)
- RHDS 12 (preferred when only DNS SANs are required):
  dsctl <instance> tls generate-server-cert-csr -s "<Subject>" <dnsSAN1> <dnsSAN2> ...
  CSR written to /etc/dirsrv/slapd-<instance>/Server-Cert.csr

- Fallback for RHDS 11 or IP SANs:
  certutil -R -d /etc/dirsrv/slapd-<instance> -f pin.txt \
           -s "<Subject>" --extSAN "dns:...,dns:...,ip:..." -Z SHA256 -a -o Server-Cert.csr

Artifacts collected (controller)
- CSR: `{{ inventory_hostname }}-{{ instance }}.csr`
- Manifest: `csr-info.yml` with fields: cn, sans.dns, sans.ip, instance, tool, tool_path, sha256, generated_at, csr_path.

Usage
- Example play:

  - name: Generate & collect RHDS CSRs
    hosts: ldap_servers
    become: true
    roles:
      - role: dirsrv_tls_csr

- Common commands:
  - Syntax check: `ansible-playbook --syntax-check site.yml`
  - Dry run: `ansible-playbook -i inventory.yml site.yml --check --diff`
  - Limit a subset: `ansible-playbook -i inventory.yml site.yml --limit ldap_servers`

Security notes
- Do not log secret contents. This role never reads nor modifies the contents of `pin.txt`/`pwdfile.txt`; it only passes their path to `certutil` when needed. Ensure these files have restrictive permissions owned by `dirsrv`.
- Generated CSR file permissions normalized to `0640`, owner/group `dirsrv`.

Future import flow (documented only)
- Import via dsconf:
  dsconf <instance> security certificate add --file <crt> --name "server-cert" --primary-cert
- Or via dsctl:
  dsctl <instance> tls import-server-cert
  dsctl <instance> tls import-server-key-cert

Molecule
- Scenario `default` includes two converge variants:
  - RHDS 12 path with DNS SANs (uses dsctl if available)
  - RHDS 11/IP SANs fallback (uses certutil)
- The scenario is lightweight and intended for CI environments with prebuilt images; adjust platforms as needed.

Tags
- tls, csr, rhds, security, artifacts

