CREATE (s:Summary {id: $id, text: $text, at: $at})
RETURN s.id AS id
