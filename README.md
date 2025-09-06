RHDS 11 → 12 Migration with Ansible (389‑DS)

Automates export/import migrations from Red Hat Directory Server (389‑DS) RHDS 11 to RHDS 12. The playbook performs per‑backend LDIF export on sources, stages artifacts on the controller, and imports into mapped targets. Server configuration is reapplied on RHDS 12 using supported tools (avoid copying dse.ldif across major versions).

- Safe by default: validates strict 1:1 source→target mapping and checks artifacts before import.
- Idempotent: tasks favor explicit `changed_when`/`failed_when` and support `--check`/`--diff`.
- Scales to many pairs: artifacts are isolated per source (and optional run label).


## Repository Structure
- `site.yml`: Orchestrates validation, source export, and target import.
- `inventory.yml`: Example hosts grouped as `dirsrv_source` and `dirsrv_target`.
- `group_vars/all/dirsrv_mapping.yml`: Defines `dirsrv_host_map` (source→target).
- `roles/dirsrv_migrate/`: Migration role
  - `tasks/main.yml`: Calls preflight and routes to `source.yml`/`target.yml`.
  - `tasks/source.yml`: Exports LDIFs and collects optional config archive.
  - `tasks/target.yml`: Copies artifacts, ensures backends, cleans LDIF, and imports.
  - `defaults/main.yml`: Default variables (override in inventory or group_vars).
- `roles/dirsrv_repl/`: Replication role (suppliers/consumers/hubs)
  - `tasks/enable.yml`: Enables replication role per suffix (supplier/consumer) and ensures suffix exists.
  - `tasks/agreements.yml`: Creates agreements, optional schedule/fractional replication, polls init.
  - `tasks/tuning.yml`: Changelog purge/encryption and release-timeout tuning.
  - `README.md`: Usage, auth modes, examples (single + mesh topologies).
- `roles/dirsrv_common/tasks/preflight.yml`: Detects `dsconf` path/capabilities.
- `docs/`: Reference guides and templates (variables, inventory/mapping, migration notes).
- `compose/`, `test/`, `scripts/`, `testdata/`: Local Podman test setup and example data.
- `ansible.cfg`: Local Ansible config (`roles_path = roles`).


## Requirements
- Controller: Ansible (core), Python, SSH or Podman connection depending on target environment.
- Managed hosts (real servers):
  - 389‑DS/RHDS tools installed (must have `dsconf`).
  - Systemd if `dirsrv_manage_service: true` (default). Set to `false` in containers.
- Secrets: `dirsrv_password` stored in Ansible Vault when using `ldapsearch` fallback.
- Optional local testing: Podman and `containers.podman` collection.


## Quick Start (real servers)
1) Define inventory and mapping
- Edit `inventory.yml` to list your RHDS 11 sources and RHDS 12 targets.
- Set a 1:1 map in `group_vars/all/dirsrv_mapping.yml` under `dirsrv_host_map`.
  - Templates for many pairs are in `docs/INVENTORY_AND_MAPPING_TEMPLATE.md`.

2) Store secrets in Vault
- Create `group_vars/all/vault.yml` and add at least `dirsrv_password: <secret>`:
  - `ansible-vault edit group_vars/all/vault.yml`

3) (Optional) Tune variables
- Override defaults from `roles/dirsrv_migrate/defaults/main.yml` in `group_vars` or `-e`.
- Typical overrides: `dirsrv_instance`, `dirsrv_backends`, `dirsrv_artifact_run`.

4) Validate, dry run, then apply
- Syntax check: `ansible-playbook --syntax-check site.yml`
- Mapping only (localhost): `ansible-playbook -i inventory.yml site.yml --check --diff --limit localhost`
- Full dry run: `ansible-playbook -i inventory.yml site.yml --check --diff`
- Apply with vault prompt: `ansible-playbook -i inventory.yml site.yml --ask-vault-pass`

Notes
- Limit stages: `--limit dirsrv_source` or `--limit dirsrv_target`.
- Artifacts path: `.ansible/artifacts/<run-label>/<source-host>/` (set `dirsrv_artifact_run` to isolate batches).


## How It Works
- Validation (localhost): Asserts mapping is 1:1 and hosts exist in the right groups.
- Source (dirsrv_source):
  - Optional stop/start for offline export when `dirsrv_export_offline: true`.
  - Exports LDIF per backend via `dsconf` (preferred). Fallback: `ldapsearch`.
  - Fetches LDIFs and optional config archive to controller under `.ansible/artifacts`.
- Target (dirsrv_target):
  - Verifies expected artifacts exist on controller for its mapped source.
  - Copies LDIFs (and optional schema/config), ensures backends, performs import with `dsconf`.

Tags (for troubleshooting)
- `export`, `artifacts`, `import`, `preflight`.


## Local Testing (Podman, no SSH)
This repo includes a minimal local lab using prebuilt 389‑DS images.

- Bring up containers: `podman compose -f compose/podman-compose.389ds.yml up -d` (fallback: `podman-compose ...`)
- Seed example data on source: `make seed_389ds`
- Migrate via Podman connection: `make migrate_pod` (or `make test_389ds` for full flow)
- Verify migration: `make verify_389ds`
- Replication role (single supplier→consumer): `make test_repl`
- Replication role mesh (2 suppliers + 2 consumers): `make test_repl_mesh`

Files
- `test/inventory.compose.pod.yml`: Podman connection inventory (ds-s1, ds-c1).
- `test/compose_mapping.yml`: `ds-s1 → ds-c1` map.
- `test/compose_vars.yml`: Test vars (e.g., `dirsrv_instance`, `dirsrv_manage_service: false`).
- `test/seed.yml`: Seeds `testdata/example.ldif` into `ds-s1`.

Tips
- macOS: run `podman machine start` before tests. Ensure your user has access to the Podman socket.
- This repo prefers native `podman compose` for stability; `podman-compose` is used only as a fallback.
- Collections are installed locally under `.ansible/collections` via `collections/requirements.yml`.


## Key Variables (override as needed)
- `dirsrv_instance`: Instance name (e.g., `dir`). Default: `dir`.
- `dirsrv_backends`: Backends and suffixes to migrate. Default `userroot: { suffix: "o=example" }`.
- `dirsrv_artifact_root`: Controller artifact root. Default: `.ansible/artifacts`.
- `dirsrv_artifact_run`: Optional run label appended under artifact root.
- `dirsrv_export_method`: `dsconf` (recommended) or `ldapsearch`.
- `dirsrv_manage_service`: Manage `dirsrv@<instance>` via systemd. Default: `true`.
- `dirsrv_collect_config`: Collect config archive (for schema extraction). Default: `true`.

See full defaults in `roles/dirsrv_migrate/defaults/main.yml` and naming notes in `docs/VARIABLES_AND_COMPATIBILITY.md`.


## Security
- Do not commit secrets. Store `dirsrv_password` in `group_vars/all/vault.yml` and run with `--ask-vault-pass` or a vault ID.
- Prefer non‑root remote users with `become: true`. The example inventory uses `ansible_user: root` for simplicity only.


## Troubleshooting
- `dsconf not found`: Ensure 389‑DS tools are installed on managed hosts. Preflight probes `dsconf` path.
- Mapping assertion fails: Keep a strict 1:1 map; all keys in `dirsrv_source` and all values in `dirsrv_target`.
- Missing artifacts on target: Re‑run source export, confirm files under `.ansible/artifacts/<run>/<source>/`.
- Container tests: set `dirsrv_manage_service: false` and use the Podman inventory.
- Podman on macOS: if you see `proxy already running` when bringing up the lab, re‑run the Makefile targets; we avoid host port mappings and force‑remove stale containers to stabilize compose up/down.


## Contributing
- Follow the style in `AGENTS.md` (simplicity, clarity, idempotence).
- Use Conventional Commits (e.g., `feat: add target import step`).
- Validate with `--check`/`--diff`; include relevant logs or diffs in PRs.
