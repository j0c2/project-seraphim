# Note: TorchServe upstream image may be amd64-only; using --platform in FROM
# allows explicit targeting and avoids platform mismatch warnings when building
# with buildx on Apple Silicon.
ARG TARGETPLATFORM
FROM --platform=${TARGETPLATFORM:-linux/amd64} pytorch/torchserve:0.11.0-cpu

USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/model-server
# Bring in handler code and config
COPY handlers/ /home/model-server/handlers/
COPY ts-config.properties /home/model-server/config.properties
COPY scripts/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
RUN mkdir -p /home/model-server/model-store

EXPOSE 8080 8081 8082
CMD ["/usr/local/bin/start.sh"]
