MATCH (w:Webhook {id: $webhook_id})
CREATE (w)-[:DELIVERED]->(d:Delivery {id: $id, webhook_id: $webhook_id, event: $event,
  at: $at, ok: $ok, attempts: $attempts, status: $status, error: $error,
  duration_ms: $duration_ms, subject: $subject})
RETURN d.id AS id
