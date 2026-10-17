MATCH ()-[d:DELEGATES_TO {id: $id}]->()
WHERE d.revoked_at IS NULL
SET d.revoked_at = $at
RETURN count(d) AS changed
