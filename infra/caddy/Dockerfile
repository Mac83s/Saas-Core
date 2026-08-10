FROM caddy:2.11.4-alpine

ARG APP_UID=10001
ARG APP_GID=10001

RUN addgroup -g ${APP_GID} -S app && \
    adduser -u ${APP_UID} -S -D -H -G app app && \
    setcap -r /usr/bin/caddy && \
    chown -R app:app /config /data

USER app:app
