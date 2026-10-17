MATCH (w:Webhook {id: $id})
SET w.cursor = $cursor, w.last_delivery_at = $last_delivery_at, w.last_ok = $last_ok,
  w.failures = $failures
RETURN w
