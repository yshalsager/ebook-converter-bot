FROM ubuntu:20.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.1.4 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
        PYSETUP_PATH="/opt/app" \
    VENV_PATH="/opt/app/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"
RUN export PATH=$PATH

# Install prerequisites
RUN apt-get update && \
    DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
                  python3.9 \
                  python3-pip \
                  python3-venv \
                  software-properties-common \
                  ca-certificates \
                  xvfb \   
                  wget \   
                  curl \   
                  gnupg2 \
                  xz-utils \
                  && rm -rf /var/lib/apt/lists/*

# Install wine
ARG WINE_BRANCH="stable"
RUN wget -nv -O- https://dl.winehq.org/wine-builds/winehq.key | APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 apt-key add - \
    && apt-add-repository "deb https://dl.winehq.org/wine-builds/ubuntu/ $(grep VERSION_CODENAME= /etc/os-release | cut -d= -f2) main" \
    && dpkg --add-architecture i386 \
    && apt-get update \
    && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends winehq-${WINE_BRANCH} \
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
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python3
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-dev

#COPY . .

#CMD ['python3', '-m', 'ebook_converter_bot']
