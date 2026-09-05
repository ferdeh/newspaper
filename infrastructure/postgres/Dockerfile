FROM imresamu/postgis:16-3.5-alpine AS vector-builder

ARG PGVECTOR_VERSION=0.8.0
RUN apk add --no-cache build-base git clang19 llvm19 \
    && git clone --branch v${PGVECTOR_VERSION} --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector NO_BC=1 \
    && make -C /tmp/pgvector NO_BC=1 DESTDIR=/tmp/vector-install install

FROM imresamu/postgis:16-3.5-alpine
COPY --from=vector-builder /tmp/vector-install/usr/local /usr/local
