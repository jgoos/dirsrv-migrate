#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_wait
short_description: Wait until replication agreements are healthy
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Polls until agreement(s) on a supplier are healthy within staleness and timeout windows.
  - Module owns the loop; playbooks should not wrap with retries.
options:
  instance: {type: str, required: true, description: Instance name}
  suffix:   {type: str, required: true, description: Suffix DN}
  agreements:
    type: list
    elements: str
    required: false
    description: Explicit agreement DNs to wait on.
  all:
    type: bool
    default: false
    description: If true (and agreements unset) wait on all under replica.
  stale_seconds: {type: int, default: 300, description: Maximum age in seconds for last successful update}
  steady_ok_polls: {type: int, default: 3, description: Consecutive healthy polls required before success}
  poll_interval: {type: int, default: 3, description: Seconds to wait between polls}
  timeout: {type: int, default: 180, description: Maximum time to wait for healthy agreements}
  require_init_success: {type: bool, default: true, description: Require last init to have succeeded (code 0)}
  use_ldapi: {type: bool, default: true, description: Prefer LDAPI (SASL/EXTERNAL) for local instance}
  ldaps_host: {type: str, description: LDAPS fallback host when LDAPI is unavailable}
  ldaps_port: {type: int, default: 636, description: LDAPS fallback port}
  connect_timeout: {type: int, default: 5, description: LDAP connect timeout seconds}
  op_timeout: {type: int, default: 30, description: LDAP operation timeout seconds}
  debug: {type: bool, default: false, description: Emit periodic progress warnings}
  log_every: {type: int, default: 5, description: Emit a progress warning every N cycles when debug=true}
'''

EXAMPLES = r'''
- name: Wait until all agreements are healthy
  directories.ds.ds_repl_wait:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
    all: true
    stale_seconds: 300
    steady_ok_polls: 3
    poll_interval: 10
    timeout: 900
'''

RETURN = r'''
observations:
  description: Last observed per-agreement snapshot.
  returned: always
  type: list
  elements: dict
  sample:
    - dn: "cn=agmt to c1:636,cn=replica,..."
      update_code: 0
      update_age: 12
      init_code: 0
      status: "unknown|healthy|stale|failed"
'''

from ansible.module_utils.basic import AnsibleModule
import time
import re
from datetime import datetime, timezone

import importlib.util
import sys
import pathlib

# Prefer local collection-relative module_utils to ensure we use sources shipped with this module (debug/dev friendly)
_p = pathlib.Path(__file__).resolve().parents[3] / 'module_utils' / 'dsldap.py'
if _p.exists():
    spec = importlib.util.spec_from_file_location('dsldap', str(_p))
    dsldap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = dsldap
    spec.loader.exec_module(dsldap)
else:  # Fallback to standard import path
    from ansible_collections.directories.ds.plugins.module_utils import dsldap

_CODE_RE = re.compile(r"(-?\d+)")


def _gtz_to_epoch(value):
    if not isinstance(value, str):
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.\d+)?Z$", value)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _escape_suffix_value(suffix_dn):
    return suffix_dn.replace('=', '\\3D').replace(',', '\\2C')


def _first(vals):
    if isinstance(vals, list) and vals:
        return vals[0]
    return None


def _observations(client, replica_dn, agmt_dns):
    now = int(time.time())
    obs = []
    try:
        rep = client.search_one(replica_dn, 'base', '(objectClass=*)', ['nsds5ReplicaEnabled'])
        vals = rep.get('attrs', {}).get('nsds5ReplicaEnabled')
        if vals:
            r_enabled = (vals[0] or '').lower() in ('on', 'true', 'yes', '1')
        else:
            r_enabled = None
    except Exception:
        r_enabled = None
    for dn in agmt_dns:
        try:
            e = client.search_one(dn, 'base', '(objectClass=*)', [
                'nsds5replicaLastInitStatus', 'nsds5replicaLastInitEnd',
                'nsds5replicaLastUpdateStatus', 'nsds5replicaLastUpdateEnd',
            ])
            a = e.get('attrs', {})
            init_status = _first(a.get('nsds5replicaLastInitStatus'))
            upd_status = _first(a.get('nsds5replicaLastUpdateStatus'))
            # Parse first integer anywhere in the status strings if present
            m_i = _CODE_RE.search(init_status) if isinstance(init_status, str) else None
            m_u = _CODE_RE.search(upd_status) if isinstance(upd_status, str) else None
            init_code = int(m_i.group(1)) if m_i else None
            upd_code = int(m_u.group(1)) if m_u else None
            upd_end = _first(a.get('nsds5replicaLastUpdateEnd'))
            upd_epoch = _gtz_to_epoch(upd_end) if upd_end else None
            upd_age = (now - upd_epoch) if upd_epoch is not None else None
            status = 'unknown'
            obs.append(dict(
                dn=dn,
                update_code=upd_code,
                update_age=upd_age if upd_age is not None else -1,
                init_code=init_code,
                update_status=upd_status,
                init_status=init_status,
                replica_enabled=r_enabled,
                status=status,
            ))
        except Exception:
            obs.append(dict(dn=dn, update_code=None, update_age=None, init_code=None, replica_enabled=r_enabled, status='missing'))
    return obs


def run_module():
    args = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        agreements=dict(type='list', elements='str', required=False),
        all=dict(type='bool', default=False),
        stale_seconds=dict(type='int', default=60),
        steady_ok_polls=dict(type='int', default=2),
        poll_interval=dict(type='int', default=3),
        timeout=dict(type='int', default=180),
        require_init_success=dict(type='bool', default=True),
        use_ldapi=dict(type='bool', default=True),
        ldaps_host=dict(type='str'),
        ldaps_port=dict(type='int', default=636),
        connect_timeout=dict(type='int', default=5),
        op_timeout=dict(type='int', default=30),
        debug=dict(type='bool', default=False),
        log_every=dict(type='int', default=5),
    )

    module = AnsibleModule(argument_spec=args, supports_check_mode=True)

    p = module.params
    conn = dsldap.LdapConnParams(
        instance=p['instance'],
        use_ldapi=p['use_ldapi'],
        ldaps_host=p.get('ldaps_host'),
        ldaps_port=p.get('ldaps_port'),
        connect_timeout=p.get('connect_timeout'),
        op_timeout=p.get('op_timeout'),
    )
    client = dsldap.DsLdap(conn)

    esc_suffix = _escape_suffix_value(p['suffix'])
    replica_dn = f"cn=replica,cn={esc_suffix},cn=mapping tree,cn=config"

    target_dns = []
    if p.get('agreements'):
        target_dns = list(p['agreements'])
    elif p.get('all'):
        try:
            ents = client.search(replica_dn, 'one', '(objectClass=nsDS5ReplicationAgreement)', ['cn'])
        except Exception:
            ents = []
        # Build DNs from cn values to avoid any LDIF wrapping issues on 'dn:'
        def _first(vals):
            return vals[0] if isinstance(vals, list) and vals else None
        target_dns = []
        for e in ents:
            cnv = _first(e.get('attrs', {}).get('cn'))
            if cnv:
                target_dns.append(f"cn={cnv},{replica_dn}")
    else:
        module.fail_json(msg="Specify 'agreements' list or set 'all: true'")

    # Visibility: where dsldap came from and what we will watch
    if p.get('debug'):
        try:
            module.warn(f"ds_repl_wait: using dsldap from {getattr(dsldap, '__file__', 'unknown')}")
        except Exception:
            pass
        module.warn(f"ds_repl_wait: discovered agreements: {', '.join(target_dns) if target_dns else '(none)'}")

    start_ts = time.monotonic()
    deadline = start_ts + int(p['timeout'])
    ok_streak = 0
    cycle = 0
    last_obs = []
    hints = []
    progress = []

    while time.monotonic() < deadline:
        cycle += 1
        last_obs = _observations(client, replica_dn, target_dns)
        unhealthy = []
        for o in last_obs:
            if o.get('replica_enabled') is False:
                unhealthy.append((o['dn'], 'replica disabled'))
                continue
            # Treat None as unknown (not unhealthy). Accept success code or success keywords.
            uc = o.get('update_code')
            us = (o.get('update_status') or '').lower()
            # More lenient success detection - accept 0, success keywords, or recent updates
            is_success = (uc == 0 or ('succeed' in us) or ('acquired successfully' in us) or ('incremental update succeeded' in us))
            age = o.get('update_age')
            
            # Only consider it unhealthy if we have a clear failure AND it's stale
            if not is_success and uc is not None and uc != 0:
                # Only fail if it's also stale (old failure)
                if age is None or age < 0 or age > int(p['stale_seconds']):
                    unhealthy.append((o['dn'], 'update_code!=0'))
            elif not is_success and uc is None:
                # Unknown status - only fail if stale
                if age is None or age < 0 or age > int(p['stale_seconds']):
                    unhealthy.append((o['dn'], 'stale'))
            if p.get('require_init_success') and o.get('init_code') not in (None, 0):
                unhealthy.append((o['dn'], 'init_code!=0'))

        # progress snapshot
        elapsed = int(time.monotonic() - start_ts)
        if p.get('debug') and p.get('log_every', 5) > 0 and (cycle % int(p['log_every']) == 0 or cycle == 1):
            sample = ', '.join([f"{o['dn'].split(',')[0]}:{o.get('status')} age={o.get('update_age')} code={o.get('update_code')}" for o in last_obs][:3])
            module.warn(f"ds_repl_wait: cycle={cycle} elapsed={elapsed}s unhealthy={len(unhealthy)} ok_streak={ok_streak} sample=[{sample}]")
        elif not p.get('debug') and cycle % 10 == 0:  # Less frequent logging when not in debug mode
            module.warn(f"ds_repl_wait: cycle={cycle} elapsed={elapsed}s unhealthy={len(unhealthy)} ok_streak={ok_streak}")
        if len(progress) < 50:
            progress.append(dict(cycle=cycle, elapsed_s=elapsed, unhealthy=len(unhealthy)))

        if not unhealthy:
            ok_streak += 1
            for o in last_obs:
                o['status'] = 'healthy'
            if ok_streak >= int(p['steady_ok_polls']):
                module.exit_json(changed=False, observations=last_obs, cycles=cycle, elapsed_s=elapsed, agreements=len(target_dns), progress=progress)
        else:
            ok_streak = 0
            for dn, reason in unhealthy:
                if reason == 'stale':
                    hints.append(f"{dn}: Last update stale >{p['stale_seconds']}s")
                elif reason == 'update_code!=0':
                    hints.append(f"{dn}: Replication update failed (code != 0)")
                elif reason == 'init_code!=0':
                    hints.append(f"{dn}: Last init failed (code != 0)")
                elif reason == 'replica disabled':
                    hints.append(f"{dn}: Replica disabled")
        time.sleep(int(p['poll_interval']))

    elapsed_final = int(time.monotonic() - start_ts)
    module.fail_json(msg="Agreements not healthy within timeout", reason="timeout", observations=last_obs, hints=sorted(set(hints)), cycles=cycle, elapsed_s=elapsed_final, agreements=len(target_dns), progress=progress)


if __name__ == '__main__':
    run_module()
