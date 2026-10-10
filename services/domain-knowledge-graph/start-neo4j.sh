#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$HERE/neo4j.env" ]; then
  echo "NEO4J_PASSWORD=ali-$(openssl rand -hex 8)" > "$HERE/neo4j.env"
  echo "created neo4j.env with a random local password"
fi
source "$HERE/neo4j.env"
mkdir -p "$HOME/ali-kg/import" "$HOME/ali-kg/data"
if docker ps -a --format '{{.Names}}' | grep -qx ali-kg; then
  docker start ali-kg
else
  docker run -d --name ali-kg \
    -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 \
    -e NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
    -v "$HOME/ali-kg/data:/data" -v "$HOME/ali-kg/import:/import" \
    neo4j:5.26-community
fi
echo "waiting for Neo4j..."
until docker exec ali-kg cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1" >/dev/null 2>&1; do sleep 3; done
echo "Neo4j is up: http://localhost:7474"
