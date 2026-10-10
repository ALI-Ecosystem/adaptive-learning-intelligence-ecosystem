// 1. search for a concept
CALL db.index.fulltext.queryNodes('concept_text', 'recursion') YIELD node, score
RETURN node.id AS id, node.name AS name, node.level AS level, round(score, 2) AS score LIMIT 5;
// 2. parents (broader), primary first
MATCH (c:Concept {name: 'Stack (abstract data type)'})-[e:CHILD_OF]->(p)
RETURN p.name AS parent, p.level AS level, e.primary AS primary, e.similarity AS similarity, e.flags AS flags
ORDER BY e.similarity DESC;
// 3. children (narrower)
MATCH (c:Concept {name: 'Data structure'})<-[e:CHILD_OF]-(k)
RETURN k.name AS child, k.level AS level, e.primary AS primary ORDER BY e.similarity DESC LIMIT 10;
// 4. related concepts
MATCH (c:Concept {name: 'Recursion (computer science)'})-[e:RELATED_TO]-(o)
RETURN o.name AS related, e.score AS score ORDER BY e.score DESC LIMIT 10;
// 5. relationship types available
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType;
MATCH ()-[e:RELATED_TO]->() RETURN e.a_type AS from_type, e.b_type AS to_type, count(*) AS n ORDER BY n DESC LIMIT 8;
// 6. navigate: primary path from a concept up to its top field
MATCH (c:Concept {name: 'Binary search tree'})
MATCH path = (c)-[:CHILD_OF* {primary: true}]->(top:Concept {level: 0})
RETURN [n IN nodes(path) | n.name] AS path_to_root LIMIT 3;
