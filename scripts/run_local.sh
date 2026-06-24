#!/usr/bin/env bash
set -euo pipefail

uvicorn callerbot.server:app --host 0.0.0.0 --port 8000
