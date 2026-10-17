MATCH (:User {id: $user_id})-[:HAS_SESSION]->(s:Session)
WHERE $keep IS NULL OR s.id <> $keep
DETACH DELETE s
RETURN count(s) AS ended
