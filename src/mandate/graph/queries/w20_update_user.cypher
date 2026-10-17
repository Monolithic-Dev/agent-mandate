MATCH (u:User {id: $id})
SET u.name = $name, u.role = $role, u.all_tenants = $all_tenants, u.tenants = $tenants,
  u.disabled = $disabled, u.updated_at = $updated_at
RETURN u
