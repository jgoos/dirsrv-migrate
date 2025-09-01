SHELL := /bin/bash
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
	@echo "Targets: migrate [ARGS=--check], up_389ds, init_389ds, seed_389ds, migrate_pod, verify_389ds, deps_podman, test_389ds, down_389ds, reset_389ds"
	@echo "         clean (git clean -fdx with CONFIRM=1), clean_dry"

# 389-DS prebuilt image workflow (no systemd/SSH)
up_389ds:
	podman compose -f compose/podman-compose.389ds.yml up -d

init_389ds:
	@echo "Waiting for LDAP on rhds11 and rhds12..."
	@for i in $$(seq 1 30); do \
	  podman exec rhds11 ldapsearch -x -H ldap://localhost:389 -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done; \
	for i in $$(seq 1 30); do \
	  podman exec rhds12 ldapsearch -x -H ldap://localhost:389 -s base -b '' '(objectClass=*)' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done

seed_389ds:
	podman exec rhds11 /bin/sh -lc 'test -f /root/example.ldif && ldapadd -x -H ldap://localhost:389 -D "cn=Directory Manager" -w "password" -f /root/example.ldif || true'

migrate_pod:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  site.yml $(ARGS)

verify_389ds:
	@echo "Verifying entries on target (rhds12)"
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=alice | grep -q "uid=alice" && echo "OK: alice present" || (echo "Missing alice" && exit 1)
	podman exec rhds12 ldapsearch -Y EXTERNAL -H ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket -b o=example uid=bob | grep -q "uid=bob" && echo "OK: bob present" || (echo "Missing bob" && exit 1)

deps_podman:
	ansible-galaxy collection install containers.podman

test_389ds: up_389ds init_389ds deps_podman migrate_pod verify_389ds

down_389ds:
	podman compose -f compose/podman-compose.389ds.yml down

reset_389ds:
	podman compose -f compose/podman-compose.389ds.yml down -v || true
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
