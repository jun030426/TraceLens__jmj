# Learning-trace sandbox image (docs/06 실행과 시각화 명세). Build from the repository root:
#   docker build -f deploy/trace-sandbox/Dockerfile -t lerny-trace:20261110 .
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jdk-headless gcc libc6-dev gdb \
 && rm -rf /var/lib/apt/lists/*

COPY apps/api/lerny/__init__.py /opt/lerny/lerny/__init__.py
COPY apps/api/lerny/tracing /opt/lerny/lerny/tracing
RUN mkdir -p /opt/lerny/java-tracer \
 && javac -d /opt/lerny/java-tracer /opt/lerny/lerny/tracing/java/LernyJavaTracer.java

ENV PYTHONPATH=/opt/lerny \
    LERNY_JAVA_TRACER_DIR=/opt/lerny/java-tracer \
    PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /tmp
