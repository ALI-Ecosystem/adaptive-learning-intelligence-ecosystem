#!/bin/bash
# SCRUM-92: Postgres 16 for the learner graph log, on 127.0.0.1:5433 only.
# Creates postgres.env (git-ignored) with a random local password on the first run.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$HERE/postgres.env" ]; then
  echo "POSTGRES_PASSWORD=ali-$(openssl rand -hex 12)" > "$HERE/postgres.env"
  chmod 600 "$HERE/postgres.env"
  echo "created postgres.env with a random local password"
fi
source "$HERE/postgres.env"
mkdir -p "$HOME/ali-kg/postgres"
if docker ps -a --format '{{.Names}}' | grep -qx ali-lg; then
  docker start ali-lg >/dev/null
else
  docker run -d --name ali-lg \
    -p 127.0.0.1:5433:5432 \
    -e POSTGRES_USER=ali -e POSTGRES_DB=learner_graph \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -v "$HOME/ali-kg/postgres:/var/lib/postgresql/data" \
    postgres:16 >/dev/null
fi
echo "waiting for Postgres..."
until docker exec ali-lg pg_isready -U ali -d learner_graph >/dev/null 2>&1; do sleep 2; done
sleep 2
docker exec ali-lg psql -U ali -d learner_graph -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'learner_graph_test'" | grep -q 1 || \
  docker exec ali-lg psql -U ali -d learner_graph -c "CREATE DATABASE learner_graph_test" >/dev/null
echo "Postgres is up: 127.0.0.1:5433 (databases learner_graph, learner_graph_test)"
