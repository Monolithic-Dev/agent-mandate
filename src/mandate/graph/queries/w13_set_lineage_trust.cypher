MATCH (i:Instruction {id: $id})
SET i.lineage_trust = $lineage_trust
RETURN count(i) AS changed
