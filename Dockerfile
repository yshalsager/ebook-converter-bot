FROM ghcr.io/yshalsager/calibre-with-kfx:20260503-0052@sha256:698b0d28b370a1d1b41304d5b3f579f3b87b562119b0d0a9b9bf169e82b5213a

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /bin/
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
