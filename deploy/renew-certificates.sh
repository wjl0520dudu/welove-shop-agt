#!/usr/bin/env sh
set -eu

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/welove-shop}"
COMPOSE_FILE="${DEPLOY_ROOT}/docker-compose.prod.yml"
PUBLIC_ENV="${DEPLOY_ROOT}/config/production.env"
SECRET_ENV="${DEPLOY_ROOT}/secrets/production.secrets.env"
CERTBOT_CONF="${DEPLOY_ROOT}/certbot/conf"
CERTBOT_WEBROOT="${DEPLOY_ROOT}/certbot/www"

if [ "${1:-}" = "--dry-run" ]; then
  CERTBOT_MODE="--dry-run"
else
  CERTBOT_MODE="--quiet"
fi

docker run --rm \
  -v "${CERTBOT_CONF}:/etc/letsencrypt" \
  -v "${CERTBOT_WEBROOT}:/var/www/certbot" \
  certbot/certbot:latest renew \
  --webroot --webroot-path /var/www/certbot \
  ${CERTBOT_MODE}

docker compose \
  --env-file "${PUBLIC_ENV}" \
  --env-file "${SECRET_ENV}" \
  -f "${COMPOSE_FILE}" \
  exec -T nginx nginx -t

docker compose \
  --env-file "${PUBLIC_ENV}" \
  --env-file "${SECRET_ENV}" \
  -f "${COMPOSE_FILE}" \
  exec -T nginx nginx -s reload
