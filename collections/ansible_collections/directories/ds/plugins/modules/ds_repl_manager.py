#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_manager
short_description: Ensure replication manager entry exists and password is set
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Ensures C(cn=replication manager,cn=config) exists and optionally sets C(userPassword).
  - Tries to verify password via simple bind over LDAPI before changing.
options:
  instance: {description: Instance name, type: str, required: true}
  name: {description: Manager common name, type: str, default: replication manager}
  ensure: {description: Target state, type: str, choices: [present, absent], default: present}
  password: {description: Desired password (when present), type: str}
  verify: {description: Attempt to verify password via bind before changing, type: bool, default: true}
  op_timeout: {description: Operation timeout seconds, type: int, default: 30}
'''

EXAMPLES = r'''
- name: Ensure replication manager exists and password set
  directories.ds.ds_repl_manager:
    instance: "slapd-example"
    password: "{{ vault_repl_password }}"
'''

RETURN = r'''
changed:
  description: Whether a change occurred
  returned: always
  type: bool
dn:
  description: Manager DN
  returned: always
  type: str
'''


from ansible.module_utils.basic import AnsibleModule
import subprocess

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

def _ldapwhoami_try(url: str, dn: str, pw: str, timeout: int) -> bool:
    try:
        cp = subprocess.run([
            'ldapwhoami', '-x', '-D', dn, '-w', pw, '-H', url
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return cp.returncode == 0
    except Exception:
        return False


def _candidate_ldapi_urls(instance: str):
    return [
        dsldap.build_ldapi_url(instance, base_dir='/run'),
        dsldap.build_ldapi_url(instance, base_dir='/data/run'),
    ]


def run_module():
    args = dict(
        instance=dict(type='str', required=True),
        name=dict(type='str', default='replication manager'),
        ensure=dict(type='str', choices=['present', 'absent'], default='present'),
        password=dict(type='str', no_log=True),
        verify=dict(type='bool', default=True),
        op_timeout=dict(type='int', default=30),
    )

    module = AnsibleModule(argument_spec=args, supports_check_mode=True)
    p = module.params
    dn = f"cn={p['name']},cn=config"

    conn = dsldap.LdapConnParams(instance=p['instance'], use_ldapi=True)
    client = dsldap.DsLdap(conn)

    # Existence check
    exists = False
    try:
        e = client.search_one(dn, 'base', '(objectClass=*)', ['cn'])
        exists = bool(e and e.get('dn'))
    except Exception:
        exists = False

    if p['ensure'] == 'absent':
        if exists:
            if not module.check_mode:
                client.delete(dn)
            module.exit_json(changed=True, dn=dn)
        module.exit_json(changed=False, dn=dn)

    # ensure present
    changed = False
    if not exists:
        if module.check_mode:
            module.exit_json(changed=True, dn=dn)
        add_attrs = {
            'objectClass': ['top', 'nsSimpleSecurityObject'],
            'cn': p['name'],
        }
        if p.get('password'):
            add_attrs['userPassword'] = p['password']
        client.add(dn, add_attrs)
        changed = True
        module.exit_json(changed=changed, dn=dn)

    # present: maybe set password
    if p.get('password'):
        if p.get('verify', True):
            ok = False
            for url in _candidate_ldapi_urls(p['instance']):
                if _ldapwhoami_try(url, dn, p['password'], p.get('op_timeout', 30)):
                    ok = True
                    break
            if ok:
                module.exit_json(changed=False, dn=dn)
        if not module.check_mode:
            # replace without trying to compare hashed value
            client.modify(dn, [('replace', 'userPassword', p['password'])])
        changed = True
    module.exit_json(changed=changed, dn=dn)


def main():
    run_module()


if __name__ == '__main__':
    main()
