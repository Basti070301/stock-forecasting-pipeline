#!/bin/sh
set -eu
umask 077
case "${SI_PUBLIC_HOST:-}" in ''|*[!a-z0-9.-]*) echo 'SI_PUBLIC_HOST: lowercase hostname or IPv4 required' >&2; exit 1;; esac
case "${SI_AUTH_USER:-}" in ''|*[!a-zA-Z0-9_-]*) echo 'Invalid SI_AUTH_USER' >&2; exit 1;; esac
case "${SI_PROXY_TOKEN:-}" in ''|*[!a-f0-9]*) echo 'SI_PROXY_TOKEN must be hexadecimal' >&2; exit 1;; esac
[ "${#SI_PROXY_TOKEN}" -ge 32 ] || { echo 'SI_PROXY_TOKEN too short' >&2; exit 1; }
[ "${#SI_AUTH_PASSWORD}" -ge 20 ] || { echo 'SI_AUTH_PASSWORD too short' >&2; exit 1; }
mkdir -p /tmp/si-nginx
printf '%s\n' "$SI_AUTH_PASSWORD" | htpasswd -niB "$SI_AUTH_USER" > /tmp/si-nginx/htpasswd
unset SI_AUTH_PASSWORD
if [ ! -s /var/lib/si-tls/server.crt ] && [ ! -s /var/lib/si-tls/server.key ]; then
    case "$SI_PUBLIC_HOST" in *[!0-9.]*) san="DNS:$SI_PUBLIC_HOST";; *) san="IP:$SI_PUBLIC_HOST";; esac
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 -keyout /var/lib/si-tls/server.key -out /var/lib/si-tls/server.crt -subj "/CN=$SI_PUBLIC_HOST" -addext "subjectAltName=$san" 2>/dev/null
fi
[ -s /var/lib/si-tls/server.crt ] && [ -s /var/lib/si-tls/server.key ] || { echo 'TLS volume incomplete; install matching certificate/key' >&2; exit 1; }
envsubst '${SI_PUBLIC_HOST} ${SI_PROXY_TOKEN}' < /etc/si/site.conf.template > /tmp/si-nginx/site.conf
nginx -t
exec nginx -g 'daemon off;'
