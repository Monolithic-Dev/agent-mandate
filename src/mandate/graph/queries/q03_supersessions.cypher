MATCH (n:Instruction)-[r:SUPERSEDES]->(o:Instruction)
WHERE o.id IN $instruction_ids AND r.at <= $as_of
RETURN o.id AS superseded_id,
       n.id AS by_id,
       r.at AS at,
       coalesce(n.quarantined, false) AS by_quarantined
