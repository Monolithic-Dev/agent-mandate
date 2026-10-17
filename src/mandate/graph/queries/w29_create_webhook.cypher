MATCH (t:Tenant {id: $tenant_id})
CREATE (w:Webhook {id: $id, tenant_id: $tenant_id, name: $name, url: $url, kind: $kind,
  events: $events, secret: $secret, enabled: $enabled, created_at: $created_at,
  created_by: $created_by, cursor: $cursor, failures: $failures})-[:NOTIFIES_FOR]->(t)
RETURN w
