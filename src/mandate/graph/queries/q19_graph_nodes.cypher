MATCH (n)
WHERE NOT n:RevokedToken
RETURN labels(n)[0] AS label, properties(n) AS props
LIMIT $limit
