MERGE (t:Tenant {id: $id})
ON CREATE SET t.name = $name, t.created_at = $created_at, t.nonce = $nonce
RETURN t.nonce = $nonce AS created
