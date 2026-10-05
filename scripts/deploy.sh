#!/usr/bin/env bash
set -Eeuo pipefail

LAB_IMAGE_URI="${1:?Usage: deploy.sh IMAGE_URI}"
LAB_REGION="ap-southeast-1"
LAB_REGISTRY="059488919510.dkr.ecr.ap-southeast-1.amazonaws.com"

case "$LAB_IMAGE_URI" in
  "$LAB_REGISTRY/aws-cicd-lab:"?*) ;;
  *) echo "Expected a tagged image from the lab ECR repository." >&2; exit 1 ;;
esac

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root on the lab EC2 instance." >&2
  exit 1
fi

# Only one deployment may change containers at a time.
exec 9>/var/lock/cicd-lab-deploy.lock
flock -n 9 || { echo "Another deployment is running." >&2; exit 1; }

wait_for_health() {
  for LAB_ATTEMPT in {1..15}; do
    if docker exec cicd-lab python -c '
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as response:
    assert response.status == 200
    assert json.load(response)["status"] == "ok"
' >/dev/null 2>&1 &&
      curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback() {
  trap - ERR INT TERM
  echo "Deployment failed. Attempting to restore the previous container." >&2
  docker logs --tail 30 cicd-lab || true
  docker rm -f cicd-lab || true

  if docker rename cicd-lab-previous cicd-lab &&
    docker start cicd-lab && wait_for_health; then
    echo "Previous container restored and healthy." >&2
  else
    echo "Rollback failed. Inspect the instance through Session Manager." >&2
  fi
  exit 1
}

# This lab already has a manually deployed container.
docker inspect cicd-lab >/dev/null
if docker inspect cicd-lab-previous >/dev/null 2>&1; then
  echo "A previous deployment needs inspection: cicd-lab-previous exists." >&2
  exit 1
fi

# Download before interrupting the running application.
aws ecr get-login-password --region "$LAB_REGION" |
  docker login --username AWS --password-stdin "$LAB_REGISTRY"
docker pull "$LAB_IMAGE_URI"

docker rename cicd-lab cicd-lab-previous
trap rollback ERR INT TERM
docker stop cicd-lab-previous

docker run -d \
  --name cicd-lab \
  --restart unless-stopped \
  --log-driver local \
  -p 8080:8080 \
  "$LAB_IMAGE_URI"

if ! wait_for_health; then
  rollback
fi

# The new container is healthy; the old one can now be removed.
trap - ERR INT TERM
docker rm cicd-lab-previous
echo "Deployment succeeded: $LAB_IMAGE_URI"
