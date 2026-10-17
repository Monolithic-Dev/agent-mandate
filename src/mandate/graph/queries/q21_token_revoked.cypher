MATCH (r:RevokedToken {id: $token_id})
RETURN count(r) AS revoked
