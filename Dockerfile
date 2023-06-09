FROM ubuntu:22.04

# Configure Poetry
ENV POETRY_VERSION=1.5.1
ENV POETRY_HOME=/opt/poetry
ENV POETRY_CACHE_DIR=/opt/.cache
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PYSETUP_PATH="/opt/app"

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
ENV VENV_PATH="/opt/app/.venv"
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"
RUN export PATH=$PATH

# Install prerequisites
RUN apt-get update && \
    DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
                  software-properties-common \
                  ca-certificates \
                  xvfb \
                  libegl1 \
                  libopengl0 \
                  libxkbcommon-x11-0 \
                  libxcomposite-dev \
                  wget \
                  curl \
                  gnupg2 \
                  xz-utils \
                  && add-apt-repository ppa:deadsnakes/ppa -y \
                  && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends python3.11-full \
                  && rm -rf /var/lib/apt/lists/*

# Install wine
ARG WINE_BRANCH="stable"
RUN dpkg --add-architecture i386 \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/focal/winehq-focal.sources \
    && apt-get update \
    && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends winbind winehq-${WINE_BRANCH} \
    && rm -rf /var/lib/apt/lists/*

# Kindle support
COPY kp3.reg .
RUN wget -q https://d2bzeorukaqrvt.cloudfront.net/KindlePreviewerInstaller.exe \
    && DISPLAY=:0 WINEARCH=win64 WINEDEBUG=-all wine KindlePreviewerInstaller.exe /S \
    && cat kp3.reg >> /root/.wine/user.reg && rm *.exe

# calibre and its plugins are
WORKDIR /app
# KFX Output 272407
# KFX Input 291290
RUN wget -q -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sh /dev/stdin \
    && wget -q https://plugins.calibre-ebook.com/272407.zip \
    && calibre-customize -a 272407.zip \
    && wget -q https://plugins.calibre-ebook.com/291290.zip \
    && calibre-customize -a 291290.zip \
    && rm *.zip

# poetry
WORKDIR $PYSETUP_PATH
RUN curl -sSL https://install.python-poetry.org | python3 -
COPY poetry.lock pyproject.toml ./
RUN poetry install --only main

#COPY . .

#CMD ['python3', '-m', 'ebook_converter_bot']
