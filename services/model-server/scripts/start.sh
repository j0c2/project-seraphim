#!/usr/bin/env bash
set -euo pipefail

# TorchServe startup script for Seraphim
# - Optionally builds and registers a sample text model with two versions
# - Starts TorchServe with configured addresses

MS_HOME=/home/model-server
MODEL_STORE="$MS_HOME/model-store"
CONFIG_FILE="$MS_HOME/config.properties"
HANDLER="$MS_HOME/handlers/custom_text_handler.py"

SAMPLE_MODEL=${SAMPLE_MODEL:-"true"}
SAMPLE_MODEL_VERSIONS=${SAMPLE_MODEL_VERSIONS:-"1.0,2.0"}

mkdir -p "$MODEL_STORE"

if [[ "${SAMPLE_MODEL}" == "true" || "${SAMPLE_MODEL}" == "1" || "${SAMPLE_MODEL}" == "True" ]]; then
  IFS=',' read -ra VERS <<<"${SAMPLE_MODEL_VERSIONS}"
  for V in "${VERS[@]}"; do
    V_TRIM=$(echo "$V" | xargs)
    [[ -z "$V_TRIM" ]] && continue
    MAR_NAME="custom-text-v${V_TRIM}.mar"
    DUMMY_PT="$MS_HOME/dummy-${V_TRIM}.pt"
    echo "Packaging sample model version ${V_TRIM} -> ${MAR_NAME}"
    touch "$DUMMY_PT"
    torch-model-archiver \
      --model-name custom-text \
      --version "${V_TRIM}" \
      --serialized-file "$DUMMY_PT" \
      --handler "$HANDLER" \
      --export-path "$MODEL_STORE" \
      --force
    # Rename default archive name to include version to avoid overwrite
    if [[ -f "$MODEL_STORE/custom-text.mar" ]]; then
      mv -f "$MODEL_STORE/custom-text.mar" "$MODEL_STORE/custom-text-v${V_TRIM}.mar"
    fi
  done
fi

# Start TorchServe in the background to allow registration
TORCHSERVE_ARGS=(
  --model-store "$MODEL_STORE"
  --ts-config "$CONFIG_FILE"
)

echo "Starting TorchServe..."
torchserve --start "${TORCHSERVE_ARGS[@]}"

# Wait for management port to be ready
MGMT_URL="http://localhost:8081"
for i in {1..30}; do
  if curl -sf "$MGMT_URL/ping" >/dev/null; then
    break
  fi
  sleep 1
  echo "Waiting for TorchServe management API... ($i)"
done

# Register sample models if present with initial workers
if compgen -G "$MODEL_STORE/custom-text-*.mar" > /dev/null; then
  for MAR in "$MODEL_STORE"/custom-text-*.mar; do
    MAR_NAME=$(basename "$MAR")
    # Extract version from filename (e.g., custom-text-v1.0.mar -> 1.0)
    VERSION=$(echo "$MAR_NAME" | sed -n 's/custom-text-v\(.*\)\.mar/\1/p')
    echo "Registering model $MAR_NAME (version: ${VERSION:-default})..."
    # Register with initial workers to avoid manual scaling
    RESPONSE=$(curl -sf -X POST "${MGMT_URL}/models?url=${MAR_NAME}&model_name=custom-text&initial_workers=1&synchronous=false" 2>&1)
    if [[ $? -eq 0 ]]; then
      echo "Model registered successfully: $RESPONSE"
    else
      echo "Failed to register model: $MAR_NAME"
    fi
  done
  # Wait for workers to be ready
  echo "Waiting for workers to initialize..."
  sleep 5
fi

# Tail logs to keep the container in the foreground
trap 'torchserve --stop || true' TERM INT

# TorchServe writes logs under /home/model-server/logs
LOG_DIR="$MS_HOME/logs"
mkdir -p "$LOG_DIR"

touch "$LOG_DIR/ts_console.log"

tail -n +1 -F "$LOG_DIR"/*.log &
WAITER=$!
wait $WAITER

