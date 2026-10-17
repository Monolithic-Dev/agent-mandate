MATCH (dec:Decision {id: $decision_id})-[:CHECKED]->(a:Action)
OPTIONAL MATCH (a)-[:PROPOSED_BY]->(ag:Agent)
OPTIONAL MATCH (dec)-[u:USED]->(i:Instruction)
RETURN dec, a, ag.id AS agent_id, collect({id: i.id, role: u.role}) AS used
