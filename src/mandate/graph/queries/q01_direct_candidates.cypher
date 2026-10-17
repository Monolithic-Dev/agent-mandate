MATCH (i:Instruction)-[:APPLIES_TO]->(:Agent {id: $agent_id})
MATCH (i)-[:ABOUT]->(s:Scope)
WHERE i.created_at <= $as_of
RETURN i, s
