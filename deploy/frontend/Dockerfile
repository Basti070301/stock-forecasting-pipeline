# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS build
WORKDIR /build
RUN npm install --global pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:15c994d10d6d78658721c3bcafff14cb281fba2a4bdf9d5ba92c416a472516e3
USER root
RUN apk add --no-cache openssl apache2-utils && mkdir -p /var/lib/si-tls && chown 101:101 /var/lib/si-tls
COPY --from=build /build/dist /usr/share/nginx/html
COPY deploy/frontend/nginx.conf /etc/nginx/nginx.conf
COPY deploy/frontend/site.conf.template /etc/si/site.conf.template
COPY --chmod=755 deploy/frontend/start.sh /usr/local/bin/si-start
USER 101:101
EXPOSE 8443
ENTRYPOINT ["/usr/local/bin/si-start"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8081/healthz || exit 1
