#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_info
short_description: Read 389-DS replica and agreement status
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Reads replica attributes and replication agreements under a suffix.
  - Prefer LDAPI with SASL/EXTERNAL; allow LDAPS fallback.
notes:
  - This is a read-only module; it always returns C(changed=false).
options:
  instance:
    description: 389-DS instance name (e.g. C(slapd-example), C(localhost)).
    type: str
    required: true
  suffix:
    description: Replicated suffix DN (e.g. C(dc=example,dc=com)).
    type: str
    required: true
  use_ldapi:
    description: Prefer ldapi + SASL/EXTERNAL.
    type: bool
    default: true
  ldaps_host:
    description: Hostname for LDAPS fallback.
    type: str
  ldaps_port:
    description: Port for LDAPS fallback.
    type: int
    default: 636
  bind_method:
    description: Remote bind method when using LDAPS.
    type: str
    choices: [simple, sslclientauth]
    default: simple
  bind_dn:
    description: Bind DN for SIMPLE bind.
    type: str
  bind_pw:
    description: Password for SIMPLE bind.
    type: str
  tls_ca:
    description: CA file path when validating LDAPS.
    type: path
  tls_client_cert:
    description: Client certificate (when using sslclientauth).
    type: path
  tls_client_key:
    description: Client private key (when using sslclientauth).
    type: path
  connect_timeout:
    description: Connect timeout seconds.
    type: int
    default: 5
  op_timeout:
    description: Operation timeout seconds.
    type: int
    default: 30
  agreements:
    description: Optional list of agreement names or DNs to include (others filtered out).
    type: list
    elements: str
    required: false
  stale_seconds:
    description: Consider last update stale if older than this many seconds when summarizing.
    type: int
    default: 120
  monitor:
    description: Best-effort sampling via `dsconf -j replication monitor` to collect backlog per agreement.
    type: bool
    default: true
  monitor_timeout:
    description: Timeout seconds for the monitor command.
    type: int
    default: 10
'''

EXAMPLES = r'''
- name: Collect replication info
  directories.ds.ds_repl_info:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
  register: info
'''

RETURN = r'''
replica:
  description: Replica entry summary.
  returned: always
  type: dict
  sample:
    dn: "cn=replica,cn=dc=example,dc=com,cn=mapping tree,cn=config"
    enabled: true
    ruv: "{replicageneration:...}"
agreements:
  description: List of agreements under the replica.
  returned: always
  type: list
  elements: dict
  sample:
    - dn: "cn=agmt to c1:636,cn=replica,cn=dc=example,dc=com,cn=mapping tree,cn=config"
      host: c1.example.com
      port: 636
      bind_dn: "uid=repl,cn=config"
      enabled: true
      last_init_status: "0 Total init succeeded"
      last_init_code: 0
      last_init_end: "20250907091531Z"
      last_init_epoch: 1757246131
      last_update_status: "0 Update OK"
      last_update_code: 0
      last_update_end: "20250907091740Z"
      last_update_epoch: 1757246260
summary:
  description: High-level health indicators derived from latest snapshot.
  returned: always
  type: dict
  sample:
    configured: true
    working: true
    finished: false
    problems: []
'''

from ansible.module_utils.basic import AnsibleModule
import re
from datetime import datetime, timezone
import json
import subprocess
from typing import Any, Dict, Optional

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


def _aget(attrs, name):
    """Case-insensitive attribute getter from parsed LDIF attrs dict."""
    if not isinstance(attrs, dict):
        return None
    lname = name.lower()
    for k, v in attrs.items():
        if isinstance(k, str) and k.lower() == lname:
            return v
    return None


def run_module():
    args_spec = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        use_ldapi=dict(type='bool', default=True),
        ldaps_host=dict(type='str', required=False),
        ldaps_port=dict(type='int', default=636),
        bind_method=dict(type='str', choices=['simple', 'sslclientauth'], default='simple'),
        bind_dn=dict(type='str', required=False),
        bind_pw=dict(type='str', required=False, no_log=True),
        tls_ca=dict(type='path', required=False),
        tls_client_cert=dict(type='path', required=False),
        tls_client_key=dict(type='path', required=False),
        connect_timeout=dict(type='int', default=5),
        op_timeout=dict(type='int', default=30),
        agreements=dict(type='list', elements='str', required=False),
        stale_seconds=dict(type='int', default=120),
        monitor=dict(type='bool', default=True),
        monitor_timeout=dict(type='int', default=10),
    )

    module = AnsibleModule(argument_spec=args_spec, supports_check_mode=True)

    p = module.params
    conn = dsldap.LdapConnParams(
        instance=p['instance'],
        use_ldapi=p['use_ldapi'],
        ldaps_host=p.get('ldaps_host'),
        ldaps_port=p.get('ldaps_port'),
        bind_method=p.get('bind_method'),
        bind_dn=p.get('bind_dn'),
        bind_pw=p.get('bind_pw'),
        tls_ca=p.get('tls_ca'),
        tls_client_cert=p.get('tls_client_cert'),
        tls_client_key=p.get('tls_client_key'),
        connect_timeout=p.get('connect_timeout'),
        op_timeout=p.get('op_timeout'),
    )
    client = dsldap.DsLdap(conn)

    esc_suffix = _escape_suffix_value(p['suffix'])
    replica_dn = f"cn=replica,cn={esc_suffix},cn=mapping tree,cn=config"

    try:
        rep = client.search_one(replica_dn, 'base', '(objectClass=*)', ['nsds5ReplicaEnabled', 'nsds50ruv'])
    except dsldap.DsLdapError as e:
        module.fail_json(msg=f"Replica entry missing for suffix {p['suffix']}", hint=getattr(e, 'hint', None))

    attrs = rep.get('attrs', {})
    rep_enabled = None
    if 'nsds5ReplicaEnabled' in attrs:
        rep_enabled = (_first(attrs['nsds5ReplicaEnabled']) or '').lower() in ('on', 'true', 'yes', '1')
    result_replica = dict(
        dn=replica_dn,
        enabled=rep_enabled,
        ruv=_first(attrs.get('nsds50ruv')),
    )

    try:
        entries = client.search(replica_dn, 'one', '(objectClass=nsDS5ReplicationAgreement)', [
            'cn',
            'nsds5ReplicaHost', 'nsds5ReplicaPort', 'nsds5ReplicaBindDN', 'nsds5ReplicaEnabled',
            'nsds5replicaLastInitStatus', 'nsds5replicaLastInitEnd', 'nsds5replicaLastInitStatusJSON',
            'nsds5replicaLastUpdateStatus', 'nsds5replicaLastUpdateStart', 'nsds5replicaLastUpdateEnd', 'nsds5replicaLastUpdateStatusJSON',
            'nsds5ReplicaUpdateInProgress'
        ])
    except Exception:
        entries = []

    # Optional filter by agreement names or DNs
    filters = set(p.get('agreements') or [])

    # Best-effort backlog sampling via dsconf -j replication monitor (LDAPI only unless bind provided)
    def _dsconf_monitor() -> Optional[Dict[str, Any]]:
        if not p.get('monitor'):
            return None
        argv = None
        # Try LDAPI first using the instance socket; prefer /run then /data/run
        try_urls = [
            dsldap.build_ldapi_url(p['instance'], "/run"),
            dsldap.build_ldapi_url(p['instance'], "/data/run"),
        ]
        for url in try_urls:
            argv = ["dsconf", "-j", url, "replication", "monitor", "--suffix", p['suffix']]
            try:
                cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(p.get('monitor_timeout', 10)))
                if cp.returncode == 0 and cp.stdout:
                    return json.loads(cp.stdout)
            except Exception:
                continue
        # Fallback to LDAPS if host + bind provided
        if p.get('ldaps_host') and p.get('bind_dn') and p.get('bind_pw'):
            url = f"ldaps://{p['ldaps_host']}:{p.get('ldaps_port', 636)}"
            argv = ["dsconf", "-j", "-H", url, "ldap", "-D", p['bind_dn'], "-w", p['bind_pw'], "replication", "monitor", "--suffix", p['suffix']]
            try:
                cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(p.get('monitor_timeout', 10)))
                if cp.returncode == 0 and cp.stdout:
                    return json.loads(cp.stdout)
            except Exception:
                pass
        return None

    mon_json = _dsconf_monitor()

    def _extract_backlogs(obj) -> Dict[str, int]:
        out: Dict[str, int] = {}
        def _walk(x):
            if isinstance(x, dict):
                nm = None
                if 'name' in x and isinstance(x['name'], str):
                    nm = x['name']
                # any key containing 'backlog'
                bl = None
                for k, v in x.items():
                    if isinstance(k, str) and 'backlog' in k.lower():
                        try:
                            bl = int(v)
                        except Exception:
                            pass
                if nm and isinstance(bl, int):
                    out[nm] = bl
                for v in x.values():
                    _walk(v)
            elif isinstance(x, list):
                for it in x:
                    _walk(it)
        _walk(obj)
        return out

    backlog_by_name: Dict[str, int] = _extract_backlogs(mon_json) if mon_json else {}

    agmts = []
    for e in entries:
        a = e.get('attrs', {})
        cn_val = _first(_aget(a, 'cn'))
        dn_val = e.get('dn', '')
        if filters:
            # Accept match if CN matches any token or DN matches any token
            matched = any(
                (
                    (cn_val and f"{f}".lower() in cn_val.lower()) or
                    (dn_val and f"{f}".lower() in dn_val.lower())
                ) for f in filters
            )
            if not matched:
                continue
        init_status = _first(_aget(a, 'nsds5replicaLastInitStatus'))
        upd_status = _first(_aget(a, 'nsds5replicaLastUpdateStatus'))
        init_match = _CODE_RE.match(init_status) if isinstance(init_status, str) else None
        upd_match = _CODE_RE.match(upd_status) if isinstance(upd_status, str) else None
        init_code = int(init_match.group(1)) if init_match else None
        upd_code = int(upd_match.group(1)) if upd_match else None
        init_end = _first(_aget(a, 'nsds5replicaLastInitEnd'))
        upd_end = _first(_aget(a, 'nsds5replicaLastUpdateEnd'))
        upd_start = _first(_aget(a, 'nsds5replicaLastUpdateStart'))
        # Busy flag (agreement-scoped)
        busy_raw = _first(_aget(a, 'nsds5ReplicaUpdateInProgress'))
        busy = None
        if isinstance(busy_raw, str):
            busy = busy_raw.strip().lower() in ('true', 'yes', 'on', '1')
        # JSON init status hints (if present)
        init_json_raw = _first(_aget(a, 'nsds5replicaLastInitStatusJSON'))
        init_json = None
        try:
            init_json = json.loads(init_json_raw) if init_json_raw else None
        except Exception:
            init_json = None
        # Derive init_status label
        init_status_label = None
        if isinstance(init_json, dict):
            if isinstance(init_json.get('initialized'), bool):
                init_status_label = 'Done' if init_json.get('initialized') else 'Unknown'
            elif isinstance(init_json.get('state'), str):
                # e.g., green/unknown
                st = init_json.get('state').lower()
                init_status_label = 'Done' if st in ('green', 'succeeded', 'success') else st.title()
        if not init_status_label and isinstance(init_status, str):
            if init_code == 0:
                init_status_label = 'Done'
            elif init_status:
                init_status_label = 'Unknown'
        # Agreement enabled status
        # Check agreement's own enabled status
        agmt_enabled = None
        vals_en = _aget(a, 'nsds5ReplicaEnabled')
        if vals_en is not None:
            agmt_enabled = (_first(vals_en) or '').lower() in ('on', 'true', 'yes', '1')
        agmts.append(dict(
            dn=dn_val,
            name=cn_val,
            host=_first(_aget(a, 'nsds5ReplicaHost')),
            port=(int(_first(_aget(a, 'nsds5ReplicaPort'))) if _first(_aget(a, 'nsds5ReplicaPort')) else None),
            bind_dn=_first(_aget(a, 'nsds5ReplicaBindDN')),
            enabled=agmt_enabled,
            busy=busy,
            init_status=init_status_label,
            last_init_status=init_status,
            last_init_code=init_code,
            last_init_end=init_end,
            last_init_epoch=_gtz_to_epoch(init_end) if init_end else None,
            last_update_status=upd_status,
            last_update_code=upd_code,
            last_update_start=upd_start,
            last_update_start_epoch=_gtz_to_epoch(upd_start) if upd_start else None,
            last_update_end=upd_end,
            last_update_epoch=_gtz_to_epoch(upd_end) if upd_end else None,
            backlog=(backlog_by_name.get(cn_val) if cn_val and cn_val in backlog_by_name else None),
        ))

    # Compute summary
    problems = []
    configured = any((a.get('enabled') is True) for a in agmts)
    if not configured:
        problems.append('No enabled agreements for suffix')
    # Working: any busy, or any recent successful update
    now = int(datetime.now(tz=timezone.utc).timestamp())
    stale = int(p.get('stale_seconds') or 120)
    recent_ok = any((
        (a.get('last_update_code') == 0) and (a.get('last_update_epoch') is not None) and ((now - int(a['last_update_epoch'])) <= stale)
    ) for a in agmts)
    any_busy = any((a.get('busy') is True) for a in agmts)
    working = any_busy or recent_ok
    if not working and agmts:
        # Provide hints per agreement
        for a in agmts:
            if a.get('last_update_code') not in (None, 0):
                problems.append(f"{(a.get('name') or a.get('dn','(agmt)')).split(',')[0]}: update failed (code {a.get('last_update_code')})")
            elif a.get('last_update_epoch') is None:
                problems.append(f"{(a.get('name') or a.get('dn','(agmt)')).split(',')[0]}: no update timestamp observed")
            else:
                age = now - int(a['last_update_epoch'])
                if age > stale:
                    problems.append(f"{(a.get('name') or a.get('dn','(agmt)')).split(',')[0]}: last update stale >{stale}s")
    # Finished: no busy, successful init (if observed), and recent_ok for all
    none_busy = all(((a.get('busy') is False) or (a.get('busy') is None)) for a in agmts) if agmts else False
    init_ok = all((a.get('last_init_code') in (None, 0) or (a.get('init_status') in ('Done', 'Completed'))) for a in agmts) if agmts else False
    all_recent_ok = all((
        (a.get('last_update_code') == 0) and (a.get('last_update_epoch') is not None) and ((now - int(a['last_update_epoch'])) <= stale)
    ) for a in agmts) if agmts else False
    # If backlog is exposed, also require 0 backlog across agreements (only for those with a value)
    backlog_ok = all(((a.get('backlog') is None) or (int(a.get('backlog')) == 0)) for a in agmts) if agmts else False
    finished = bool(none_busy and init_ok and all_recent_ok and backlog_ok)

    summary = dict(configured=bool(configured), working=bool(working), finished=bool(finished), problems=sorted(set(problems)))

    module.exit_json(changed=False, replica=result_replica, agreements=agmts, summary=summary)


if __name__ == '__main__':
    run_module()
