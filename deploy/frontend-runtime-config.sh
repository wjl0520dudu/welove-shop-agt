#!/bin/sh
set -eu

image_base_url=$(printf '%s' "${IMAGE_BASE_URL:-}" | sed 's/\\/\\\\/g; s/"/\\"/g')
sms_login_enabled=$(printf '%s' "${SMS_LOGIN_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')
cat > /usr/share/nginx/html/runtime-config.js <<EOF
window.__WLS_RUNTIME_CONFIG__ = {
  IMAGE_BASE_URL: "${image_base_url}",
  SMS_LOGIN_ENABLED: "${sms_login_enabled}"
};
EOF
