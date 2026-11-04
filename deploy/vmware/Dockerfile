# Build/validation tools only. Runs unprivileged QEMU TCG, never a host hypervisor.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    qemu-utils qemu-system-x86 ovmf xorriso openssh-client openssl python3 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
