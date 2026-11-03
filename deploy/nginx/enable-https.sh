#!/bin/sh
if [ -f /etc/nginx/certs/local.pem ] && [ -f /etc/nginx/certs/local-key.pem ]; then
    cp /etc/nginx/vz/https.conf /etc/nginx/conf.d/https.conf
    echo "HTTPS включён: порт 8443"
else
    rm -f /etc/nginx/conf.d/https.conf
    echo "Сертификатов в ./certs нет, работает только HTTP: порт 8000"
fi
