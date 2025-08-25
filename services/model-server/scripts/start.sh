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
fi

# Register sample models if present
if compgen -G "$MODEL_STORE/custom-text-*.mar" > /dev/null; then
  for MAR in "$MODEL_STORE"/custom-text-*.mar; do
    echo "Registering model from $MAR"
    curl -sf -X POST "${MGMT_URL}/models?url=$(basename "$MAR")" || true
  done
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

#!/usr/bin/env bash
set -euo pipefail
trap 'torchserve --stop || true' EXIT

SAMPLE_MODEL=${SAMPLE_MODEL:-false}
MODEL_NAME=${MODEL_NAME:-squeezenet}
MODEL_URL=${MODEL_URL:-https://torchserve.pytorch.org/mar_files/squeezenet1_1.mar}

# Start TorchServe
torchserve --start --model-store /home/model-server/model-store \
  --ts-config /home/model-server/config.properties

# Wait for management API to be ready
for i in {1..50}; do
  if curl -sf --max-time 0.3 http://127.0.0.1:8081/ping >/dev/null; then
    break
  fi
  sleep 0.2
done

if [[ "$SAMPLE_MODEL" == "true" ]]; then
  echo "Downloading sample model: $MODEL_NAME"
  curl -fsSL "$MODEL_URL" -o "/home/model-server/model-store/${MODEL_NAME}.mar"
  curl -fsSL -X POST \
    "http://127.0.0.1:8081/models?url=${MODEL_NAME}.mar&model_name=${MODEL_NAME}&initial_workers=1"
fi

# Stream logs
exec tail -F /home/model-server/logs/ts_log.log
