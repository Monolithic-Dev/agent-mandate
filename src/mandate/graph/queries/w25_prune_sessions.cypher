MATCH (:User {id: $user_id})-[:HAS_SESSION]->(s:Session)
WHERE s.expires_at <= $now
DETACH DELETE s
RETURN count(s) AS ended
