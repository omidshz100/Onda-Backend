#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )); then
  echo "Usage: $0 <resource-group> <app-name>" >&2
  exit 2
fi

resource_group=$1
app_name=$2
project_root=$(cd "$(dirname "$0")/.." && pwd)
archive_path=/tmp/onda-backend-deploy.zip

cd "$project_root"
uv run pytest
uv run ruff check .
uv export --frozen --no-dev --no-emit-project --output-file requirements.txt >/dev/null

zip -q -FS -r "$archive_path" \
  app migrations alembic.ini pyproject.toml uv.lock requirements.txt \
  -x '*__pycache__*' '*.pyc'

az webapp deploy \
  --resource-group "$resource_group" \
  --name "$app_name" \
  --src-path "$archive_path" \
  --type zip

echo "Uploaded tested backend code to ${app_name}."
