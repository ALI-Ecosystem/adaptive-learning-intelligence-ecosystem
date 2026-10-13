"""One-time setup: store an embedding on every :Concept and create the vector index.

Usage: python -m placement.build_index
Uses the same static model as SCRUM-88 (build.py), so nothing new to download.
"""
import time

from . import config
from .embedder import concept_text, embed
from .graph import connect

BATCH = 2000


def main():
    driver = connect()
    rows, _, _ = driver.execute_query(
        "MATCH (c:Concept) RETURN c.id AS id, c.name AS name, c.description AS description")
    print(f"embedding {len(rows)} concepts with {config.EMBED_MODEL} ...")
    t = time.time()
    vecs = embed([concept_text(r["name"], r["description"]) for r in rows])
    dim = vecs.shape[1]
    for i in range(0, len(rows), BATCH):
        batch = [{"id": r["id"], "v": vecs[i + j].tolist()}
                 for j, r in enumerate(rows[i:i + BATCH])]
        driver.execute_query("UNWIND $rows AS row MATCH (c:Concept {id: row.id}) "
                             "CALL db.create.setNodeVectorProperty(c, 'embedding', row.v)",
                             rows=batch)
    driver.execute_query(
        f"""CREATE VECTOR INDEX {config.VECTOR_INDEX} IF NOT EXISTS
            FOR (c:Concept) ON c.embedding
            OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},
                                     `vector.similarity_function`: 'cosine'}}}}""")
    driver.execute_query("CALL db.awaitIndexes(600)")
    print(f"done in {time.time() - t:.0f}s: {len(rows)} embeddings (dim {dim}), "
          f"vector index '{config.VECTOR_INDEX}' online")
    driver.close()


if __name__ == "__main__":
    main()
