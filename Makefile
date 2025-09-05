SHELL := /bin/bash
# Prefer calling podman-compose directly (silences podman wrapper warning),
# fallback to `podman compose` when podman-compose is not installed.
COMPOSE_CMD := $(shell command -v podman-compose >/dev/null 2>&1 && echo podman-compose || echo podman compose)
.DEFAULT_GOAL := test_389ds

# Timing helper and lab params
.SHELLFLAGS := -eu -o pipefail -c
define _time
	@start=$$(date +%s); \
	{ $(1) ; }; \
	rc=$$?; end=$$(date +%s); \
	echo "[TIMING] $(2): $$((end-start))s (rc=$$rc)"; \
	exit $$rc
endef

DS_IMAGE := quay.io/389ds/dirsrv:latest
NET_NAME := replnet

.stamps/%:
	@mkdir -p .stamps
	@touch $@

.PHONY: migrate help \
	up_389ds init_389ds seed_389ds migrate_pod deps_podman test_389ds verify_389ds down_389ds reset_389ds \
	clean clean_dry test_ldif_filter csr_pod verify_csr test_csr

# Additional CSR scenarios
.PHONY: csr_pod_multi verify_csr_multi test_csr_edges

# Default migrate uses Podman connection (no sshpass/SSH required)
migrate: deps_podman
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  site.yml $(ARGS)

help:
	@echo "Targets: migrate [ARGS=--check], up_389ds, init_389ds, seed_389ds, migrate_pod, repl_pod, verify_389ds, deps_podman, test_389ds, test_ldif_filter, test_repl, test_repl_mesh, test_csr, down_389ds, reset_389ds"
	@echo "         clean (git clean -fdx with CONFIRM=1), clean_dry"

# 389-DS prebuilt image workflow (no systemd/SSH)
pull_if_needed: .stamps/pull
.stamps/pull:
	@mkdir -p .stamps
	@podman image exists $(DS_IMAGE) >/dev/null 2>&1 || podman pull $(DS_IMAGE)
	@touch $@

net: .stamps/net
.stamps/net:
	@mkdir -p .stamps
	@podman network inspect $(NET_NAME) >/dev/null 2>&1 || podman network create $(NET_NAME)
	@touch $@

up_389ds: pull_if_needed net
	$(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml up -d --no-recreate,compose_up)

up_389ds_fast: net
	$(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml up -d --no-recreate,compose_up_fast)

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
	$(call _time,ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  test/seed.yml,seed)

migrate_pod:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  site.yml $(ARGS)

# Run replication role against compose lab
repl_pod:
	$(call _time,ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  -e @test/repl_vars.yml \
	  test/repl.yml $(ARGS),repl_pod)

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

# Exercise LDIF split/filter module and verify artifacts on controller
test_ldif_filter: up_389ds init_389ds deps_podman seed_389ds
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_mapping.yml \
	  -e @test/compose_vars.yml \
	  --limit dirsrv_source \
	  site.yml $(ARGS)
	@set -e; \
	ART_DIR=".ansible/artifacts/compose-dev/ds-s1"; \
	CLEAN="$$ART_DIR/migration-userroot.cleaned.ldif"; \
	REM="$$ART_DIR/migration-userroot.removed.ldif.gz"; \
	ORIGGZ="$$ART_DIR/migration-userroot.ldif.gz"; \
	[ -f "$$CLEAN" ] || { echo "Missing cleaned LDIF: $$CLEAN" >&2; exit 1; }; \
	[ -f "$$REM" ] || { echo "Missing removed LDIF gz: $$REM" >&2; exit 1; }; \
	[ -f "$$ORIGGZ" ] || { echo "Missing original LDIF gz: $$ORIGGZ" >&2; exit 1; }; \
	grep -q "^dn: uid=alice,ou=people,o=example" "$$CLEAN" || { echo "Cleaned LDIF missing expected entry (alice)" >&2; exit 1; }; \
	! grep -qi "^dn: cn=repl" "$$CLEAN" || { echo "Found replication keep-alive entry in cleaned LDIF" >&2; exit 1; }; \
	echo "OK: ldif_filter_split produced expected artifacts and content"

# End-to-end replication test (supplier ds-s1 -> consumer ds-c1)
test_repl: up_389ds init_389ds deps_podman seed_389ds repl_pod verify_389ds

# Run CSR role against compose lab
csr_pod:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  -e dirsrv_artifact_root_effective=$(PWD)/.ansible/artifacts \
	  test/csr.yml $(ARGS)

# Verify CSR artifacts on controller
verify_csr:
	@set -e; \
	ART_DIR_BASE="$(PWD)/.ansible/artifacts/tls"; \
	S1_DIR="$$ART_DIR_BASE/ds-s1"; \
	C1_DIR="$$ART_DIR_BASE/ds-c1"; \
	S1_CSR="$$S1_DIR/ds-s1-localhost.csr"; \
	C1_CSR="$$C1_DIR/ds-c1-localhost.csr"; \
	S1_MAN="$$S1_DIR/csr-info.yml"; \
	C1_MAN="$$C1_DIR/csr-info.yml"; \
	[ -f "$$S1_CSR" ] || { echo "Missing CSR: $$S1_CSR" >&2; exit 1; }; \
	[ -f "$$C1_CSR" ] || { echo "Missing CSR: $$C1_CSR" >&2; exit 1; }; \
	[ -f "$$S1_MAN" ] || { echo "Missing manifest: $$S1_MAN" >&2; exit 1; }; \
	[ -f "$$C1_MAN" ] || { echo "Missing manifest: $$C1_MAN" >&2; exit 1; }; \
	grep -q "tool: dsctl" "$$S1_MAN" || { echo "Expected dsctl path in $$S1_MAN" >&2; exit 1; }; \
	grep -q "tool: certutil" "$$C1_MAN" || { echo "Expected certutil path in $$C1_MAN" >&2; exit 1; }; \
	echo "OK: CSR artifacts and manifests look sane"

# End-to-end CSR test
test_csr: up_389ds init_389ds deps_podman csr_pod verify_csr

down_389ds:
	$(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down,compose_down)

reset_389ds:
	$(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down -v || true,compose_down_purge)
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
	$(call _time,ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod4.yml \
	  -e @test/repl_mesh_vars.yml \
	  test/repl_mesh.yml $(ARGS),repl_mesh)

test_repl_mesh: up_389ds init_389ds_mesh deps_podman seed_389ds repl_pod_mesh verify_389ds
# Fast mesh test: reuse containers, restore golden, run mesh only
test_repl_mesh_fast: up_389ds_fast reset_soft repl_pod_mesh
# Run CSR role for multi-instance scenario on ds-s1
csr_pod_multi:
	ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp \
	ansible-playbook -i test/inventory.compose.pod.yml \
	  -e @test/compose_vars.yml \
	  -e dirsrv_artifact_root_effective=$(PWD)/.ansible/artifacts \
	  test/csr_multi.yml $(ARGS)

# Verify multi-instance CSR artifacts
verify_csr_multi:
	@set -e; \
	ART_DIR_BASE="$(PWD)/.ansible/artifacts/tls"; \
	S1_DIR="$$ART_DIR_BASE/ds-s1"; \
	EXTRA_CSR="$$S1_DIR/ds-s1-extra.csr"; \
	MAN="$$S1_DIR/csr-info.yml"; \
	[ -f "$$EXTRA_CSR" ] || { echo "Missing CSR for extra: $$EXTRA_CSR" >&2; exit 1; }; \
	grep -q "instance: extra" "$$MAN" || { echo "Manifest missing 'extra' instance entry" >&2; exit 1; }; \
	echo "OK: multi-instance CSR artifacts present"

# Aggregate CSR edge tests
test_csr_edges: up_389ds init_389ds deps_podman csr_pod verify_csr csr_pod_multi verify_csr_multi

# Soft reset: restore from golden backups inside containers (fast)
reset_soft:
	@echo "Soft reset: restoring golden backups (if missing, creating once)"
	@for h in ds-s1 ds-s2 ds-c1 ds-c2; do \
	  inst=localhost; bakroot="/var/lib/dirsrv/slapd-$$inst/bak"; bakdir="$$bakroot/golden"; \
	  echo "- $$h: restoring from $$bakdir"; \
	  podman exec $$h bash -lc 'set -e; \
	    if [ ! -d '"$$bakdir"' ]; then \
	      dsctl '"$$inst"' db2bak || true; \
	      last=$$(ls -1dt '"$$bakroot"'/* 2>/dev/null | head -1 || true); \
	      if [ -n "$$last" ]; then rm -rf '"$$bakdir"' && cp -a "$$last" '"$$bakdir"'; fi; \
	    fi; \
	    dsctl '"$$inst"' bak2db '"$$bakdir"' || true'; \
	done

# Hard reset: tear down containers; keep volumes unless PURGE=1
reset_hard:
	@if [ "$(PURGE)" = "1" ]; then \
	  $(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down -v,down_purge); \
	else \
	  $(call _time,$(COMPOSE_CMD) -f compose/podman-compose.389ds.yml down,down); \
	fi

# Setup network only (no-op if exists)
net_only: net

# Quick bench: up -> seed -> mesh -> down (timed)
bench:
	@echo "Running bench: up -> seed -> mesh -> down"
	$(MAKE) up_389ds
	$(MAKE) seed_389ds
	$(MAKE) repl_pod_mesh
	$(MAKE) down_389ds
