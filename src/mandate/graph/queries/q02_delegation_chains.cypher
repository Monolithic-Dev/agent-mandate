MATCH path = (root:Agent)-[:DELEGATES_TO*1..4]->(:Agent {id: $agent_id})
WHERE all(d IN relationships(path) WHERE d.created_at <= $as_of)
RETURN [n IN nodes(path) | n.id] AS agents,
       [d IN relationships(path) | properties(d)] AS hops
