MATCH (u:User {id: $id})
SET u.password_hash = $password_hash, u.updated_at = $at
RETURN u
