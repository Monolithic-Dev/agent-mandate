MATCH (ag:Agent {id: $agent_id})
CREATE (a:Action {id: $action_id, action_type: $action_type, resource: $resource, args: $args, status: $action_status, at: $action_at})-[:PROPOSED_BY]->(ag)
CREATE (d:Decision {id: $decision_id, result: $result, reason: $reason, as_of: $as_of, at: $decision_at, path_json: $path_json, ignored_json: $ignored_json, latency_ms: $latency_ms})-[:CHECKED]->(a)
SET d.request_id = $request_id
WITH d
UNWIND $used AS u
OPTIONAL MATCH (i:Instruction {id: u.instruction_id})
FOREACH (x IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (d)-[:USED {role: u.role}]->(i))
RETURN count(DISTINCT d) AS recorded
