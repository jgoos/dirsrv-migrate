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
	@echo "Waiting for LDAP (ldapi) on rhds11 and rhds12..."
	@for i in $$(seq 1 60); do \
	  podman exec rhds11 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done; \
	for i in $$(seq 1 60); do \
	  podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done

seed_389ds: deps_podman
	@echo "Seeding example data on rhds11 via Ansible"
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
	@echo "Verifying entries on target (rhds12)"
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=alice | grep -q "uid=alice" && echo "OK: alice present" || (echo "Missing alice" && exit 1)
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=bob | grep -q "uid=bob" && echo "OK: bob present" || (echo "Missing bob" && exit 1)
	# Verify nested group and service account
	podman exec rhds12 ldapsearch -Y EXTERNAL -LLL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b 'cn=staff,ou=groups,o=example' -s base uniqueMember | grep -iq "uniqueMember: cn=devs,ou=groups,o=example" && echo "OK: staff includes devs" || (echo "Missing nested group" && exit 1)
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=app-x | grep -q "uid=app-x" && echo "OK: app-x present" || (echo "Missing app-x" && exit 1)
	# Verify an ACI string imported into data
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example '(aci=*)' aci | grep -q "Devs can write mail" && echo "OK: ACI present" || (echo "Missing data ACI" && exit 1)

deps_podman:
	ansible-galaxy collection install containers.podman

test_389ds: up_389ds init_389ds deps_podman seed_389ds migrate_pod verify_389ds

# End-to-end replication test (supplier rhds11 -> consumer rhds12)
test_repl: up_389ds init_389ds deps_podman seed_389ds repl_pod verify_389ds

down_389ds:
	$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down

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
	@echo "Waiting for LDAP (ldapi) on rhds11, rhds12, rhds13, rhds14..."
	@for h in rhds11 rhds12 rhds13 rhds14; do \
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
