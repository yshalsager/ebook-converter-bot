FROM ghcr.io/yshalsager/calibre-with-kfx:20260802-0254@sha256:8705cd0c05aeb16534837ac02754ecba3e2a171aa4a61861611de903158ddd43

ARG PANDOC_VERSION=3.10.2

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /bin/
USER root
ENV PATH="/opt/venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_NO_DEV=1 \
    UV_PROJECT_ENVIRONMENT="/opt/venv" \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /code
COPY pyproject.toml uv.lock /code/
RUN uv sync --frozen --no-install-project

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/pandoc.tar.gz "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz"; \
    tar -xzf /tmp/pandoc.tar.gz --strip-components=1 -C /usr/local; \
    rm /tmp/pandoc.tar.gz; \
    pandoc --version
USER calibre
# Override the entrypoint of the parent image
ENTRYPOINT [""]
