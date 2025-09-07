# Repository Guidelines

## Simplicity First
- Keep the codebase small: add only files that serve a clear purpose.
- Prefer readability and maintainability over cleverness or abstractions.
- Use built-in Ansible modules and features; avoid extra collections unless required.
- Keep templates simple with minimal Jinja2 logic; move logic into variables when possible.
- Avoid deep includes/imports; split by clear concern but keep the structure shallow.
- Be explicit over generic: a few clear tasks beat a complex loop when it aids clarity.
- Minimize custom plugins/filters; only introduce them when absolutely necessary.
- Optimize for idempotence and clarity: set `changed_when`/`failed_when` where helpful.
- Document intent briefly in task names; keep comments short and practical.

## Project Structure & Module Organization
- `site.yml`: Primary playbook orchestrating the overall workflow.
- `inventory.yml`: Hosts grouped into source/target groups (e.g., `dirsrv_source`/`dirsrv_target`) for migration; lab inventories live under `inventories/`.
- `roles/dirsrv_migrate/`: Migration role (source/target flows)
  - `tasks/`: `main.yml`, `source.yml`, `target.yml`
  - `defaults/main.yml`: Default vars (override in inventory/group_vars)
  - `templates/`: (if used) keep Jinja2 minimal
- `roles/dirsrv_repl/`: Replication role (enable, agreements, init, wait/monitor)
- `roles/dirsrv_tls/`: TLS helper role for DS instances
- `roles/dirsrv_tls_csr/`: CSR generation scenarios (lab/testing)
- `ansible.cfg`: Local config (e.g., `roles_path = roles`).
- `.ansible/`: Local collections/modules workspace (optional).

## Collections Development Workflow (policy)
- Never develop new code under `.ansible/`. That path is ignored by Git and reserved for installed artifacts only.
- Always develop collection sources under the vendored path `collections/ansible_collections/directories/ds`.
- Build and install the collection via Makefile targets:
  - `make collection_build` – packages the collection from `collections/…/directories/ds`.
  - `make collection_install_dev` – installs the built tarball to `.ansible/collections` for local runs.
  - `make collection_install_user` – installs to `~/.ansible/collections`.
- `ansible.cfg` is configured to search `collections/`, then `.ansible/collections`, then user path.
- Rationale: prevents drift and ensures all source code is versioned. The `.ansible/` tree should only contain generated/install artifacts.

## Build, Test, and Development Commands
- Syntax check: `ansible-playbook --syntax-check site.yml`
- Lint (if installed): `ansible-lint` and `yamllint .`
- Dry run with diff: `ansible-playbook -i inventory.yml site.yml --check --diff`
- Target a subset: `ansible-playbook -i inventory.yml site.yml --limit <source-group>`
- Set secrets at runtime: `ansible-playbook -i inventory.yml site.yml -e @group_vars/all/vault.yml`

## Vault Usage
- Store secrets in `group_vars/all/vault.yml` (encrypted with Ansible Vault).
- Create/update: `ansible-vault edit group_vars/all/vault.yml` and set `dirsrv_password: <secret>`.
- Run with vault password prompt: `ansible-playbook -i inventory.yml site.yml --ask-vault-pass`.
- Or with vault IDs: `ansible-playbook -i inventory.yml site.yml --vault-id dev@prompt`.
- Note: `.gitignore` excludes `.ansible/` artifacts and `group_vars/all/vault.yml`.

## Coding Style & Naming Conventions
- YAML: 2-space indent, no tabs; keys lower_snake_case.
- Tasks: clear, imperative `name`; prefer FQCN modules (e.g., `ansible.builtin.command`).
- Variables: define defaults in `roles/dirsrv_migrate/defaults/main.yml`; override via inventory/group_vars. Use `dirsrv_*` variables only; do not use `dsm_*` variables.
- Templates: Jinja2 with spaced braces (`{{ var }}`) and minimal logic.
- Files: keep role entrypoints as `main.yml`; split by concern (e.g., `source.yml`).

## Testing Guidelines
- Idempotence: run playbook twice; second run should show no changes.
- Safety: use `--check` and `--diff` before applying; set `changed_when`/`failed_when` explicitly where needed.
- Naming: test-related files mirror role/feature names; prefer group_vars for overrides.

## Commit & Pull Request Guidelines
- Commits: use Conventional Commits (e.g., `feat: add target import step`, `fix: correct LDIF path`).
- PRs include: purpose/impact, sample command used, `--check` output snippet or reasoning, risks/rollback, and linked issues.
- Screenshots/logs: include relevant task output or diffs for review.
- No direct pushes to `main`: always work on a feature branch and open a PR.


## Security & Configuration Tips
- Do not commit secrets. Move `dirsrv_password` to Ansible Vault (e.g., `ansible-vault create group_vars/all/vault.yml`) and run with `--ask-vault-pass` or a vault ID.
- Prefer non-root SSH users with `become: true` (inventory shows `ansible_user: root` only as an example).
- Keep inventory hostnames accurate; the play relies on single hosts in the configured source/target groups.
- Mask secrets in logs: set `no_log: true` on tasks that pass or render sensitive values (e.g., `dirsrv_password`, replication bind_password). Avoid `debug: var=` for secret variables.
- Prefer `ansible.builtin.command` with `argv` over `shell`. Only use `shell` when needed (pipes, redirection), sanitize inputs, and set explicit `changed_when`/`failed_when`.
- Pin dependencies: use a `collections/requirements.yml` with explicit versions for collections (e.g., `containers.podman`). Install with `ansible-galaxy collection install -r collections/requirements.yml`.
- Container lab hardening: avoid exposing host ports when not needed; prefer LDAPI for local admin operations. Force-remove stale containers before up/down on macOS Podman.
- Supply chain: prefer versioned image tags or digests for reproducibility in compose files.

## Ansible Best Practices (additions)
- Idempotence: always set `changed_when`/`failed_when` on command/shell tasks to prevent false positives and to surface real failures.
- Check mode: destructive operations should respect `ansible_check_mode`; skip when appropriate and explain what would change.
- Input validation: use `ansible.builtin.assert` early (e.g., topology, unique replica IDs) with actionable `fail_msg`.
- Namespacing: keep variable prefixes consistent (`dirsrv_*`, `dirsrv_repl_*`) and avoid deprecated aliases.

## Branching & Protection (repo policy)
- Protect `main`: require PR reviews and passing checks. Disallow force pushes and direct pushes.
- Use feature branches per change; keep PRs focused and scoped.


## Lab Topology & Ports (from DESIGN)
- Containers: upstream 389-DS images under Podman on macOS.
- Topologies: 2 suppliers (s1,s2) + consumers (c1,c2) or full mesh.
- Naming: use deterministic FQDNs `*.dsnet.test`; instance names align to container names.
- Ports in containers: LDAP `3389`, LDAPS `3636`, LDAPI socket under `/data/run/slapd-<instance>.socket`.
- Agreements use container DNS names (e.g., `s1.dsnet.test:3389/3636`).

## Podman & Networking
- Use a single user-defined network (e.g., `dsnet`) with DNS enabled; avoid multiple networks per container.
- Prefer running Ansible against containers via the Podman connection plugin or inside the Podman VM so `*.dsnet.test` resolves.
- Health: wait for LDAPI readiness before configuration (see `init_389ds*` targets).

## TLS & Certificates
- Prefer upstream 389-DS container TLS flow. Certificates’ CN/SANs must match `*.dsnet.test` names.
- For lab stability, use LDAP on `3389` during replication bring-up; switch to LDAPS `3636` only when trust is fully configured.

## Replication Conventions
- Unique replica IDs per supplier/hub per suffix.
- Create all agreements first (without `--init`), then initialize serially per suffix/target.
- Serialize init/poll (use `throttle: 1`) to avoid replica lock contention (UpdateInProgress/RUV errors).
- Keep `nsDS5ReplicaReleaseTimeout` moderate (default 60s is fine) to avoid prolonged locks.

## Health Gating (robust, non-interactive)
- Avoid dsconf prompts in gates. For health, read agreement entries via `ldapsearch`:
  - DN: `cn=<agmt>,cn=replica,cn=<escaped suffix>,cn=mapping tree,cn=config`.
  - Keys: `nsds5replicaLastInitStatusJSON`, `nsds5replicaLastUpdateStatusJSON`, `nsds5replicaUpdateInProgress`.
  - Healthy when JSON shows `"error": 0` or messages like `Total update succeeded`, `Incremental update succeeded`, `Replica acquired successfully`, and UpdateInProgress is not true.
- Use EXTERNAL over LDAPI; otherwise bind as Directory Manager (lab default) for non-interactive checks.

## Credentials
- Store secrets in Vault for real environments.
- For the lab, `Directory Manager` may be used as the replication bind to reduce drift; production should use a dedicated `cn=replication manager,cn=config` with inbound authorization per suffix.

## Make Targets & Flows
- Spin-up: `make up` (or `up_389ds`), then `make init_389ds_mesh` to wait on LDAPI.
- Full mesh test: `make test_repl_mesh ARGS=" -e dirsrv_debug=true -e dirsrv_log_capture=true -vvv"`.
- Targeted convergence: `make repl_pod_mesh ARGS="... --limit ds-s1"` (then `ds-s2`).
- Reset: `make reset_hard` (add `PURGE=1` to remove volumes) or `make reset_soft` to restore gold backups in containers.
- Logs bundle: `make bundle_logs` (includes `.ansible/test_logs` and test artifacts under `test/.ansible/artifacts`).

## Troubleshooting (quick RCA)
- Agreement snapshot:
  - `ldapsearch -x -D "cn=Directory Manager" -w $PW -H ldap://localhost:3389 -b 'cn=<agmt>,cn=replica,cn=<escaped suffix>,cn=mapping tree,cn=config' -s base nsds5replicaLastInitStatusJSON nsds5replicaLastUpdateStatusJSON nsDS5ReplicaUpdateInProgress`
- Replica present:
  - `dsconf -j -D "cn=Directory Manager" -w $PW ldap://localhost:3389 replication get --suffix dc=example,dc=com`
  - If missing on consumers: `replication enable --suffix dc=example,dc=com --role consumer`.
- Inbound allowlist:
  - `dsconf -D "cn=Directory Manager" -w $PW ldap://localhost:3389 replication set --suffix dc=example,dc=com --repl-add-bind-dn "<bind DN>"`.
- Final clean re-init:
  - `dsconf -D "cn=Directory Manager" -w $PW ldap://localhost:3389 repl-agmt init --suffix dc=example,dc=com <agmt-name>` then poll `init-status`.

## Contribution Notes (agent focus)
- Prefer `argv` with `ansible.builtin.command`; keep `no_log: true` where secrets might appear.
- Validate inputs (unique IDs, nodes present) with `assert`.
- Add serialization (`throttle: 1`) around init/poll operations.
- Favor non-interactive health checks and avoid prompts.
