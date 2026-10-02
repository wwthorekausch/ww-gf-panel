#!/bin/bash
# Startet n8n-mcp (stdio) für https://n8n.web-wikinger.de; API-Key nur aus Keychain.
set -euo pipefail
export N8N_API_URL="https://n8n.web-wikinger.de"
N8N_API_KEY="$(security find-generic-password -s ww-gf-cockpit-n8n -w)"
export N8N_API_KEY
export MCP_MODE=stdio LOG_LEVEL=error DISABLE_CONSOLE_OUTPUT=true
exec pnpm dlx n8n-mcp
