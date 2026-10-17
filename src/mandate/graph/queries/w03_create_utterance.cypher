MATCH (p:Principal {id: $speaker_id})
CREATE (p)-[:SAID]->(u:Utterance {id: $id, text: $text, channel: $channel, trust: $trust, at: $at})
SET u.source_ref = $source_ref
RETURN u.id AS id
