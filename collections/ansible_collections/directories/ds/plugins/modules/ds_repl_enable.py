#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_enable
short_description: Enable 389-DS replication for a suffix/role
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Idempotently ensure replication is enabled for a given suffix and role using C(dsconf).
  - Prefers local instance operations (LDAPI) if possible.
options:
  instance:
    description: 389-DS instance name (e.g. C(slapd-example), C(localhost)).
    type: str
    required: true
  suffix:
    description: Replicated suffix DN (e.g. C(dc=example,dc=com)).
    type: str
    required: true
  role:
    description: Replica role for this node.
    type: str
    choices: [supplier, hub, consumer]
    required: true
  replica_id:
    description: Replica ID required for supplier/hub roles (1..65534).
    type: int
  use_ldapi:
    description: Prefer LDAPI (local instance) operations over remote.
    type: bool
    default: true
  conn_url:
    description: Optional remote LDAP(S) URL (e.g., C(ldap://host:3389)). When provided, C(dm_dn) and C(dm_pw) are used.
    type: str
  dm_dn:
    description: Directory Manager bind DN for remote connections.
    type: str
  dm_pw:
    description: Directory Manager password for remote connections.
    type: str
  op_timeout:
    description: Operation timeout seconds for dsconf calls.
    type: int
    default: 30
'''

EXAMPLES = r'''
- name: Ensure replication enabled (supplier)
  directories.ds.ds_repl_enable:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
    role: supplier
    replica_id: 1
'''

RETURN = r'''
enabled:
  description: Whether replication is enabled for the suffix after the operation.
  returned: always
  type: bool
changed:
  description: Whether changes were applied.
  returned: always
  type: bool
details:
  description: Selected fields from dsconf JSON where available.
  returned: when available
  type: dict
'''


from ansible.module_utils.basic import AnsibleModule
import json
import subprocess

def _run(argv, timeout=30):
    cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return cp


def _dsconf_base(params):
    base = ["dsconf"]
    if params.get('conn_url'):
        if params.get('dm_dn'):
            base += ["-D", params['dm_dn']]
        if params.get('dm_pw'):
            base += ["-w", params['dm_pw']]
        base += [params['conn_url']]
    else:
        # instance-local operations
        base += [params['instance']]
    return base


def _get_state(module, params):
    base = _dsconf_base(params)
    argv = base + ["-j", "replication", "get", "--suffix", params['suffix']]
    try:
        cp = _run(argv, timeout=params.get('op_timeout', 30))
        if cp.returncode != 0:
            return False, None
        text = (cp.stdout.decode('utf-8', errors='ignore') or '').strip()
        if not text:
            return False, None
        data = json.loads(text)
        attrs = data.get('attrs', {}) if isinstance(data, dict) else {}
        # Normalize keys to lowercase because dsconf JSON uses lowercase attribute names
        attrs_lc = { (k.lower() if isinstance(k, str) else k): v for k, v in attrs.items() } if isinstance(attrs, dict) else {}
        # Consider enabled when nsds5replicatype exists
        enabled = 'nsds5replicatype' in attrs_lc and bool(attrs_lc.get('nsds5replicatype'))
        # Return a compact details map
        details = dict(
            replica_type=attrs_lc.get('nsds5replicatype', [None])[0] if isinstance(attrs_lc.get('nsds5replicatype'), list) else attrs_lc.get('nsds5replicatype'),
            replica_id=attrs_lc.get('nsds5replicaid', [None])[0] if isinstance(attrs_lc.get('nsds5replicaid'), list) else attrs_lc.get('nsds5replicaid'),
        )
        return enabled, details
    except Exception:
        return False, None


def run_module():
    args_spec = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        role=dict(type='str', required=True, choices=['supplier', 'hub', 'consumer']),
        replica_id=dict(type='int', required=False),
        use_ldapi=dict(type='bool', default=True),
        conn_url=dict(type='str', required=False),
        dm_dn=dict(type='str', required=False),
        dm_pw=dict(type='str', required=False, no_log=True),
        op_timeout=dict(type='int', default=30),
    )

    module = AnsibleModule(argument_spec=args_spec, supports_check_mode=True)
    p = module.params

    # Pre-check
    enabled, details = _get_state(module, p)
    if enabled:
        module.exit_json(changed=False, enabled=True, details=details)

    if module.check_mode:
        module.exit_json(changed=True, enabled=True)

    base = _dsconf_base(p)
    argv = base + [
        "replication", "enable",
        "--suffix", p['suffix'],
        "--role", p['role'],
    ]
    if p['role'] in ('supplier', 'hub') and p.get('replica_id'):
        argv += ["--replica-id", str(p['replica_id'])]

    cp = _run(argv, timeout=p.get('op_timeout', 30))
    if cp.returncode != 0:
        stderr = (cp.stderr.decode(errors='ignore') or '').lower()
        # Idempotence guard: tolerate already-enabled state
        if 'already enabled' in stderr or 'replication is already enabled' in stderr:
            module.exit_json(changed=False, enabled=True)
        module.fail_json(msg="dsconf replication enable failed", rc=cp.returncode, stderr=cp.stderr.decode(errors='ignore'))

    # Post-check
    enabled2, details2 = _get_state(module, p)
    if not enabled2:
        module.fail_json(msg="Replication not enabled after dsconf run")

    module.exit_json(changed=True, enabled=True, details=details2)


if __name__ == '__main__':
    run_module()
