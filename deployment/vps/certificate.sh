#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PSYCODE_HOST=${PSYCODE_HOST:-}
PSYCODE_CERT_KIND=ip
PSYCODE_CERT_EMAIL=
PSYCODE_ACME_TOS=1
if [[ -f /etc/psycode/deploy.conf ]]; then
  # shellcheck disable=SC1091
  . /etc/psycode/deploy.conf
fi
[[ "$PSYCODE_ACME_TOS" == 1 ]] || exit 2
lineage=psycode-ip
live=/etc/letsencrypt/live/$lineage
site=/etc/nginx/sites-available/psycode
template=/etc/psycode/nginx-https.conf
if [[ -s "$live/fullchain.pem" && -s "$live/privkey.pem" ]]; then
  /opt/certbot/bin/certbot renew --non-interactive --quiet --no-random-sleep-on-renew \
    --cert-name "$lineage" --deploy-hook 'systemctl reload nginx'
else
  if [[ -z "$PSYCODE_HOST" ]]; then
    echo 'Configure PSYCODE_HOST in /etc/psycode/deploy.conf before issuing the certificate.' >&2
    exit 2
  fi
  identity=(--domain "$PSYCODE_HOST")
  if [[ "$PSYCODE_CERT_KIND" == ip ]]; then
    identity=(--ip-address "$PSYCODE_HOST" --preferred-profile shortlived)
  fi
  contact=(--register-unsafely-without-email)
  if [[ -n "$PSYCODE_CERT_EMAIL" ]]; then
    contact=(--email "$PSYCODE_CERT_EMAIL")
  fi
  /opt/certbot/bin/certbot certonly --non-interactive --agree-tos \
    "${contact[@]}" --webroot -w /var/www/letsencrypt "${identity[@]}" --cert-name "$lineage"
fi

# Si el certificado ya existe pero la activación se interrumpió, completar Nginx.
if [[ -s "$template" ]] && ! cmp -s "$template" "$site"; then
  backup=$(mktemp)
  trap 'rm -f -- "$backup"' EXIT
  cp "$site" "$backup"
  install -m 644 "$template" "$site"
  if ! nginx -t || ! systemctl reload nginx; then
    install -m 644 "$backup" "$site"
    exit 1
  fi
fi
