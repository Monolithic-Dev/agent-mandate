MATCH (a)-[r]->(b)
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS source, b.id AS target, type(r) AS type, properties(r) AS props
