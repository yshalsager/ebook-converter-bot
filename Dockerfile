FROM ghcr.io/yshalsager/calibre-with-kfx:20251207-0029

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /code
COPY pyproject.toml uv.lock /code/
RUN uv sync --frozen --no-cache
ENV PATH="/code/.venv/bin:$PATH"

# Override the entrypoint of the parent image
ENTRYPOINT [""]
