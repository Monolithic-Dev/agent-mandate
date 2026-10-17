MATCH (dec:Decision)-[u:USED]->(i:Instruction)
MATCH (dec)-[:CHECKED]->(:Action)-[:PROPOSED_BY]->(ag:Agent)
RETURN i.id AS instruction_id,
       count(DISTINCT dec) AS decisions,
       count(DISTINCT CASE WHEN u.role = 'winner' THEN dec END) AS as_winner,
       count(DISTINCT ag) AS agents,
       min(dec.at) AS first_at,
       max(dec.at) AS last_at
ORDER BY decisions DESC, instruction_id
LIMIT $limit
