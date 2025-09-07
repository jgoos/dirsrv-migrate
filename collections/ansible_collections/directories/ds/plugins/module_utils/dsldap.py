# -*- coding: utf-8 -*-

"""
Lightweight LDAP helper for directories.ds modules using OpenLDAP CLI.

Features:
  - LDAPI (SASL/EXTERNAL) first, with /run and /data/run socket paths.
  - LDAPS fallback with SIMPLE or client-cert (sslclientauth via SASL/EXTERNAL over TLS).
  - search_one, search, add, modify, delete with subprocess timeouts and retry with jitter.
  - Raises DsLdapError(code, hint) on failures.
"""

from __future__ import annotations

import os
import random
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


CONNECT_TIMEOUT = 5   # seconds
OP_TIMEOUT = 30       # seconds
RETRIES = 3
BACKOFF_BASE = 0.5    # seconds


class DsLdapError(Exception):
    def __init__(self, message: str, code: Optional[int] = None, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


def build_ldapi_url(instance: str, base_dir: str = "/run") -> str:
    """Return a percent-encoded LDAPI URL for the instance socket.

    Examples:
      - host systemd path:      ldapi://%2Frun%2Fslapd-<instance>.socket
      - container default path: ldapi://%2Fdata%2Frun%2Fslapd-<instance>.socket
    """
    socket_path = f"{base_dir}/slapd-{instance}.socket"
    enc = socket_path.replace('/', '%2F')
    return f"ldapi://{enc}"


@dataclass
class LdapConnParams:
    instance: str
    use_ldapi: bool = True
    ldaps_host: Optional[str] = None
    ldaps_port: int = 636
    bind_method: str = "simple"  # simple | sslclientauth
    bind_dn: Optional[str] = None
    bind_pw: Optional[str] = None
    tls_ca: Optional[str] = None
    tls_client_cert: Optional[str] = None
    tls_client_key: Optional[str] = None
    connect_timeout: int = CONNECT_TIMEOUT
    op_timeout: int = OP_TIMEOUT


class DsLdap:
    """Simple wrapper invoking ldapsearch/ldapmodify/ldapdelete with retries."""

    def __init__(self, params: LdapConnParams) -> None:
        self.params = params
        self.urls: List[str] = []
        if params.use_ldapi:
            self.urls.append(build_ldapi_url(params.instance, "/run"))
            self.urls.append(build_ldapi_url(params.instance, "/data/run"))
        if params.ldaps_host:
            self.urls.append(f"ldaps://{params.ldaps_host}:{params.ldaps_port}")

    def _auth_args(self, url: str) -> Tuple[List[str], Dict[str, str]]:
        env = os.environ.copy()
        argv: List[str] = []
        if url.startswith("ldapi://"):
            argv += ["-Y", "EXTERNAL"]
        else:
            if self.params.tls_ca:
                env["LDAPTLS_CACERT"] = self.params.tls_ca
            if self.params.bind_method == "simple":
                if not self.params.bind_dn or not self.params.bind_pw:
                    raise DsLdapError("SIMPLE bind requires bind_dn and bind_pw", hint="Provide bind_dn/bind_pw or use ldapi")
                argv += ["-x", "-D", self.params.bind_dn, "-w", self.params.bind_pw]
            elif self.params.bind_method == "sslclientauth":
                if not self.params.tls_client_cert or not self.params.tls_client_key:
                    raise DsLdapError("sslclientauth requires tls_client_cert and tls_client_key")
                env["LDAPTLS_CERT"] = self.params.tls_client_cert
                env["LDAPTLS_KEY"] = self.params.tls_client_key
                argv += ["-Y", "EXTERNAL"]
        return argv, env

    def _run_with_retry(self, argv: List[str], env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        last_err: Optional[Exception] = None
        for attempt in range(1, RETRIES + 1):
            try:
                cp = subprocess.run(
                    argv,
                    input=(stdin.encode("utf-8") if stdin is not None else None),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    timeout=self.params.op_timeout,
                    check=False,
                )
                if cp.returncode == 0:
                    return cp
                last_err = DsLdapError(
                    f"Command failed rc={cp.returncode}", code=cp.returncode,
                    hint=(cp.stderr.decode(errors='ignore') or cp.stdout.decode(errors='ignore'))[:512]
                )
            except subprocess.TimeoutExpired as te:
                last_err = DsLdapError("LDAP command timeout", hint=str(te))
            if attempt < RETRIES:
                time.sleep(BACKOFF_BASE * attempt + random.uniform(0, 0.25))
        assert last_err is not None
        raise last_err

    def _first_ok(self) -> Tuple[str, List[str], Dict[str, str]]:
        last_exc: Optional[Exception] = None
        for url in self.urls:
            try:
                auth_argv, env = self._auth_args(url)
                argv = ["ldapsearch", "-LLL", "-o", f"nettimeout={self.params.connect_timeout}"] + auth_argv + ["-H", url, "-s", "base", "-b", "", "1.1"]
                cp = self._run_with_retry(argv, env=env)
                if cp.returncode == 0:
                    return url, auth_argv, env
            except Exception as e:
                last_exc = e
                continue
        raise DsLdapError("No usable LDAP URL (ldapi or ldaps) succeeded", hint=str(last_exc) if last_exc else None)

    def search_one(self, base: str, scope: str, flt: str, attrs: List[str]) -> Dict[str, Any]:
        url, auth_argv, env = self._first_ok()
        argv = [
            "ldapsearch", "-LLL",
            "-o", f"nettimeout={self.params.connect_timeout}",
            "-o", "ldif-wrap=no",
        ] + auth_argv + ["-H", url, "-s", scope, "-b", base, flt] + (attrs or [])
        cp = self._run_with_retry(argv, env=env)
        return self._parse_single_entry(cp.stdout.decode("utf-8", errors="ignore"))

    def search(self, base: str, scope: str, flt: str, attrs: List[str]) -> List[Dict[str, Any]]:
        url, auth_argv, env = self._first_ok()
        argv = [
            "ldapsearch", "-LLL",
            "-o", f"nettimeout={self.params.connect_timeout}",
            "-o", "ldif-wrap=no",
        ] + auth_argv + ["-H", url, "-s", scope, "-b", base, flt] + (attrs or [])
        cp = self._run_with_retry(argv, env=env)
        return self._parse_entries(cp.stdout.decode("utf-8", errors="ignore"))

    def add(self, dn: str, attrs: Dict[str, Any]) -> None:
        url, auth_argv, env = self._first_ok()
        ldif = [f"dn: {dn}", "changetype: add"]
        for k, v in (attrs or {}).items():
            if isinstance(v, (list, tuple)):
                for val in v:
                    ldif.append(f"{k}: {val}")
            elif v is not None:
                ldif.append(f"{k}: {v}")
        ldif.append("")
        argv = ["ldapmodify", "-o", f"nettimeout={self.params.connect_timeout}"] + auth_argv + ["-H", url, "-a"]
        self._run_with_retry(argv, env=env, stdin="\n".join(ldif))

    def modify(self, dn: str, changes: List[Tuple[str, Any]]) -> None:
        url, auth_argv, env = self._first_ok()
        ldif = [f"dn: {dn}", "changetype: modify"]
        for ch in changes or []:
            if not isinstance(ch, (list, tuple)) or len(ch) < 2:
                raise DsLdapError("Invalid change tuple")
            op = ch[0]
            attr = ch[1]
            val = ch[2] if len(ch) > 2 else None
            if op not in ("add", "delete", "replace"):
                raise DsLdapError("Unsupported modify op; use add|delete|replace")
            ldif.append(f"{op}: {attr}")
            if val is None:
                pass
            elif isinstance(val, (list, tuple)):
                for v in val:
                    ldif.append(f"{attr}: {v}")
            else:
                ldif.append(f"{attr}: {val}")
            ldif.append("-")
        ldif.append("")
        argv = ["ldapmodify", "-o", f"nettimeout={self.params.connect_timeout}"] + auth_argv + ["-H", url]
        self._run_with_retry(argv, env=env, stdin="\n".join(ldif))

    def delete(self, dn: str) -> None:
        url, auth_argv, env = self._first_ok()
        argv = ["ldapdelete", "-o", f"nettimeout={self.params.connect_timeout}"] + auth_argv + ["-H", url, dn]
        self._run_with_retry(argv, env=env)

    def _unfold(self, text: str) -> List[str]:
        lines: List[str] = []
        for raw in text.splitlines():
            # LDIF line folding: continuation lines start with a single space
            if raw.startswith(' ') and lines:
                lines[-1] += raw[1:]
            else:
                lines.append(raw)
        return lines

    def _parse_single_entry(self, text: str) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"attrs": {}}
        dn_seen = False
        for line in self._unfold(text):
            if not line.strip():
                continue
            if line.lower().startswith("dn: "):
                entry["dn"] = line[4:].strip()
                dn_seen = True
                continue
            if not dn_seen:
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                entry.setdefault("attrs", {}).setdefault(k, []).append(v)
        return entry

    def _parse_entries(self, text: str) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        cur: Optional[Dict[str, Any]] = None
        for line in self._unfold(text):
            if not line.strip():
                if cur is not None and ('dn' in cur):
                    entries.append(cur)
                cur = None
                continue
            if line.lower().startswith('dn: '):
                if cur is not None and ('dn' in cur):
                    entries.append(cur)
                cur = {"attrs": {}}
                cur["dn"] = line[4:].strip()
                continue
            if cur is None:
                continue
            if ':' in line:
                k, v = line.split(':', 1)
                k = k.strip()
                v = v.strip()
                cur.setdefault('attrs', {}).setdefault(k, []).append(v)
        if cur is not None and ('dn' in cur):
            entries.append(cur)
        return entries
