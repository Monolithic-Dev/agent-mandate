MATCH (src:Summary {id: $source_id})
CREATE (i:Instruction {id: $id, effect: $effect, text_span: $text_span, status: 'pending', created_at: $created_at, quarantined: false, lineage_trust: 'untrusted'})
CREATE (s:Scope {id: $scope_id, action_type: $action_type, resource_pattern: $resource_pattern, constraints: $constraints})
CREATE (i)-[:ABOUT]->(s)
CREATE (src)-[:EXPRESSES]->(i)
SET i.valid_from = $valid_from, i.valid_to = $valid_to
WITH i
UNWIND $agent_ids AS agent_id
MATCH (a:Agent {id: agent_id})
CREATE (i)-[:APPLIES_TO]->(a)
RETURN count(a) AS applied
