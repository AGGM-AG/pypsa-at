FROM ghcr.io/prefix-dev/pixi:latest

RUN mkdir -p /mnt/storage

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates  \
    wget  \
    curl  \
    rsync  \
    git  \
    procps  \
    zsh  \
    build-essential  \
    python3-dev  \
    nano  \
    nodejs  \
    npm  \
    git-delta \
    gh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Instal oh-my-zsh with git plugin and default theme
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.2.1/zsh-in-docker.sh)" -- \
    -t robbyrussell \
    -p git

# Install starship
RUN curl -sS https://starship.rs/install.sh | sh -s -- -y

# install npm and claude  
RUN curl -fsSL https://claude.ai/install.sh | bash

