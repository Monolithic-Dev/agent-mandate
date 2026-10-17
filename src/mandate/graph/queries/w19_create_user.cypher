MERGE (u:User {email: $email})
ON CREATE SET u.id = $id, u.name = $name, u.role = $role, u.all_tenants = $all_tenants,
  u.tenants = $tenants, u.disabled = $disabled, u.created_at = $created_at,
  u.updated_at = $updated_at, u.password_hash = $password_hash
RETURN u.id = $id AS created
