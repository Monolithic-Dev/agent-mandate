MATCH (u:User {id: $user_id})
CREATE (u)-[:HAS_SESSION]->(s:Session {id: $id, user_id: $user_id, token_hash: $token_hash,
  created_at: $created_at, expires_at: $expires_at, last_seen_at: $last_seen_at,
  user_agent: $user_agent})
RETURN s
