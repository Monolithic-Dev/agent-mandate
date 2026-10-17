CREATE (p:Principal {id: $id, name: $name, role: $role})
RETURN p.id AS id
