MATCH (a:Action {id: $id})
SET a.status = $status
RETURN count(a) AS changed
