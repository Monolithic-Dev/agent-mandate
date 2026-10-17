MATCH (t:Tenant {id: $id})
DETACH DELETE t
RETURN count(t) AS deleted
