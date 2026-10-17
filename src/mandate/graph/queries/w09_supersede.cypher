MATCH (n:Instruction {id: $new_id}), (o:Instruction {id: $old_id})
CREATE (n)-[:SUPERSEDES {at: $at}]->(o)
SET o.status = CASE WHEN o.status = 'active' THEN 'superseded' ELSE o.status END
RETURN count(o) AS changed
