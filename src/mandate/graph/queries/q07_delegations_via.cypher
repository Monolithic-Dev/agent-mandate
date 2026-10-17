MATCH ()-[d:DELEGATES_TO]->()
WHERE d.via_instruction IN $instruction_ids
RETURN d.id AS id
ORDER BY d.id
