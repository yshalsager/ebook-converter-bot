FROM ghcr.io/yshalsager/calibre-with-kfx:20260531-0100@sha256:1a5eee11129fde123a85cbe243748fbdc8ffd097c5272e5f97bcc53f3af818d8

ARG PANDOC_VERSION=3.9.0.2

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:78bc42400d77b0678ba95765305c826652ed5431f399257271dda681d0318f03 /uv /uvx /bin/
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

COPY ebook_converter_bot/data/fonts/pdf /tmp/vendor-pdf-fonts
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends antiword ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/pandoc.tar.gz "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz"; \
    tar -xzf /tmp/pandoc.tar.gz --strip-components=1 -C /usr/local; \
    rm /tmp/pandoc.tar.gz; \
    pandoc --version; \
    mkdir -p /usr/local/share/fonts/ebook-converter-bot; \
    find /tmp/vendor-pdf-fonts -type f -name '*.ttf' -exec cp '{}' /usr/local/share/fonts/ebook-converter-bot/ ';'; \
    fc-cache -f -v; \
    rm -rf /tmp/vendor-pdf-fonts /root/.cache/fontconfig/* /root/.cache/calibre/*font*
USER calibre
# Override the entrypoint of the parent image
ENTRYPOINT [""]
