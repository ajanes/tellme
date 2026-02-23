#!/usr/bin/env bash
set -euo pipefail

REGISTRY_HOST="gitlab.inf.unibz.it:4567"
IMAGE_LOCAL="tellme-app:latest"
PROJECT_NAME="tellme"
PLATFORMS="linux/amd64,linux/arm64"

if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "GITLAB_TOKEN is not set" >&2
  exit 1
fi

if [[ -z "${GITLAB_USER:-}" ]]; then
  echo "GITLAB_USER is not set" >&2
  exit 1
fi

IMAGE_REMOTE="$REGISTRY_HOST/$GITLAB_USER/$PROJECT_NAME:latest"

# Use a PAT with read_registry/write_registry scopes.
docker login "$REGISTRY_HOST" -u "$GITLAB_USER" --password-stdin <<<"$GITLAB_TOKEN"

docker buildx create --use --name tellme-builder >/dev/null 2>&1 || docker buildx use tellme-builder
docker buildx build --platform "$PLATFORMS" -t "$IMAGE_REMOTE" --push .
