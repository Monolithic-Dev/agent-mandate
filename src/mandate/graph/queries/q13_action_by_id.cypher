MATCH (a:Action {id: $id})-[:PROPOSED_BY]->(ag:Agent)
OPTIONAL MATCH (d:Decision)-[:CHECKED]->(a)
RETURN a, ag.id AS agent_id, d.id AS decision_id
