MATCH (s:Session {id: $id})
SET s.last_seen_at = $at
RETURN s.id AS id
