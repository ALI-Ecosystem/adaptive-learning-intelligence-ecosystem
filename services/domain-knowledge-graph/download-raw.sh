#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/raw"
cd "$HERE/raw"
curl -fL -o part_0000.gz "https://openalex.s3.amazonaws.com/data/jsonl/concepts/updated_date=2026-09-23/part_0000.gz"
curl -fL -o FieldOfStudyChildren.txt.gz "https://archive.org/download/mag-2020-01-23/FieldOfStudyChildren.txt.gz"
curl -fL -o RelatedFieldOfStudy.txt.gz "https://archive.org/download/mag-2020-01-23/RelatedFieldOfStudy.txt.gz"
ls -la
