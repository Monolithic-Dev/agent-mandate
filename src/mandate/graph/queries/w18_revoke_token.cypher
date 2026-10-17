MERGE (r:RevokedToken {id: $token_id})
ON CREATE SET r.agent_id = $agent_id, r.expires_at = $expires_at, r.revoked_at = $revoked_at, r.by = $by
RETURN r
