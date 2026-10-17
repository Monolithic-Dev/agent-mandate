MATCH (u:User)-[:HAS_SESSION]->(s:Session {token_hash: $token_hash})
WHERE s.expires_at > $now
RETURN u, s
