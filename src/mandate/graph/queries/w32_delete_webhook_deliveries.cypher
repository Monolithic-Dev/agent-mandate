MATCH (w:Webhook)-[:DELIVERED]->(d:Delivery)
WHERE ($id IS NOT NULL AND w.id = $id) OR ($tenant_id IS NOT NULL AND w.tenant_id = $tenant_id)
DETACH DELETE d
RETURN count(d) AS deleted
