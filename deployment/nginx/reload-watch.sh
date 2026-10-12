#!/bin/sh
set -eu
# nginx starts with HTTP-only configuration if no certificate exists.
# Restart workers only when a valid TLS certificate or vhost changes.
(
    last=""
    while sleep 90; do
        if [ -f /etc/nginx/weave-conf/node.conf ] && \
           [ -f /etc/letsencrypt/live/weave-cbt-node/fullchain.pem ]; then
            current="$(
                cat /etc/nginx/weave-conf/node.conf \
                    /etc/letsencrypt/live/weave-cbt-node/fullchain.pem \
                    /etc/letsencrypt/live/weave-cbt-node/privkey.pem 2>/dev/null |
                    sha256sum | cut -d ' ' -f 1
            )"
            if [ "$current" != "$last" ] && nginx -t >/dev/null 2>&1; then
                nginx -s reload
                last="$current"
            fi
        fi
    done
) &
exec nginx -g 'daemon off;'
