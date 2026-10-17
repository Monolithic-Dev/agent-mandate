MATCH (t:Tenant)
RETURN t.id AS id, t.name AS name, t.created_at AS created_at
ORDER BY t.id
