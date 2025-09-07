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
'''

from ansible.module_utils.basic import AnsibleModule
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
            'nsds5ReplicaHost', 'nsds5ReplicaPort', 'nsds5ReplicaBindDN',
            'nsds5replicaLastInitStatus', 'nsds5replicaLastInitEnd',
            'nsds5replicaLastUpdateStatus', 'nsds5replicaLastUpdateEnd',
        ])
    except Exception:
        entries = []

    agmts = []
    for e in entries:
        a = e.get('attrs', {})
        init_status = _first(a.get('nsds5replicaLastInitStatus'))
        upd_status = _first(a.get('nsds5replicaLastUpdateStatus'))
        init_code = int(_CODE_RE.match(init_status).group(1)) if (isinstance(init_status, str) and _CODE_RE.match(init_status)) else None
        upd_code = int(_CODE_RE.match(upd_status).group(1)) if (isinstance(upd_status, str) and _CODE_RE.match(upd_status)) else None
        init_end = _first(a.get('nsds5replicaLastInitEnd'))
        upd_end = _first(a.get('nsds5replicaLastUpdateEnd'))
        agmts.append(dict(
            dn=e.get('dn', ''),
            host=_first(a.get('nsds5ReplicaHost')),
            port=(int(_first(a.get('nsds5ReplicaPort'))) if _first(a.get('nsds5ReplicaPort')) else None),
            bind_dn=_first(a.get('nsds5ReplicaBindDN')),
            enabled=bool(rep_enabled),
            last_init_status=init_status,
            last_init_code=init_code,
            last_init_end=init_end,
            last_init_epoch=_gtz_to_epoch(init_end) if init_end else None,
            last_update_status=upd_status,
            last_update_code=upd_code,
            last_update_end=upd_end,
            last_update_epoch=_gtz_to_epoch(upd_end) if upd_end else None,
        ))

    module.exit_json(changed=False, replica=result_replica, agreements=agmts)


if __name__ == '__main__':
    run_module()
