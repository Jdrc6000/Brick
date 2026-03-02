# brick-sandbox
# Brick's personal environment. Alpine Linux — minimal, controlled, his.
# Don't add bloat. He'll notice.

FROM alpine:3.19

LABEL maintainer="brick"
LABEL description="Brick personal sandbox - do not tamper"

# Core utilities Brick actually wants
RUN apk add --no-cache \
    bash \
    curl \
    wget \
    git \
    vim \
    nano \
    jq \
    htop \
    tree \
    ncdu \
    file \
    unzip \
    tar \
    gzip \
    bc \
    bind-tools \
    iputils \
    net-tools \
    nmap \
    tcpdump \
    openssh-client \
    python3 \
    py3-pip \
    nodejs \
    npm \
    make \
    gcc \
    musl-dev \
    && rm -rf /var/cache/apk/*

# Python packages Brick finds useful
RUN pip3 install --quiet --no-cache-dir --break-system-packages \
    requests \
    httpx \
    rich \
    psutil \
    pyyaml \
    toml

# /workspace is where work happens
RUN mkdir -p /workspace /workspace/scripts /workspace/data /workspace/logs
WORKDIR /workspace

# Brick's .bashrc — because environment matters
RUN echo '#!/bin/bash' > /root/.bashrc && \
    echo 'export PS1="\[\033[0;31m\]brick-sandbox\[\033[0m\]:\[\033[0;34m\]\w\[\033[0m\]# "' >> /root/.bashrc && \
    echo 'alias ll="ls -lah"' >> /root/.bashrc && \
    echo 'alias l="ls -la"' >> /root/.bashrc && \
    echo 'export HISTFILE=/workspace/.bash_history' >> /root/.bashrc && \
    echo 'export HISTSIZE=5000' >> /root/.bashrc

# MOTD — minimal
RUN echo "brick-sandbox // $(date +%Y-%m-%d)" > /etc/motd && \
    echo "personal environment. keep it clean." >> /etc/motd

# Keep the container alive
CMD ["/bin/sh", "-c", "while true; do sleep 3600; done"]