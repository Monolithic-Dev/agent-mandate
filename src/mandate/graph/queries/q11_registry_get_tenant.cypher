MATCH (t:Tenant {id: $id})
RETURN t.id AS id, t.name AS name, t.created_at AS created_at
