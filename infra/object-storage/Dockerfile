FROM chrislusf/seaweedfs:4.41@sha256:43b768cd62b00d132439cda881b93fd1adebf1b315e996e794087743821d771d

COPY --chmod=0555 infra/object-storage/secret-entrypoint.sh /usr/local/bin/object-storage-entrypoint

RUN addgroup -g 10001 -S app && \
    adduser -u 10001 -S -D -H -G app app && \
    chown -R app:app /data

USER app:app

ENTRYPOINT ["object-storage-entrypoint"]
