REQUIREMENTS – Podman & VM 389-DS Environments

0) Scope & Goals

Provide two reproducible environments for 389-DS (containers on macOS Podman VM + RHEL VMs):
	•	Development (DEV) – persistent, longer-lived, restartable
	•	Integration Testing (INT) – ephemeral, no persistence, never restarted once seeded
	•	VMs – standard RHDS/389-ds-base on RHEL, must use same Ansible code

⸻

1) Environment Matrix

Dimension	DEV (persistent)	INT (ephemeral)	VMs
Storage	Bind mounts (config/db/logs/certs)	Tmpfs/anon volumes (no bind mounts)	Local FS under /etc/dirsrv, /var/lib/dirsrv
Lifecycle	Start/stop/restart allowed	No restarts allowed; full teardown if needed	Start/stop/restart allowed (systemd)
Data seeding	Optional; incremental	Deterministic, clean every run	Deterministic
Image pinning	Tag-based (for iteration)	Immutable digest	Installed RPMs
Logging	Persist on host	Export artifacts before teardown	Local logs, copy summaries
DNS policy	Service names only	Service names only	FQDNs only


⸻

2) Naming & Addressing
	•	Containers: always use Compose service names (ds-s1, ds-s2, …).
	•	VMs: always use FQDN (e.g., rhds-a1.example.com).
	•	Variable: dirsrv_advertised_hostname_final = the only name ever used in agreements or LDAP URLs.

Resolution rule (priority order):
	1.	dirsrv_advertised_hostname if defined
	2.	If dirsrv_target_type == container → inventory_hostname (service name)
	3.	Else → ansible_fqdn | default(inventory_hostname)

🚫 No IP literals. No mixing service names and FQDNs.

⸻

3) Storage Layout

DEV
	•	Persist all instance paths: /etc/dirsrv/..., /var/lib/dirsrv/..., /var/log/dirsrv/..., /etc/dirsrv/.../certs, /data/db.
	•	Bind mounts live under .ansible/containers/<svc>/....

INT
	•	Tmpfs/anon volumes only.
	•	Recommended tmpfs:
	•	/var/lib/dirsrv/...: size=1G
	•	/var/log/dirsrv/...: size=128M
	•	Any artifact needed must be copied out before teardown.

⸻

4) Container Lifecycle Contracts
	•	DEV: restarts allowed.
	•	INT: restarts forbidden after seeding begins; if restart required, tear down and rebuild.
	•	Enforced by role var:

dirsrv_no_restart: "{{ env_type == 'int' }}"


	•	VMs: restarts allowed (systemd handlers).

⸻

5) Deterministic Seeding (INT & VMs)
	•	Start from clean slate.
	•	Seed LDIF, schema, and indexes via idempotent tasks.
	•	Sequence:
	1.	Base suffix creation
	2.	Required indexes/schema changes
	3.	Test entries load
	•	Fail fast on divergence.

⸻

6) Replication Setup
	•	Agreements use dirsrv_advertised_hostname_final only.
	•	Replica ID policy:
	•	Suppliers get fixed IDs (1..N).
	•	Consumers use 65535.
	•	Verification:
	•	Agreement present in dsconf list
	•	Monitor reports green
	•	RUV present, change count increasing

⸻

7) Readiness & Preflight Gates

Sequence
	1.	DNS resolution (getent hosts {{ peer }})
	2.	TCP handshake (nc -vz {{ peer }} 389/636)
	3.	Base search over TCP LDAP (ldapsearch -x -H ldap://{{ peer }}:389)

LDAPI socket
	•	Containers: /data/run/slapd-localhost.socket
	•	VMs: /run/slapd-localhost.socket

⸻

8) Observability & Artifacts
	•	Logs: errors, access, audit.
	•	Replication status: agreements, RUV per suffix.
	•	namingContexts, listener sockets, Ansible timings, sanitized vars snapshot.

DEV: logs persist in bind mounts.
INT: export all artifacts to .ansible/artifacts/<run-id>/... before teardown.
VMs: leave logs on host; copy summaries.

⸻

9) Security & Secrets
	•	No secrets in git.
	•	Provide via .env, Podman secrets, or Ansible vault.
	•	Required:
	•	DS_DM_PASSWORD
	•	Any test bind DN passwords

⸻

10) Image & Packages
	•	DEV: pin to stable tag.
	•	INT: pin by immutable digest (quay.io/389ds/dirsrv@sha256:...).
	•	VMs: install RHDS/389-ds-base via RPM.

⸻

11) Time & Sync
	•	Max clock skew: ≤ 2s across nodes.
	•	NTP must be enabled on Podman VM and VMs.

⸻

12) Firewalld & SELinux (VMs only)
	•	Open ports 389, 636.
	•	Verify SELinux contexts/booleans for RHDS defaults.

⸻

13) Timeouts (defaults)
	•	LDAPI readiness (local): ≤ 20s
	•	TCP readiness: ≤ 15s per peer
	•	Initial replication init per agreement: ≤ 120s
	•	Mesh convergence (4-node): ≤ 4m
	•	Entire INT job: ≤ 10m

⸻

14) Acceptance Criteria
	•	Same Ansible role works for containers and VMs; only inventory/group vars differ.
	•	Agreements always use canonical advertised hostname.
	•	INT fails if:
	•	restart occurs,
	•	preflight gates fail, or
	•	convergence exceeds SLA.
	•	Artifacts are exported (INT) or persisted (DEV/VM).

⸻

15) Non-Goals
	•	TLS/PKI lifecycle (CSR/renewal) – separate doc.
	•	Multi-host Podman networking.
	•	Reverse proxy/ingress design.

⸻

16) Open Questions
	•	Do we require TLS in INT runs, or only plaintext?
	•	For INT: prefer tmpfs (fast, ephemeral) or anon volumes (less memory)?
	•	Max acceptable convergence time in larger topologies (e.g., 30-node mesh)?

⸻