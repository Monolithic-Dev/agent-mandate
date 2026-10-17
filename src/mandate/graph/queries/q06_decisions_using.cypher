MATCH (dec:Decision)-[:USED]->(i:Instruction)
WHERE i.id IN $instruction_ids
MATCH (dec)-[:CHECKED]->(a:Action)-[:PROPOSED_BY]->(ag:Agent)
RETURN DISTINCT dec, a, ag.id AS agent_id
ORDER BY dec.at, dec.as_of, dec.id
