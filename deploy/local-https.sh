#!/bin/sh
set -e

cd "$(dirname "$0")/.."

IP="${1:-$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')}"
if [ -z "$IP" ]; then
    echo "Не удалось определить адрес в Wi-Fi. Укажите его явно: deploy/local-https.sh 192.168.1.20"
    exit 1
fi
if ! command -v mkcert >/dev/null 2>&1; then
    echo "Нужен mkcert: brew install mkcert"
    exit 1
fi

mkcert -install
mkcert -cert-file certs/local.pem -key-file certs/local-key.pem localhost 127.0.0.1 "$IP"

echo
echo "Сертификат готов. Впишите в .env:"
echo "  ALLOWED_HOSTS=localhost,127.0.0.1,$IP"
echo "  CSRF_TRUSTED_ORIGINS=https://localhost:8443,https://$IP:8443"
echo "  SITE_URL=https://$IP:8443"
echo
echo "Корневой сертификат для телефона: $(mkcert -CAROOT)/rootCA.pem"
echo "После правки .env: docker compose up -d && docker compose restart nginx"
echo "Адрес для телефона: https://$IP:8443"
