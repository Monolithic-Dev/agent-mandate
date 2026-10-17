MATCH (w:Webhook)
WHERE ($tenant_id IS NULL OR w.tenant_id = $tenant_id)
  AND ($enabled IS NULL OR w.enabled = $enabled)
RETURN w
ORDER BY w.created_at, w.id
