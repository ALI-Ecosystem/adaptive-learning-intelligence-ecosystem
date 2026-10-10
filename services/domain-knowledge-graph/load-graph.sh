#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/neo4j.env"
mkdir -p "$HOME/ali-kg/import"
cp "$HERE"/import/* "$HERE"/*.cypher "$HOME/ali-kg/import/"
echo "loading graph, this takes a few minutes..."
docker exec ali-kg cypher-shell -u neo4j -p "$NEO4J_PASSWORD" -f /import/load.cypher
echo "running demo queries..."
docker exec ali-kg cypher-shell -u neo4j -p "$NEO4J_PASSWORD" -f /import/demo.cypher | tee "$HERE/demo-output.txt"
