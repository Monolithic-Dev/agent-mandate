MATCH (:Webhook {id: $webhook_id})-[:DELIVERED]->(d:Delivery)
WITH d ORDER BY d.at DESC, d.id DESC
SKIP $keep
DETACH DELETE d
RETURN count(d) AS pruned
