# Inventory and Mapping Templates (35 Pairs)

Use these templates to scaffold your inventory and the `dirsrv_host_map` for 35 RHDS 11→12 pairs.

Note: For the local test lab, hostnames `ds-s1`/`ds-c1`/`ds-s2`/`ds-c2` are used. This document targets production‑style FQDNs.

Replace hostnames with your real FQDNs, then copy to `inventory.yml` and `group_vars/all/dirsrv_mapping.yml`.

## inventory.yml (example)

```yaml
---
all:
  children:
    dirsrv_source:
      hosts:
        rhds11-01.example.com: { ansible_user: root }
        rhds11-02.example.com: { ansible_user: root }
        rhds11-03.example.com: { ansible_user: root }
        rhds11-04.example.com: { ansible_user: root }
        rhds11-05.example.com: { ansible_user: root }
        rhds11-06.example.com: { ansible_user: root }
        rhds11-07.example.com: { ansible_user: root }
        rhds11-08.example.com: { ansible_user: root }
        rhds11-09.example.com: { ansible_user: root }
        rhds11-10.example.com: { ansible_user: root }
        rhds11-11.example.com: { ansible_user: root }
        rhds11-12.example.com: { ansible_user: root }
        rhds11-13.example.com: { ansible_user: root }
        rhds11-14.example.com: { ansible_user: root }
        rhds11-15.example.com: { ansible_user: root }
        rhds11-16.example.com: { ansible_user: root }
        rhds11-17.example.com: { ansible_user: root }
        rhds11-18.example.com: { ansible_user: root }
        rhds11-19.example.com: { ansible_user: root }
        rhds11-20.example.com: { ansible_user: root }
        rhds11-21.example.com: { ansible_user: root }
        rhds11-22.example.com: { ansible_user: root }
        rhds11-23.example.com: { ansible_user: root }
        rhds11-24.example.com: { ansible_user: root }
        rhds11-25.example.com: { ansible_user: root }
        rhds11-26.example.com: { ansible_user: root }
        rhds11-27.example.com: { ansible_user: root }
        rhds11-28.example.com: { ansible_user: root }
        rhds11-29.example.com: { ansible_user: root }
        rhds11-30.example.com: { ansible_user: root }
        rhds11-31.example.com: { ansible_user: root }
        rhds11-32.example.com: { ansible_user: root }
        rhds11-33.example.com: { ansible_user: root }
        rhds11-34.example.com: { ansible_user: root }
        rhds11-35.example.com: { ansible_user: root }
    dirsrv_target:
      hosts:
        rhds12-01.example.com: { ansible_user: root }
        rhds12-02.example.com: { ansible_user: root }
        rhds12-03.example.com: { ansible_user: root }
        rhds12-04.example.com: { ansible_user: root }
        rhds12-05.example.com: { ansible_user: root }
        rhds12-06.example.com: { ansible_user: root }
        rhds12-07.example.com: { ansible_user: root }
        rhds12-08.example.com: { ansible_user: root }
        rhds12-09.example.com: { ansible_user: root }
        rhds12-10.example.com: { ansible_user: root }
        rhds12-11.example.com: { ansible_user: root }
        rhds12-12.example.com: { ansible_user: root }
        rhds12-13.example.com: { ansible_user: root }
        rhds12-14.example.com: { ansible_user: root }
        rhds12-15.example.com: { ansible_user: root }
        rhds12-16.example.com: { ansible_user: root }
        rhds12-17.example.com: { ansible_user: root }
        rhds12-18.example.com: { ansible_user: root }
        rhds12-19.example.com: { ansible_user: root }
        rhds12-20.example.com: { ansible_user: root }
        rhds12-21.example.com: { ansible_user: root }
        rhds12-22.example.com: { ansible_user: root }
        rhds12-23.example.com: { ansible_user: root }
        rhds12-24.example.com: { ansible_user: root }
        rhds12-25.example.com: { ansible_user: root }
        rhds12-26.example.com: { ansible_user: root }
        rhds12-27.example.com: { ansible_user: root }
        rhds12-28.example.com: { ansible_user: root }
        rhds12-29.example.com: { ansible_user: root }
        rhds12-30.example.com: { ansible_user: root }
        rhds12-31.example.com: { ansible_user: root }
        rhds12-32.example.com: { ansible_user: root }
        rhds12-33.example.com: { ansible_user: root }
        rhds12-34.example.com: { ansible_user: root }
        rhds12-35.example.com: { ansible_user: root }
```

## group_vars/all/dirsrv_mapping.yml (example)

```yaml
---
dirsrv_host_map:
  rhds11-01.example.com: rhds12-01.example.com
  rhds11-02.example.com: rhds12-02.example.com
  rhds11-03.example.com: rhds12-03.example.com
  rhds11-04.example.com: rhds12-04.example.com
  rhds11-05.example.com: rhds12-05.example.com
  rhds11-06.example.com: rhds12-06.example.com
  rhds11-07.example.com: rhds12-07.example.com
  rhds11-08.example.com: rhds12-08.example.com
  rhds11-09.example.com: rhds12-09.example.com
  rhds11-10.example.com: rhds12-10.example.com
  rhds11-11.example.com: rhds12-11.example.com
  rhds11-12.example.com: rhds12-12.example.com
  rhds11-13.example.com: rhds12-13.example.com
  rhds11-14.example.com: rhds12-14.example.com
  rhds11-15.example.com: rhds12-15.example.com
  rhds11-16.example.com: rhds12-16.example.com
  rhds11-17.example.com: rhds12-17.example.com
  rhds11-18.example.com: rhds12-18.example.com
  rhds11-19.example.com: rhds12-19.example.com
  rhds11-20.example.com: rhds12-20.example.com
  rhds11-21.example.com: rhds12-21.example.com
  rhds11-22.example.com: rhds12-22.example.com
  rhds11-23.example.com: rhds12-23.example.com
  rhds11-24.example.com: rhds12-24.example.com
  rhds11-25.example.com: rhds12-25.example.com
  rhds11-26.example.com: rhds12-26.example.com
  rhds11-27.example.com: rhds12-27.example.com
  rhds11-28.example.com: rhds12-28.example.com
  rhds11-29.example.com: rhds12-29.example.com
  rhds11-30.example.com: rhds12-30.example.com
  rhds11-31.example.com: rhds12-31.example.com
  rhds11-32.example.com: rhds12-32.example.com
  rhds11-33.example.com: rhds12-33.example.com
  rhds11-34.example.com: rhds12-34.example.com
  rhds11-35.example.com: rhds12-35.example.com
```

## Validate quickly

Run a syntax check and mapping validation:

```bash
ansible-playbook -i inventory.yml site.yml --syntax-check
ansible-playbook -i inventory.yml site.yml --check --diff --limit localhost
```

Use a run label to isolate artifacts per batch:

```bash
ansible-playbook -i inventory.yml site.yml --ask-vault-pass -e dirsrv_artifact_run=2024-09-batch1
```
