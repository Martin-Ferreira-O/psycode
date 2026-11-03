#!/usr/bin/env bash
set -euo pipefail
if [[ ! -f /etc/letsencrypt/live/psycode-ip/fullchain.pem ]]; then
  /opt/certbot/bin/certbot certonly --non-interactive --agree-tos \
    --register-unsafely-without-email --webroot -w /var/www/letsencrypt \
    --ip-address 144.22.56.52 --preferred-profile shortlived --cert-name psycode-ip
  install -m 644 /etc/psycode/nginx-https.conf /etc/nginx/sites-available/psycode
  nginx -t
  systemctl reload nginx
else
  /opt/certbot/bin/certbot renew --non-interactive --quiet --no-random-sleep-on-renew \
    --cert-name psycode-ip --deploy-hook 'systemctl reload nginx'
fi
