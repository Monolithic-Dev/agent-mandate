MATCH (:User {id: $user_id})-[:HAS_SESSION]->(s:Session)
WHERE s.expires_at > $now
RETURN s
ORDER BY s.last_seen_at DESC, s.id DESC
