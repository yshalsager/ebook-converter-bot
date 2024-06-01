FROM ghcr.io/yshalsager/calibre-with-kfx:20240526-0019

# Configure Poetry
ENV POETRY_VERSION=1.6.1
ENV POETRY_HOME=/app/poetry
ENV POETRY_CACHE_DIR=/app/.cache
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PYSETUP_PATH="/app"

# pip
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV PIP_DEFAULT_TIMEOUT=100

# python
# Don't buffer `stdout`:
ENV PYTHONUNBUFFERED=1
# Don't create `.pyc` files:
ENV PYTHONDONTWRITEBYTECODE=1

# Configure Paths
ENV VENV_PATH="/app/.venv"
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"
RUN export PATH=$PATH

# poetry
WORKDIR $PYSETUP_PATH
RUN curl -sSL https://install.python-poetry.org | python3 -
COPY poetry.lock pyproject.toml ./
RUN poetry install --only main

#COPY . .

# Override the entrypoint of the parent image
ENTRYPOINT [""]
