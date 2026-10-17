CREATE (e:AuditEvent {id: $id, at: $at, actor_kind: $actor_kind, actor_id: $actor_id,
  actor_name: $actor_name, action: $action, method: $method, route: $route,
  tenant_id: $tenant_id, target: $target, status: $status, outcome: $outcome,
  request_id: $request_id})
WITH e
OPTIONAL MATCH (u:User {id: $actor_id})
OPTIONAL MATCH (t:Tenant {id: $tenant_id})
FOREACH (_ IN CASE WHEN u IS NULL THEN [] ELSE [1] END | CREATE (u)-[:PERFORMED]->(e))
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | CREATE (e)-[:CONCERNS]->(t))
RETURN e.id AS id
