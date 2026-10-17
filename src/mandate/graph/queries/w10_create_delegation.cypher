MATCH (f:Agent {id: $from_agent}), (t:Agent {id: $to_agent})
CREATE (f)-[d:DELEGATES_TO {id: $id, action_type: $action_type, resource_pattern: $resource_pattern, constraints: $constraints, created_at: $created_at, valid_from: $valid_from}]->(t)
SET d.valid_to = $valid_to, d.via_instruction = $via_instruction
RETURN count(d) AS created
