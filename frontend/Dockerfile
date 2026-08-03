# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS dependencies

ENV COREPACK_HOME=/corepack \
    PNPM_HOME=/pnpm
ENV PATH="$PNPM_HOME:$PATH"

WORKDIR /workspace/frontend

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN corepack pnpm@10.34.5 install --frozen-lockfile


FROM dependencies AS builder

ARG API_ORIGIN=http://backend-api:8000
ENV API_ORIGIN=$API_ORIGIN \
    NEXT_TELEMETRY_DISABLED=1

COPY . .
RUN corepack pnpm@10.34.5 build


FROM node:24-bookworm-slim AS runtime

ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

WORKDIR /workspace/frontend

COPY --from=builder --chown=node:node /workspace/frontend/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/frontend/.next/static ./.next/static

USER node

EXPOSE 3000

CMD ["node", "server.js"]
