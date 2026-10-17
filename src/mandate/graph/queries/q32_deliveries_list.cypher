MATCH (:Webhook {id: $webhook_id})-[:DELIVERED]->(d:Delivery)
RETURN d
ORDER BY d.at DESC, d.id DESC
LIMIT $limit
