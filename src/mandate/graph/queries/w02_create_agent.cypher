CREATE (a:Agent {id: $id, name: $name, kind: $kind})
RETURN a.id AS id
