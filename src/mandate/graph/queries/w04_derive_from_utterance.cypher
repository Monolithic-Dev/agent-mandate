MATCH (s:Summary {id: $summary_id}), (p:Utterance {id: $source_id})
CREATE (s)-[:DERIVED_FROM]->(p)
RETURN count(p) AS linked
