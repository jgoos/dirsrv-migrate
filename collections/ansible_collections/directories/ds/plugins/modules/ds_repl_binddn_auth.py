#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_binddn_auth
short_description: Ensure inbound replication bind DN authorization on a replica
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Adds or removes a DN from C(nsds5ReplicaBindDN) on the replica entry for a suffix.
options:
  instance: {description: Instance name, type: str, required: true}
  suffix:   {description: Suffix DN, type: str, required: true}
  bind_dn:  {description: Bind DN to allow/deny, type: str, required: true}
  state:    {description: Target state, type: str, choices: [present, absent], default: present}
  use_ldapi: {description: Prefer LDAPI (EXTERNAL) for local ops, type: bool, default: true}
  ldaps_host: {description: Fallback host for LDAPS ops, type: str}
  ldaps_port: {description: LDAPS port, type: int, default: 636}
  dm_dn: {description: Directory Manager DN for remote ops, type: str}
  dm_pw: {description: Directory Manager password for remote ops, type: str}
  connect_timeout: {description: Connect timeout seconds, type: int, default: 5}
  op_timeout: {description: Operation timeout seconds, type: int, default: 30}
'''

EXAMPLES = r'''
- name: Allow inbound bind DN on this replica
  directories.ds.ds_repl_binddn_auth:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
    bind_dn: "cn=replication manager,cn=config"
    state: present
'''

RETURN = r'''
changed:
  description: Whether a change was made
  returned: always
  type: bool
'''


from ansible.module_utils.basic import AnsibleModule

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

def _escape_suffix_value(suffix_dn):
    return suffix_dn.replace('=', '\\3D').replace(',', '\\2C')


def _first(vals):
    if isinstance(vals, list) and vals:
        return vals[0]
    return None


def run_module():
    args = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        bind_dn=dict(type='str', required=True),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        use_ldapi=dict(type='bool', default=True),
        ldaps_host=dict(type='str'),
        ldaps_port=dict(type='int', default=636),
        dm_dn=dict(type='str'),
        dm_pw=dict(type='str', no_log=True),
        connect_timeout=dict(type='int', default=5),
        op_timeout=dict(type='int', default=30),
    )

    module = AnsibleModule(argument_spec=args, supports_check_mode=True)
    p = module.params

    conn = dsldap.LdapConnParams(
        instance=p['instance'],
        use_ldapi=p.get('use_ldapi', True),
        ldaps_host=p.get('ldaps_host'),
        ldaps_port=p.get('ldaps_port') or 636,
        bind_method='simple' if p.get('ldaps_host') else 'simple',
        bind_dn=p.get('dm_dn'),
        bind_pw=p.get('dm_pw'),
        connect_timeout=p.get('connect_timeout') or 5,
        op_timeout=p.get('op_timeout') or 30,
    )
    client = dsldap.DsLdap(conn)

    esc_suffix = _escape_suffix_value(p['suffix'])
    replica_dn = f"cn=replica,cn={esc_suffix},cn=mapping tree,cn=config"
    cur = {}
    try:
        rep = client.search_one(replica_dn, 'base', '(objectClass=*)', ['nsds5ReplicaBindDN'])
        cur = rep.get('attrs', {})
    except Exception as e:
        module.fail_json(msg=f"Replica entry missing for suffix {p['suffix']}", hint=str(e))

    cur_vals = [v.lower() for v in cur.get('nsds5ReplicaBindDN', [])]
    target = p['bind_dn'].lower()
    changed = False

    if p['state'] == 'present':
        if target not in cur_vals:
            if not module.check_mode:
                try:
                    client.modify(replica_dn, [('add', 'nsds5ReplicaBindDN', p['bind_dn'])])
                except Exception as e:
                    module.fail_json(msg='Failed adding bind DN to replica', hint=str(e))
            changed = True
        module.exit_json(changed=changed)
    else:
        # absent
        if target in cur_vals:
            if not module.check_mode:
                try:
                    client.modify(replica_dn, [('delete', 'nsds5ReplicaBindDN', p['bind_dn'])])
                except Exception as e:
                    module.fail_json(msg='Failed removing bind DN from replica', hint=str(e))
            changed = True
        module.exit_json(changed=changed)


def main():
    run_module()


if __name__ == '__main__':
    main()
