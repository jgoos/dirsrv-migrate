#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import time
import re
from datetime import datetime, timezone

try:
    from ansible_collections.directories.ds.plugins.module_utils import dsldap
except Exception:  # pragma: no cover
    import importlib.util
    import sys
    import pathlib
    _p = pathlib.Path(__file__).resolve().parents[3] / 'module_utils' / 'dsldap.py'
    spec = importlib.util.spec_from_file_location('dsldap', str(_p))
    dsldap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = dsldap
    spec.loader.exec_module(dsldap)

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
  stale_seconds: {type: int, default: 300}
  steady_ok_polls: {type: int, default: 3}
  poll_interval: {type: int, default: 10}
  timeout: {type: int, default: 900}
  require_init_success: {type: bool, default: true}
  use_ldapi: {type: bool, default: true}
  ldaps_host: {type: str}
  ldaps_port: {type: int, default: 636}
  connect_timeout: {type: int, default: 5}
  op_timeout: {type: int, default: 30}
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

_CODE_RE = re.compile(r"^(-?\d+)")


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
        r_enabled = (_first(rep.get('attrs', {}).get('nsds5ReplicaEnabled', [])) or '').lower() in ('on', 'true', 'yes', '1')
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
            init_code = int(_CODE_RE.match(init_status).group(1)) if (isinstance(init_status, str) and _CODE_RE.match(init_status)) else None
            upd_code = int(_CODE_RE.match(upd_status).group(1)) if (isinstance(upd_status, str) and _CODE_RE.match(upd_status)) else None
            upd_end = _first(a.get('nsds5replicaLastUpdateEnd'))
            upd_epoch = _gtz_to_epoch(upd_end) if upd_end else None
            upd_age = (now - upd_epoch) if upd_epoch is not None else None
            status = 'unknown'
            obs.append(dict(
                dn=dn,
                update_code=upd_code,
                update_age=upd_age if upd_age is not None else -1,
                init_code=init_code,
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
        stale_seconds=dict(type='int', default=300),
        steady_ok_polls=dict(type='int', default=3),
        poll_interval=dict(type='int', default=10),
        timeout=dict(type='int', default=900),
        require_init_success=dict(type='bool', default=True),
        use_ldapi=dict(type='bool', default=True),
        ldaps_host=dict(type='str'),
        ldaps_port=dict(type='int', default=636),
        connect_timeout=dict(type='int', default=5),
        op_timeout=dict(type='int', default=30),
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
        target_dns = [e.get('dn') for e in ents if e.get('dn')]
    else:
        module.fail_json(msg="Specify 'agreements' list or set 'all: true'")

    deadline = time.monotonic() + int(p['timeout'])
    ok_streak = 0
    last_obs = []
    hints = []

    while time.monotonic() < deadline:
        last_obs = _observations(client, replica_dn, target_dns)
        unhealthy = []
        for o in last_obs:
            if o.get('replica_enabled') is False:
                unhealthy.append((o['dn'], 'replica disabled'))
                continue
            if o.get('update_code') != 0:
                unhealthy.append((o['dn'], 'update_code!=0'))
            age = o.get('update_age')
            if age is None or age < 0 or age > int(p['stale_seconds']):
                unhealthy.append((o['dn'], 'stale'))
            if p.get('require_init_success') and o.get('init_code') not in (None, 0):
                unhealthy.append((o['dn'], 'init_code!=0'))

        if not unhealthy:
            ok_streak += 1
            for o in last_obs:
                o['status'] = 'healthy'
            if ok_streak >= int(p['steady_ok_polls']):
                module.exit_json(changed=False, observations=last_obs)
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

    module.fail_json(msg="Agreements not healthy within timeout", reason="timeout", observations=last_obs, hints=sorted(set(hints)))


if __name__ == '__main__':
    run_module()
