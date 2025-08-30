# Repository Guidelines

## Project Structure & Module Organization
- `site.yml`: Primary playbook orchestrating the DSM migration.
- `inventory.yml`: Hosts grouped as `dsm_source` and `dsm_target`.
- `roles/dsm/`: Role implementing migration logic
  - `tasks/`: `main.yml`, `dsm_source.yml`, `dsm_target.yml`
  - `defaults/main.yml`: Default vars (override in inventory/group_vars)
  - `templates/`: Jinja2 templates (e.g., `slapd.inf.j2`)
- `ansible.cfg`: Local config (e.g., `roles_path = roles`).
- `.ansible/`: Local collections/modules workspace (optional).

## Build, Test, and Development Commands
- Syntax check: `ansible-playbook --syntax-check site.yml`
- Lint (if installed): `ansible-lint` and `yamllint .`
- Dry run with diff: `ansible-playbook -i inventory.yml site.yml --check --diff`
- Target a subset: `ansible-playbook -i inventory.yml site.yml --limit dsm_source`
- Set secrets at runtime: `ansible-playbook -i inventory.yml site.yml -e @group_vars/all/vault.yml`

## Coding Style & Naming Conventions
- YAML: 2-space indent, no tabs; keys lower_snake_case.
- Tasks: clear, imperative `name`; prefer FQCN modules (e.g., `ansible.builtin.command`).
- Variables: define defaults in `roles/dsm/defaults/main.yml`; override via inventory/group_vars.
- Templates: Jinja2 with spaced braces (`{{ var }}`) and minimal logic.
- Files: keep role entrypoints as `main.yml`; split by concern (e.g., `dsm_source.yml`).

## Testing Guidelines
- Idempotence: run playbook twice; second run should show no changes.
- Safety: use `--check` and `--diff` before applying; set `changed_when`/`failed_when` explicitly where needed.
- Naming: test-related files mirror role/feature names; prefer group_vars for overrides.

## Commit & Pull Request Guidelines
- Commits: use Conventional Commits (e.g., `feat: add target import step`, `fix: correct LDIF path`).
- PRs include: purpose/impact, sample command used, `--check` output snippet or reasoning, risks/rollback, and linked issues.
- Screenshots/logs: include relevant task output or diffs for review.

## Security & Configuration Tips
- Do not commit secrets. Move `dsm_password` to Ansible Vault (e.g., `ansible-vault create group_vars/all/vault.yml`) and run with `--ask-vault-pass` or a vault ID.
- Prefer non-root SSH users with `become: true` (inventory shows `ansible_user: root` only as an example).
- Keep inventory hostnames accurate; the play relies on single hosts in `dsm_source` and `dsm_target`.

