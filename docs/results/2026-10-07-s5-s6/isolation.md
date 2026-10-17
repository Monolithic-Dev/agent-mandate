# S5: tenant isolation

Generated 2026-10-07 01:16 UTC. 60 probes over 3 variants, through the REST API.

**Cross-tenant leaks: 0/60 = 0.0% (95% CI 0.0% to 6.0%)**

| Variant | Probes | Leaks |
|---|---|---|
| v1_distinct_rules | 20 | 0 |
| v2_identical_rules | 20 | 0 |
| v3_ids_differ_by_one_character | 20 | 0 |

## Leaks

None.

## Limits

- Probes are the ones listed in docs/scenarios.md section 7 plus the extra mutations (revoke, list endpoints, principal reuse, foreign agent tool call); they do not cover attacks on FalkorDB itself or on the network.
- One shared admin key is used for all tenants (a documented single-key limit); isolation here means the tenant in the path decides which graph is touched.
