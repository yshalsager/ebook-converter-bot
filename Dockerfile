FROM ghcr.io/yshalsager/calibre-with-kfx:20260412-0043

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /code
COPY pyproject.toml uv.lock /code/
RUN uv sync --frozen --no-cache
ENV PATH="/code/.venv/bin:$PATH"

USER root
COPY ebook_converter_bot/data/fonts/pdf /tmp/vendor-pdf-fonts
RUN set -eux; \
    mkdir -p /usr/local/share/fonts/ebook-converter-bot; \
    find /tmp/vendor-pdf-fonts -type f -name '*.ttf' -exec cp '{}' /usr/local/share/fonts/ebook-converter-bot/ ';'; \
    fc-cache -f -v; \
    rm -rf /tmp/vendor-pdf-fonts /root/.cache/fontconfig/* /root/.cache/calibre/*font*
USER calibre
# Override the entrypoint of the parent image
ENTRYPOINT [""]
