MATCH (a:Action)-[:PROPOSED_BY]->(ag:Agent)
WHERE $status IS NULL OR a.status = $status
OPTIONAL MATCH (d:Decision)-[:CHECKED]->(a)
RETURN a, ag.id AS agent_id, d.id AS decision_id
ORDER BY a.at DESC, a.id DESC
LIMIT $limit
