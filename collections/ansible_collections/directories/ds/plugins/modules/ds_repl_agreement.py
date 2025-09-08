#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_agreement
short_description: Ensure a 389-DS replication agreement is present/absent
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Idempotently create, update, or remove a replication agreement under a suffix.
  - This stub provides argument validation surface and will be wired to LDAP ops.
options:
  instance: {description: Instance name, type: str, required: true}
  suffix:   {description: Suffix DN, type: str, required: true}
  consumer_host: {description: Consumer hostname, type: str, required: true}
  consumer_port: {description: Consumer port, type: int, default: 636}
  bind_method: {description: Bind method for remote, type: str, choices: [simple, sslclientauth], default: simple}
  bind_dn: {description: Bind DN when SIMPLE, type: str}
  bind_pw: {description: Bind password when SIMPLE, type: str}
  transport: {description: Transport type, type: str, choices: [LDAPS, StartTLS, LDAP], default: LDAPS}
  tls_ca: {description: CA file for LDAPS, type: path}
  tls_client_cert: {description: Client cert for sslclientauth, type: path}
  tls_client_key: {description: Client key for sslclientauth, type: path}
  backoff_min: {description: Backoff min seconds, type: int}
  backoff_max: {description: Backoff max seconds, type: int}
  purge_delay: {description: Purge delay seconds, type: int}
  compression: {description: Enable compression if supported, type: bool, default: false}
  state: {description: Target state, type: str, choices: [present, absent], default: present}
  use_ldapi: {description: Prefer ldapi, type: bool, default: true}
  ldaps_host: {description: Fallback host, type: str}
  ldaps_port: {description: Fallback port, type: int, default: 636}
  connect_timeout: {description: Connect timeout, type: int, default: 5}
  op_timeout: {description: Operation timeout, type: int, default: 30}
'''

EXAMPLES = r'''
- name: Ensure agreement present (LDAPS + mTLS)
  directories.ds.ds_repl_agreement:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
    consumer_host: "c1.dsnet.test"
    consumer_port: 636
    bind_method: sslclientauth
    transport: LDAPS
    tls_ca: "/etc/dirsrv/certs/ca.pem"
    tls_client_cert: "/etc/dirsrv/certs/repl-client.crt"
    tls_client_key: "/etc/dirsrv/certs/repl-client.key"
    state: present
'''

RETURN = r'''
agreement_dn:
  description: Managed agreement DN when known.
  returned: when known
  type: str
effective:
  description: Effective attributes applied or validated.
  returned: always
  type: dict
changed:
  description: Whether a change would have been made (stub false).
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


def _transport_map(transport):
    return {
        'LDAPS': 'SSL',
        'StartTLS': 'TLS',
        'LDAP': 'LDAP',
    }.get(transport, 'LDAP')


def run_module():
    args = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        consumer_host=dict(type='str', required=True),
        consumer_port=dict(type='int', default=636),
        name=dict(type='str'),
        bind_method=dict(type='str', choices=['simple', 'sslclientauth'], default='simple'),
        bind_dn=dict(type='str'),
        bind_pw=dict(type='str', no_log=True),
        transport=dict(type='str', choices=['LDAPS', 'StartTLS', 'LDAP'], default='LDAPS'),
        tls_ca=dict(type='path'),
        tls_client_cert=dict(type='path'),
        tls_client_key=dict(type='path'),
        backoff_min=dict(type='int'),
        backoff_max=dict(type='int'),
        purge_delay=dict(type='int'),
        compression=dict(type='bool', default=False),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        use_ldapi=dict(type='bool', default=True),
        ldaps_host=dict(type='str'),
        ldaps_port=dict(type='int', default=636),
        connect_timeout=dict(type='int', default=5),
        op_timeout=dict(type='int', default=30),
    )

    module = AnsibleModule(argument_spec=args, supports_check_mode=True)

    # Basic validation
    bm = module.params['bind_method']
    if bm == 'simple':
        if not module.params.get('bind_dn') or not module.params.get('bind_pw'):
            module.fail_json(msg='bind_method=simple requires bind_dn and bind_pw')
    if bm == 'sslclientauth':
        if not module.params.get('tls_client_cert') or not module.params.get('tls_client_key'):
            module.fail_json(msg='bind_method=sslclientauth requires tls_client_cert and tls_client_key')

    p = module.params

    try:
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
    except Exception as e:
        module.fail_json(msg=f"Failed to create LDAP connection: {str(e)}")

    esc_suffix = _escape_suffix_value(p['suffix'])
    replica_dn = f"cn=replica,cn={esc_suffix},cn=mapping tree,cn=config"
    try:
        client.search_one(replica_dn, 'base', '(objectClass=*)', ['cn'])
    except dsldap.DsLdapError as e:
        module.fail_json(msg=f"Enable replication on suffix before creating agreements: {p['suffix']}", hint=getattr(e, 'hint', None))

    # Search for existing agreements by name first, then by host:port
    existing = []
    if p.get('name'):
        filter_name = f"(&(objectClass=nsDS5ReplicationAgreement)(cn={p['name']}))"
        try:
            existing = client.search(replica_dn, 'one', filter_name, [
                'cn', 'nsds5ReplicaHost', 'nsds5ReplicaPort', 'nsds5ReplicaBindDN', 'nsds5ReplicaEnabled',
                'nsds5ReplicaTransportInfo', 'nsds5ReplicaBackoffMin', 'nsds5ReplicaBackoffMax', 'nsds5ReplicaPurgeDelay', 'nsds5ReplicaBindMethod'
            ])
        except Exception:
            existing = []
    
    # If no agreement found by name, search by host:port
    if not existing:
        filter_hp = f"(&(objectClass=nsDS5ReplicationAgreement)(nsds5ReplicaHost={p['consumer_host']})(nsds5ReplicaPort={p['consumer_port']}))"
        try:
            existing = client.search(replica_dn, 'one', filter_hp, [
                'cn', 'nsds5ReplicaHost', 'nsds5ReplicaPort', 'nsds5ReplicaBindDN', 'nsds5ReplicaEnabled',
                'nsds5ReplicaTransportInfo', 'nsds5ReplicaBackoffMin', 'nsds5ReplicaBackoffMax', 'nsds5ReplicaPurgeDelay', 'nsds5ReplicaBindMethod'
            ])
        except Exception:
            existing = []

    warnings = []
    agmt_dn = ''
    if existing:
        if len(existing) > 1:
            warnings.append("Multiple agreements match host:port; managing the first")
        agmt_dn = existing[0].get('dn', '')

    target_transport = _transport_map(p['transport'])
    target_attrs = {
        'nsds5ReplicaHost': p['consumer_host'],
        'nsds5ReplicaPort': str(p['consumer_port']),
        'nsds5ReplicaTransportInfo': target_transport,
        'nsds5ReplicaRoot': p['suffix'],
        'description': f"agmt to {p['consumer_host']}:{p['consumer_port']}",
    }
    if p['bind_method'] == 'simple' and p.get('bind_dn'):
        target_attrs['nsds5ReplicaBindDN'] = p['bind_dn']
        target_attrs['nsds5ReplicaBindMethod'] = 'SIMPLE'
        if p.get('bind_pw'):
            target_attrs['nsds5ReplicaCredentials'] = p['bind_pw']
    elif p['bind_method'] == 'sslclientauth':
        target_attrs['nsds5ReplicaBindMethod'] = 'SSLCLIENTAUTH'
    if p.get('backoff_min') is not None:
        target_attrs['nsds5ReplicaBackoffMin'] = str(p['backoff_min'])
    if p.get('backoff_max') is not None:
        target_attrs['nsds5ReplicaBackoffMax'] = str(p['backoff_max'])
    if p.get('purge_delay') is not None:
        target_attrs['nsds5ReplicaPurgeDelay'] = str(p['purge_delay'])
    if p.get('compression'):
        warnings.append('Compression attribute not implemented; skipping')

    changed = False

    if p['state'] == 'absent':
        if agmt_dn:
            if not module.check_mode:
                try:
                    client.delete(agmt_dn)
                except dsldap.DsLdapError as e:
                    module.fail_json(msg=f"Failed to delete agreement {agmt_dn}", hint=getattr(e, 'hint', None))
            changed = True
        module.exit_json(changed=changed, agreement_dn=agmt_dn, warnings=warnings)

    if not agmt_dn:
        cn_val = p.get('name') or f"agmt to {p['consumer_host']}:{p['consumer_port']}"
        agmt_dn = f"cn={cn_val},{replica_dn}"
        if not module.check_mode:
            add_attrs = {
                'objectClass': ['top', 'nsDS5ReplicationAgreement'],
                'cn': cn_val,
            }
            add_attrs.update(target_attrs)
            try:
                client.add(agmt_dn, add_attrs)
                # Enable the agreement after creation
                client.modify(agmt_dn, [('replace', 'nsds5ReplicaEnabled', 'on')])
            except dsldap.DsLdapError as e:
                module.fail_json(msg=f"Failed to create agreement {agmt_dn}", hint=getattr(e, 'hint', None))
        changed = True
        module.exit_json(changed=changed, agreement_dn=agmt_dn, effective=dict(
            host=p['consumer_host'], port=p['consumer_port'], bind_method=p['bind_method'], transport=p['transport'],
            backoff_min=p.get('backoff_min'), backoff_max=p.get('backoff_max'), purge_delay=p.get('purge_delay'), compression=p.get('compression')
        ), warnings=warnings)

    cur = existing[0].get('attrs', {}) if existing else {}
    changes = []
    for k, v in target_attrs.items():
        cur_v = _first(cur.get(k))
        if cur_v is None or str(cur_v) != str(v):
            changes.append(('replace', k, v))
    
    # Check if agreement is enabled
    cur_enabled = _first(cur.get('nsds5ReplicaEnabled'))
    if cur_enabled is None or cur_enabled.lower() not in ('on', 'true', 'yes', '1'):
        changes.append(('replace', 'nsds5ReplicaEnabled', 'on'))

    if changes:
        if not module.check_mode:
            try:
                client.modify(agmt_dn, changes)
            except dsldap.DsLdapError as e:
                warnings.append(f"Modify warning for {agmt_dn}: {getattr(e, 'hint', '')[:200]}")
        changed = True

    module.exit_json(changed=changed, agreement_dn=agmt_dn, effective=dict(
        host=p['consumer_host'], port=p['consumer_port'], bind_method=p['bind_method'], transport=p['transport'],
        backoff_min=p.get('backoff_min'), backoff_max=p.get('backoff_max'), purge_delay=p.get('purge_delay'), compression=p.get('compression')
    ), warnings=warnings)


if __name__ == '__main__':
    run_module()
