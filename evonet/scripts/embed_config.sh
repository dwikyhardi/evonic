#!/bin/bash
# embed_config.sh — Append a JSON config to an Evonet binary after the magic marker.
#
# Usage: ./scripts/embed_config.sh <binary> <config.json>
# Example: ./scripts/embed_config.sh evonet config.json
#
# The binary can then be distributed; Evonet will read the embedded config on startup.
# Config can still be overridden by ~/.evonet/config.yaml or CLI flags.

set -euo pipefail

BINARY="${1:?Usage: $0 <binary> <config.json>}"
CONFIG="${2:?Usage: $0 <binary> <config.json>}"

if [ ! -f "$BINARY" ]; then
    echo "Error: binary '$BINARY' not found" >&2
    exit 1
fi
if [ ! -f "$CONFIG" ]; then
    echo "Error: config '$CONFIG' not found" >&2
    exit 1
fi

# Magic marker: \x00\x00EVONET_CFG\x00\x00
MARKER=$'\x00\x00EVONET_CFG\x00\x00'

printf '%s' "$MARKER" >> "$BINARY"
cat "$CONFIG" >> "$BINARY"

echo "Embedded config from '$CONFIG' into '$BINARY'"
