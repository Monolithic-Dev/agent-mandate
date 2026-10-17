MATCH (a:Action {id: $action_id})
WHERE a.status = 'pending'
SET a.status = $new_status
WITH a
CREATE (p:Approval {id: $approval_id, approved: $approved, by: $by, at: $at})-[:APPROVES]->(a)
RETURN count(a) AS changed
