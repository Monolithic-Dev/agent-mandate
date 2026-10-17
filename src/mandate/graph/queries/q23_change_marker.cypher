OPTIONAL MATCH (d:Decision)
WITH count(d) AS decisions, max(d.at) AS last_decision_at
OPTIONAL MATCH (a:Action)
WHERE a.status = $pending
WITH decisions, last_decision_at, collect(a.id) AS pending
OPTIONAL MATCH (i:Instruction)
RETURN decisions, last_decision_at, pending, collect([i.id, i.status, i.quarantined, i.lineage_trust]) AS rules
