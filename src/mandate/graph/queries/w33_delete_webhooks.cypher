MATCH (w:Webhook)
WHERE ($id IS NOT NULL AND w.id = $id) OR ($tenant_id IS NOT NULL AND w.tenant_id = $tenant_id)
DETACH DELETE w
RETURN count(w) AS deleted
