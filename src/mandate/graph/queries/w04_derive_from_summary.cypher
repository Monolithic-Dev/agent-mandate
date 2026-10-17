MATCH (s:Summary {id: $summary_id}), (p:Summary {id: $source_id})
CREATE (s)-[:DERIVED_FROM]->(p)
RETURN count(p) AS linked
