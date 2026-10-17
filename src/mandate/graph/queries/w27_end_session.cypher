MATCH (:User {id: $user_id})-[:HAS_SESSION]->(s:Session {id: $id})
DETACH DELETE s
RETURN count(s) AS ended
