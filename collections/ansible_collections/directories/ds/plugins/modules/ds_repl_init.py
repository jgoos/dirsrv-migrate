#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Directory Services Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: ds_repl_init
short_description: Initialize a 389-DS replication agreement
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Runs C(dsconf repl-agmt init) for a given agreement under a suffix and optionally waits for success.
options:
  instance:
    description: 389-DS instance name.
    type: str
    required: true
  suffix:
    description: Replicated suffix DN.
    type: str
    required: true
  agreement:
    description: Agreement name (CN value under the replica).
    type: str
    required: true
  wait:
    description: Whether to poll init-status until success.
    type: bool
    default: true
  timeout:
    description: Max seconds to wait for successful initialization.
    type: int
    default: 600
  poll_interval:
    description: Seconds between status polls.
    type: int
    default: 5
  conn_url:
    description: Optional remote LDAP URL (ldap/ldaps). If not provided, instance-local is used.
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
    default: 60
'''

EXAMPLES = r'''
- name: Initialize agreement and wait
  directories.ds.ds_repl_init:
    instance: "slapd-example"
    suffix: "dc=example,dc=com"
    agreement: "agmt to c1:636"
    timeout: 900
'''

RETURN = r'''
changed:
  description: Whether init was invoked.
  returned: always
  type: bool
status:
  description: Last init-status output captured.
  returned: when wait=true
  type: str
'''


from ansible.module_utils.basic import AnsibleModule
import subprocess
import time

def _run(argv, timeout=60):
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _base(params):
    base = ["dsconf"]
    if params.get('conn_url'):
        if params.get('dm_dn'):
            base += ["-D", params['dm_dn']]
        if params.get('dm_pw'):
            base += ["-w", params['dm_pw']]
        base += [params['conn_url']]
    else:
        base += [params['instance']]
    return base


def _status(params, timeout):
    base = _base(params)
    argv = base + ["repl-agmt", "init-status", "--suffix", params['suffix'], params['agreement']]
    cp = _run(argv, timeout=timeout)
    return cp


def run_module():
    args_spec = dict(
        instance=dict(type='str', required=True),
        suffix=dict(type='str', required=True),
        agreement=dict(type='str', required=True),
        wait=dict(type='bool', default=True),
        timeout=dict(type='int', default=600),
        poll_interval=dict(type='int', default=5),
        conn_url=dict(type='str', required=False),
        dm_dn=dict(type='str', required=False),
        dm_pw=dict(type='str', required=False, no_log=True),
        op_timeout=dict(type='int', default=60),
    )

    module = AnsibleModule(argument_spec=args_spec, supports_check_mode=True)
    p = module.params

    if module.check_mode:
        module.exit_json(changed=True)

    base = _base(p)
    argv = base + ["repl-agmt", "init", "--suffix", p['suffix'], p['agreement']]
    cp = _run(argv, timeout=p.get('op_timeout', 60))
    if cp.returncode != 0:
        module.fail_json(msg="dsconf repl-agmt init failed", rc=cp.returncode, stderr=cp.stderr.decode(errors='ignore'))

    if not p.get('wait', True):
        module.exit_json(changed=True)

    # Poll for success with progress reporting
    end_by = time.time() + int(p.get('timeout', 600))
    last_out = ''
    poll_count = 0
    start_time = time.time()

    while time.time() < end_by:
        poll_count += 1
        elapsed = time.time() - start_time

        st = _status(p, timeout=p.get('op_timeout', 60))
        out = st.stdout.decode('utf-8', errors='ignore')
        last_out = out

        # Log progress every 10 polls or when status changes
        if poll_count % 10 == 0 or 'error' in out.lower():
            module.warn(f"ds_repl_init: poll={poll_count} elapsed={elapsed:.1f}s status='{out.strip()}'")

        # success indicators borrowed from role's wait logic
        low = out.lower()
        if ('successfully initialized' in low) or ('total init succeeded' in low):
            module.exit_json(changed=True, status=out, polls=poll_count, elapsed_seconds=elapsed)
        time.sleep(int(p.get('poll_interval', 5)))

    module.fail_json(msg='Timeout waiting for successful initialization', status=last_out)


if __name__ == '__main__':
    run_module()
