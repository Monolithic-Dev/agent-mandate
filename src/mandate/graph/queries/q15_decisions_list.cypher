MATCH (d:Decision)-[:CHECKED]->(a:Action)-[:PROPOSED_BY]->(ag:Agent)
WHERE $agent_id IS NULL OR ag.id = $agent_id
RETURN d, a, ag.id AS agent_id
ORDER BY d.at DESC, d.id DESC
LIMIT $limit
