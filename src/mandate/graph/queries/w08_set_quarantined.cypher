MATCH (i:Instruction)
WHERE i.id IN $ids
SET i.quarantined = $value, i.quarantine_changed_at = $at, i.quarantine_changed_by = $by
RETURN count(i) AS changed
