# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=24.17.0
ARG PNPM_VERSION=11.0.0

FROM node:${NODE_VERSION}-alpine3.24 AS base

ARG PNPM_VERSION
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /workspace

FROM base AS dependencies

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/frontend/package.json apps/frontend/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/site-blocks/package.json packages/site-blocks/package.json
COPY packages/ui/package.json packages/ui/package.json

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM dependencies AS builder

ARG DEPLOYMENT=core-only
ENV BACKEND_INTERNAL_URL=http://backend:8000
ENV NEXT_TELEMETRY_DISABLED=1

COPY tsconfig.base.json ./tsconfig.base.json
COPY apps/frontend ./apps/frontend
COPY deployments ./deployments
COPY packages ./packages

RUN node packages/contracts/scripts/deployment-render.mjs --profile ${DEPLOYMENT} && \
    pnpm --filter @saas-core/frontend build

FROM node:${NODE_VERSION}-alpine3.24 AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

RUN addgroup -g ${APP_GID} -S app && \
    adduser -u ${APP_UID} -S -D -H -G app app

ENV BACKEND_INTERNAL_URL=http://backend:8000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=3000

WORKDIR /app

COPY --from=builder --chown=app:app /workspace/apps/frontend/.next/standalone ./
COPY --from=builder --chown=app:app /workspace/apps/frontend/.next/static ./apps/frontend/.next/static

USER app:app

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["node", "apps/frontend/server.js"]
