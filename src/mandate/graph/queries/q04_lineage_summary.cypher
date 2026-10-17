MATCH (s:Summary {id: $node_id})-[:DERIVED_FROM]->(p)
OPTIONAL MATCH (speaker:Principal)-[:SAID]->(p)
RETURN p.id AS id, labels(p)[0] AS label, p.trust AS trust, speaker.id AS principal_id
