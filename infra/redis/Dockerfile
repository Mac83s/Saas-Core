FROM ghcr.io/oliver006/redis_exporter:v1.84.0 AS exporter

FROM redis:8.2-alpine

COPY --from=exporter /redis_exporter /usr/local/bin/redis_exporter
COPY --chmod=0555 infra/redis/secret-entrypoint.sh /usr/local/bin/redis-secret-entrypoint

USER redis:redis

ENTRYPOINT ["redis-secret-entrypoint"]
CMD ["redis-server", "--appendonly", "yes"]
