# Migration Guide: VM-First Default

## Summary

As of this release, the default value for `dirsrv_target_type` has changed from `'container'` to `'vm'` to reflect production-first usage patterns.

## Rationale

- **Production environments** run RHDS on VMs, not containers
- **Containers** are only used for development and testing
- **VM-first approach** prevents Podman-specific tasks from incorrectly running in production
- **Safety** - production environments work correctly by default without additional configuration

## What Changed

### Default Behavior
```yaml
# OLD (container-first):
dirsrv_target_type: 'container' (when undefined)

# NEW (VM-first):  
dirsrv_target_type: 'vm' (when undefined)
```

### Auto-Detection Still Works
The smart auto-detection in `roles/dirsrv_repl/defaults/main.yml` remains unchanged:
```yaml
dirsrv_target_type: >-
  {{
    'container'
      if (ansible_connection | default('ssh')) in [
        'containers.podman.podman', 'community.docker.docker', 'podman', 'docker'
      ] else 'vm'
  }}
```

This means:
- Using Podman/Docker connection plugins → automatically detected as `'container'`
- Using SSH or other connections → automatically detected as `'vm'`

## Impact on Your Environment

### Production VMs (RHDS on VMs)
✅ **No action required** - VMs are now the default

Your production inventory can simply use:
```yaml
all:
  hosts:
    rhds-server01.example.com:
      ansible_host: rhds-server01.example.com
      # dirsrv_target_type automatically set to 'vm'
```

### Development/Test Containers (Podman Compose)
⚠️ **Action required** - Explicitly declare container type

Container test environments must now explicitly set:
```yaml
# In test variable files (e.g., test/compose_vars.yml):
dirsrv_target_type: container
```

**Already Updated:**
- `test/compose_vars.yml` ✅
- `test/repl_vars.yml` ✅
- `test/repl_mesh_vars.yml` ✅

### Mixed Environments
If you have both VMs and containers in the same inventory:
```yaml
all:
  children:
    production_vms:
      hosts:
        rhds-prod01.example.com:
          # No dirsrv_target_type needed (defaults to 'vm')
    
    dev_containers:
      vars:
        dirsrv_target_type: container  # Set at group level
      hosts:
        ds-s1:
          ansible_connection: containers.podman.podman
```

## What This Fixes

### Production Error Resolved
The error on `rhds-eid-acc-master03.asml.com`:
```
'dict object' has no attribute 'stdout'
```

This occurred because:
1. Podman network inspection task correctly skipped for VMs
2. But downstream tasks tried to access `stdout` on skipped results
3. With VM-first defaults, this logic flow is clearer and safer

### Container-Specific Tasks Now Skip for VMs
These tasks only run when `dirsrv_target_type == 'container'`:
- Podman network inspection
- Container IP mapping extraction
- `/etc/hosts` conflict detection for containers

## Testing

After this change:
- VM environments work without modification ✅
- Container tests explicitly declare their type ✅
- Auto-detection still works for Podman connections ✅
- No impact on existing production VMs ✅

## Rollback

If you need to revert to container-first behavior:
```yaml
# In your inventory or group_vars:
dirsrv_target_type: container
```

## Questions?

See `AGENTS.md` sections:
- "Naming & Addressing" for resolution rules
- "Environment Matrix" for container vs VM differences

