MATCH (i:Instruction)-[:APPLIES_TO]->(a:Agent)
MATCH (i)-[:ABOUT]->(s:Scope)
WHERE ($status IS NULL OR i.status = $status) AND ($agent_id IS NULL OR a.id = $agent_id)
RETURN i, s, a.id AS agent_id
ORDER BY i.created_at, i.id
