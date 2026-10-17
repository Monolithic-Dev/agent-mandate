# Agent Mandate in ONE container: FalkorDB, the API and the web console, for a host that runs a
# single free web service (Render's free plan, Hugging Face Spaces, Fly's free allowance).
# The database is in memory and starts empty, so it is a demo deployment: the start script
# seeds the demo tenant and creates the first admin each time the container starts.
#
#   docker build -f deploy/free/Dockerfile -t agent-mandate-free .
#   docker run --rm -p 10000:10000 -e MANDATE_ADMIN_EMAIL=you@example.com \
#     -e MANDATE_ADMIN_PASSWORD='a long passphrase' agent-mandate-free
FROM node:24-alpine AS console
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/tsconfig.json ui/vite.config.ts ui/index.html ./
COPY ui/src ./src
RUN npx vite build

FROM python:3.12-slim-trixie AS api
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# Only the database's binary and module are taken from its image (same Debian release).
FROM falkordb/falkordb:6.0.1 AS db

FROM python:3.12-slim-trixie
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MANDATE_STATIC_DIR=/opt/console MANDATE_RESULTS_DIR=/opt/results PORT=10000
RUN groupadd --system --gid 10001 mandate \
 && useradd --system --uid 10001 --gid mandate --home-dir /nonexistent --no-create-home mandate
COPY --from=db /usr/local/bin/redis-server /usr/local/bin/redis-cli /usr/local/bin/
COPY --from=db /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so
COPY --from=api /opt/venv /opt/venv
COPY --from=console /ui/dist /opt/console
COPY docs/results /opt/results
COPY deploy/free/start.sh /usr/local/bin/mandate-start
RUN chmod 755 /usr/local/bin/mandate-start
USER 10001:10001
EXPOSE 10000
HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=5 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['PORT'], timeout=2).status == 200 else 1)"
CMD ["mandate-start"]
