MATCH (e:AuditEvent)
WHERE ($tenant_ids IS NULL OR e.tenant_id IN $tenant_ids)
  AND ($tenant_id IS NULL OR e.tenant_id = $tenant_id)
  AND ($actor_id IS NULL OR e.actor_id = $actor_id)
  AND ($action IS NULL OR e.action = $action)
  AND ($before IS NULL OR e.id < $before)
RETURN e
ORDER BY e.id DESC
LIMIT $limit
