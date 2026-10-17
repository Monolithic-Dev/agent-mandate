MATCH (d:Decision)-[:CHECKED]->(a:Action)-[:PROPOSED_BY]->(ag:Agent)
WHERE d.at >= $since
RETURN d.at AS at, d.result AS result, d.reason AS reason, a.action_type AS action_type,
  ag.id AS agent_id, d.latency_ms AS latency_ms
ORDER BY d.at DESC
LIMIT $limit
