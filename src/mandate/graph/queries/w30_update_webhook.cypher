MATCH (w:Webhook {id: $id})
SET w.name = $name, w.events = $events, w.enabled = $enabled
RETURN w
