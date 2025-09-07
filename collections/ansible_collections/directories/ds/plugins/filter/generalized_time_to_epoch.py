# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from datetime import datetime, timezone


DOCUMENTATION = r'''
name: generalized_time_to_epoch
short_description: Convert LDAP Generalized Time to epoch (UTC)
version_added: "1.0.0"
author: directories.ds (@directories-ds)
description:
  - Converts LDAP Generalized Time strings (UTC with trailing Z) into an integer epoch seconds value.
  - Supports strict forms C(YYYYmmddHHMMSSZ) and fractional seconds C(YYYYmmddHHMMSS.ffffffZ) (fraction truncated).
options:
  _input:
    description: LDAP Generalized Time string.
    type: string
'''

EXAMPLES = r'''
vars:
  t1: "20250101123045Z"
  t2: "20240229120000Z"
  t3: "20250101123045.123Z"

tasks:
  - set_fact:
      e1: "{{ t1 | generalized_time_to_epoch }}"
      e2: "{{ t2 | generalized_time_to_epoch }}"
      e3: "{{ t3 | generalized_time_to_epoch }}"
'''


_GTZ_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.\d+)?Z$")


def generalized_time_to_epoch(value: str) -> int | None:
    """Convert LDAP Generalized Time (UTC Z) to epoch seconds.

    Accepts YYYYmmddHHMMSSZ and YYYYmmddHHMMSS.ffffffZ (fraction truncated).
    Returns int epoch seconds or None if unparsable.
    """
    if not isinstance(value, str):
        return None
    m = _GTZ_RE.match(value)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


class FilterModule(object):
    def filters(self):
        return {
            'generalized_time_to_epoch': generalized_time_to_epoch,
        }

