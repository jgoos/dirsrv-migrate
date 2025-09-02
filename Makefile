SHELL := /bin/bash
# Prefer calling podman-compose directly (silences podman wrapper warning),
# fallback to `podman compose` when podman-compose is not installed.
COMPOSE_CMD := $(shell command -v podman-compose >/dev/null 2>&1 && echo podman-compose || echo podman compose)
.DEFAULT_GOAL := test_389ds

.PHONY: migrate help \
	up_389ds init_389ds seed_389ds migrate_pod deps_podman test_389ds verify_389ds down_389ds reset_389ds \
	clean clean_dry

# Default migrate uses Podman connection (no sshpass/SSH required)
migrate: deps_podman
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  site.yml $(ARGS)

help:
	@echo "Targets: migrate [ARGS=--check], up_389ds, init_389ds, seed_389ds, migrate_pod, repl_pod, verify_389ds, deps_podman, test_389ds, test_repl, test_repl_mesh, down_389ds, reset_389ds"
	@echo "         clean (git clean -fdx with CONFIRM=1), clean_dry"

# 389-DS prebuilt image workflow (no systemd/SSH)
up_389ds:
	$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml up -d

init_389ds:
	@echo "Waiting for LDAP (ldapi) on ds-s1 and ds-c1..."
	@for i in $$(seq 1 60); do \
	  podman exec ds-s1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done; \
	for i in $$(seq 1 60); do \
	  podman exec ds-c1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done

seed_389ds: deps_podman
	@echo "Seeding example data on ds-s1 via Ansible"
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  test/seed.yml

migrate_pod:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  site.yml $(ARGS)

# Run replication role against compose lab
repl_pod:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  -e @test/repl_vars.yml \
	  test/repl.yml $(ARGS)

verify_389ds:
	@echo "Verifying entries on target (ds-c1)"
	@verify() { name="$$1" cmd="$$2"; for i in $$(seq 1 60); do eval "$$cmd" >/dev/null 2>&1 && echo "OK: $$name" && return 0; sleep 1; done; echo "Missing $$name" >&2; exit 1; }; \
	verify "alice present" "podman exec ds-c1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=alice | grep -q 'uid=alice'"; \
	verify "bob present" "podman exec ds-c1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=bob | grep -q 'uid=bob'"; \
	verify "staff includes devs" "podman exec ds-c1 ldapsearch -Y EXTERNAL -LLL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b 'cn=staff,ou=groups,o=example' -s base uniqueMember | grep -iq 'uniqueMember: cn=devs,ou=groups,o=example'"; \
	verify "app-x present" "podman exec ds-c1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=app-x | grep -q 'uid=app-x'"; \
	verify "ACI present" "podman exec ds-c1 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example '(aci=*)' aci | grep -q 'Devs can write mail'"

deps_podman:
	ansible-galaxy collection install containers.podman

test_389ds: up_389ds init_389ds deps_podman seed_389ds migrate_pod verify_389ds

# End-to-end replication test (supplier ds-s1 -> consumer ds-c1)
test_repl: up_389ds init_389ds deps_podman seed_389ds repl_pod verify_389ds

down_389ds:
	$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down

reset_389ds:
	$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down -v || true
	rm -rf .ansible/artifacts/compose-dev || true

# Show what would be removed (untracked + ignored files)
clean_dry:
	@echo "[dry-run] git clean -fdx -n"
	@git clean -fdx -n

# Remove everything not tracked by git (DANGEROUS)
# Usage: make clean CONFIRM=1
clean:
	@if [ "$(CONFIRM)" != "1" ]; then \
	  echo "Refusing to delete without CONFIRM=1"; \
	  echo "Run: make clean_dry   # to preview"; \
	  echo "Run: make clean CONFIRM=1   # to delete"; \
	  exit 2; \
	fi
	@git clean -fdx
# Mesh replication test (2 suppliers, 2 consumers)

init_389ds_mesh:
	@echo "Waiting for LDAP (ldapi) on ds-s1, ds-c1, ds-s2, ds-c2..."
	@for h in ds-s1 ds-c1 ds-s2 ds-c2; do \
	  for i in $$(seq 1 60); do \
	    podman exec $$h ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	    sleep 1; \
	  done; \
	done

repl_pod_mesh:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod4.yml \
	  -e @test/repl_mesh_vars.yml \
	  test/repl_mesh.yml $(ARGS)

test_repl_mesh: up_389ds init_389ds_mesh deps_podman seed_389ds repl_pod_mesh verify_389ds
