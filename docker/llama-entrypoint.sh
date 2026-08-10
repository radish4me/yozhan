#!/usr/bin/env bash
set -euo pipefail

# Maps the friendly model id (LOCAL_DEFAULT_MODEL) to a HF repo:quant pair.
# Kept in sync with config/providers.yaml's providers.local.models list.
case "${LOCAL_DEFAULT_MODEL:-qwen3.5-0.8b}" in
  qwen3.5-0.8b)   HF_REF="Qwen/Qwen3.5-0.8B-GGUF:Q4_K_M" ;;
  lfm2.5)         HF_REF="LiquidAI/LFM2.5-GGUF:Q4_K_M" ;;
  agents-a1-4b)   HF_REF="SomeOrg/Agents-A1-4B-Q4_K_M-GGUF" ;;
  *)              HF_REF="${LOCAL_DEFAULT_MODEL}" ;;  # allow raw "repo:quant" override
esac

exec llama-server \
  -hf "${HF_REF}" \
  --host 0.0.0.0 \
  --port 8080 \
  "$@"
