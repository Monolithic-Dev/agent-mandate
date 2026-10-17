MATCH (i:Instruction {id: $id})
WHERE i.revoked_at IS NULL
SET i.revoked_at = $at, i.status = 'revoked', i.revoked_by = $by
RETURN count(i) AS changed
