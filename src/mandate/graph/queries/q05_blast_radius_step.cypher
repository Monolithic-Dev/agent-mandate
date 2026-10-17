MATCH (i:Instruction)
WHERE i.id IN $instruction_ids
OPTIONAL MATCH (i)<-[:DERIVED_FROM]-(s:Summary)
OPTIONAL MATCH (s)-[:EXPRESSES]->(d:Instruction)
RETURN collect(DISTINCT s.id) AS summaries, collect(DISTINCT d.id) AS derived_instruction_ids
