# The API (with the MCP server it starts on stdio) and the chat window, in one image.
# docker-compose.yml runs it twice (api, ui) next to Ollama on the GPU: make docker-up.
# The base image is pinned by digest, so a rebuild cannot pick up a different Python.
FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANONYMIZED_TELEMETRY=False

WORKDIR /srv

COPY requirements-app.txt .
RUN pip install -r requirements-app.txt && pip check

# Only what the app reads at run time (.dockerignore keeps .env, the database and the index out).
COPY app app
COPY mcp_server mcp_server
COPY ui ui
COPY prompts prompts
COPY data data
COPY docker docker

RUN useradd --create-home --uid 10001 app && mkdir -p runs .chroma && chown -R app /srv
USER app

EXPOSE 8000 8501
CMD ["python", "docker/start_api.py"]
