# Seraphim Model Server (TorchServe)

This directory contains a minimal TorchServe setup with a dummy text handler and a startup script that packages and registers two model versions (1.0 and 2.0) for canary testing.

- `handlers/custom_text_handler.py`: stateless handler that returns "positive" for even-length text and "negative" for odd.
- `config.properties`: TorchServe configuration addresses and model store path.
- `scripts/start.sh`: builds MAR files and registers versions via the management API, then tails logs.

Build locally (Apple Silicon):

```bash
# Ensure amd64 base is used; Docker Desktop will transparently emulate
DOCKER_DEFAULT_PLATFORM=linux/amd64 \
  docker buildx build --platform linux/amd64 -t seraphim-model-server:dev .

# Run it
docker run --rm -p 8080:8080 -p 8081:8081 -p 8082:8082 seraphim-model-server:dev
```

Model endpoints once running:
- Inference: POST http://localhost:8080/predictions/custom-text/1.0
- Inference: POST http://localhost:8080/predictions/custom-text/2.0
- Management: http://localhost:8081
