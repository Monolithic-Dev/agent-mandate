MATCH (r:RevokedToken)
RETURN r
ORDER BY r.revoked_at DESC, r.id DESC
LIMIT $limit
