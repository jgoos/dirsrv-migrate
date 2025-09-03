#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import annotations
from ansible.module_utils.basic import AnsibleModule
import os, re, io, base64, gzip


def unfold(lines):
    out, buf = [], ""
    for line in lines:
        if line.startswith(" "):
            buf += line[1:]
        else:
            if buf:
                out.append(buf)
            buf = line
    if buf:
        out.append(buf)
    return out


def parse_entry(txt):
    u = unfold(txt.splitlines())
    dn, ocs, attrs = "", set(), {}
    for ln in u:
        if ":" not in ln:
            continue
        name, rest = ln.split(":", 1)
        name = name.strip()
        is_b64 = rest.startswith(":")
        raw = rest[1:].strip() if is_b64 else rest.strip()
        if is_b64:
            try:
                val = base64.b64decode(raw).decode("utf-8", "replace")
            except Exception:
                val = ""
        else:
            val = raw
        low = name.lower()
        if low == "dn":
            dn = val
        else:
            attrs.setdefault(name, []).append(val)
            if low == "objectclass" and val:
                ocs.add(val.strip().lower())
    return dn, ocs, attrs


def write_entry(fh, blob):
    # ensure exactly one blank line between entries
    if blob.endswith("\n"):
        fh.write(blob)
        if not blob.endswith("\n\n"):
            fh.write("\n")
    else:
        fh.write(blob + "\n\n")


def compile_rules(dn_regex_any, oc_all_groups):
    dn_res = [re.compile(p, re.IGNORECASE) for p in dn_regex_any]
    oc_all = [set(x.strip().lower() for x in grp if x) for grp in oc_all_groups]
    return dn_res, oc_all


def should_drop(dn, ocs, dn_res, oc_all):
    if any(rx.search(dn) for rx in dn_res):
        return True
    if any(all(x in ocs for x in grp) for grp in oc_all):
        return True
    return False


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            src=dict(type="path", required=True),
            clean=dict(type="path", required=True),
            removed=dict(type="path", required=True),
            dn_regex_any=dict(type="list", elements="str", default=[]),
            oc_all=dict(type="list", elements="list", default=[]),
            compress_removed=dict(type="bool", default=True),
            compress_orig=dict(type="bool", default=True),
        ),
        supports_check_mode=True,
    )

    p = module.params
    src = p["src"]
    clean_path = p["clean"]
    removed_path = p["removed"]
    dn_regex_any = p["dn_regex_any"]
    oc_all = p["oc_all"]

    if not os.path.isfile(src):
        module.fail_json(msg=f"Source not found: {src}")

    dn_res, oc_all_groups = compile_rules(dn_regex_any, oc_all)

    kept = removed = 0
    wrote_preamble = False

    try:
        # writers
        if not module.check_mode:
            fclean = io.open(clean_path, "w", encoding="utf-8")
            # gzip removed if requested
            if p["compress_removed"] and not removed_path.endswith(".gz"):
                removed_path += ".gz"
            if removed_path.endswith(".gz"):
                frem = gzip.open(removed_path, "wt", encoding="utf-8")
            else:
                frem = io.open(removed_path, "w", encoding="utf-8")
        else:
            fclean = io.StringIO()
            frem = io.StringIO()

        # stream over entries
        with io.open(src, "r", encoding="utf-8", errors="replace") as fin:
            entry = []

            def flush():
                nonlocal kept, removed, wrote_preamble
                if not entry:
                    return
                blob = "".join(entry)
                dn, ocs, attrs = parse_entry(blob)
                # Handle preamble blocks (e.g., 'version: 1') without a DN:
                if not dn:
                    if not wrote_preamble and blob.strip():
                        write_entry(fclean, blob)
                        wrote_preamble = True
                    # Do not count preamble as kept/removed entry
                    return
                if should_drop(dn, ocs, dn_res, oc_all_groups):
                    write_entry(frem, blob)
                    removed += 1
                else:
                    write_entry(fclean, blob)
                    kept += 1

            for line in fin:
                if line.strip() == "":
                    flush()
                    entry = []
                else:
                    entry.append(line)
            flush()

        if not module.check_mode:
            fclean.close()
            frem.close()

        # compress original if requested
        orig_gz = None
        if p["compress_orig"] and not module.check_mode:
            if not src.endswith(".gz"):
                # gzip -f is safe; this overwrites any pre-existing .gz
                os.system(f"gzip -f {src}")
                orig_gz = src + ".gz"
            else:
                orig_gz = src

        module.exit_json(
            changed=True,
            kept=kept,
            removed=removed,
            clean=clean_path,
            removed_file=removed_path,
            orig_compressed=orig_gz,
        )
    except Exception as e:
        module.fail_json(msg=str(e))


def main():
    run_module()


if __name__ == "__main__":
    main()
