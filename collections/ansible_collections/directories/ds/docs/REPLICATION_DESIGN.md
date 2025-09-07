This collection follows the repository’s MODULE_SPECS for 389-DS replication automation.

Highlights
- Manage agreements directly over LDAP (no dsconf parsing), LDAPI-first.
- Health semantics: update_code == 0, non-stale update_end, optional init_code == 0.
- Modules run on suppliers; polling is inside the module.

See also
- docs/MODULE_SPECS.md in the repository root for full specifications.

