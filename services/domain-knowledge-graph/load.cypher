CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE;
CREATE FULLTEXT INDEX concept_text IF NOT EXISTS FOR (c:Concept) ON EACH [c.name, c.description];
LOAD CSV WITH HEADERS FROM 'file:///concepts.csv' AS r
CALL { WITH r
  MERGE (c:Concept {id: r.id})
  SET c.name = r.name, c.description = r.description, c.level = toInteger(r.level),
      c.wikidata = r.wikidata, c.works_count = toInteger(r.works_count),
      c.disambiguation_suspect = (r.disambiguation_suspect = 'True'),
      c.source = 'OpenAlex Concepts snapshot 2026-09-23'
} IN TRANSACTIONS OF 5000 ROWS;
LOAD CSV WITH HEADERS FROM 'file:///edges_child_of.csv' AS r
CALL { WITH r
  MATCH (ch:Concept {id: r.child_id}), (p:Concept {id: r.parent_id})
  MERGE (ch)-[e:CHILD_OF]->(p)
  SET e.similarity = toFloat(r.similarity), e.primary = (r.primary = 'True'),
      e.flags = CASE WHEN r.flags IS NULL OR r.flags = '' THEN [] ELSE split(r.flags, '|') END,
      e.source = 'MAG 2020-01-23 FieldOfStudyChildren'
} IN TRANSACTIONS OF 10000 ROWS;
LOAD CSV WITH HEADERS FROM 'file:///edges_related.csv.gz' AS r
CALL { WITH r
  MATCH (a:Concept {id: r.a_id}), (b:Concept {id: r.b_id})
  MERGE (a)-[e:RELATED_TO]->(b)
  SET e.a_type = r.a_type, e.b_type = r.b_type, e.score = toFloat(r.score),
      e.source = 'MAG 2020-01-23 RelatedFieldOfStudy'
} IN TRANSACTIONS OF 10000 ROWS;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH ()-[e:CHILD_OF]->() RETURN count(e) AS child_of_edges;
MATCH ()-[e:RELATED_TO]->() RETURN count(e) AS related_edges;
