MATCH (i:Instruction {id: $id})
WHERE i.status = 'pending'
SET i.status = 'active', i.activated_at = $at, i.valid_from = coalesce(i.valid_from, $at), i.lineage_trust = $lineage_trust, i.activated_by = $by, i.activated_via = $via
RETURN count(i) AS changed
