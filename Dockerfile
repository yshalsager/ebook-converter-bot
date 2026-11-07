FROM ghcr.io/yshalsager/calibre-with-kfx:20261106-143606@sha256:9091972117b5894ff570e2657bed00f4f5a982bf080ff414edaa09fa6c8bd6ba

ARG PANDOC_VERSION=3.13

COPY --from=python:3.15.2-slim-trixie@sha256:fd2aef5e0d8438208de9fe154ab5b331a2428fc0c9838d41611e611fd7a80d85 /usr/local/ /usr/local/
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /bin/
USER root
ENV PATH="/opt/venv/bin:$PATH" \
    LANG=C.UTF-8 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_NO_DEV=1 \
    UV_PROJECT_ENVIRONMENT="/opt/venv" \
    UV_PYTHON_DOWNLOADS=0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl libmpdec4; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/pandoc.tar.gz "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz"; \
    tar -xzf /tmp/pandoc.tar.gz --strip-components=1 -C /usr/local; \
    rm /tmp/pandoc.tar.gz; \
    pandoc --version

WORKDIR /code
COPY pyproject.toml uv.lock /code/
RUN uv sync --frozen --no-install-project

USER calibre
RUN boko --version \
    && calibre-customize --disable-plugin "KFX Output" \
    && calibre-debug -c "import sys; from calibre.customize.ui import plugin_for_output_format; p = plugin_for_output_format('kfx'); sys.exit(0 if p is not None and p.name == 'kfxgen' else 'The base image must provide kfxgen')"
# Override the entrypoint of the parent image
ENTRYPOINT [""]
