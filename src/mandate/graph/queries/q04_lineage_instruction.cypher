MATCH (i:Instruction {id: $node_id})
OPTIONAL MATCH (src)-[:EXPRESSES]->(i)
OPTIONAL MATCH (speaker:Principal)-[:SAID]->(src)
RETURN src.id AS id, labels(src)[0] AS label, src.trust AS trust, speaker.id AS principal_id
