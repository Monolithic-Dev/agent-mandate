MATCH (u:User {id: $id})
SET u.last_login_at = $at
RETURN u.id AS id
