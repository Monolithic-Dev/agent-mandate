# Agent Mandate API and MCP servers. Multi-stage, non-root, no build tools in the final image.
#   docker build -t agent-mandate .
#   docker run --rm -p 8000:8000 -e MANDATE_API_KEY=... -e FALKORDB_HOST=... agent-mandate

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 mandate \
 && useradd --system --uid 10001 --gid mandate --home-dir /nonexistent --no-create-home mandate
COPY --from=build /opt/venv /opt/venv
USER 10001:10001
EXPOSE 8000
# /readyz needs a real graph read, so an unhealthy database takes the container out of rotation.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "--factory", "mandate.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
