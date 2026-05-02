#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/../VERSION"

if [ ! -f "$VERSION_FILE" ]; then
    echo "ERROR: VERSION file not found at $VERSION_FILE"
    exit 1
fi

# Change to project root so git tag works
cd "$SCRIPT_DIR/.."

if [ $# -gt 0 ]; then
    # Manual version: user provides explicit version
    NEW_VERSION="$1"
    # Validate semver-ish format
    if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
        echo "ERROR: Version must be in X.Y.Z format (e.g. 0.2.5)"
        exit 1
    fi
else
    # Auto-bump: read current version and increment
    CURRENT="$(cat "$VERSION_FILE")"
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

    PATCH=$((PATCH + 1))
    if [ "$PATCH" -gt 100 ]; then
        PATCH=0
        MINOR=$((MINOR + 1))
    fi
    if [ "$MINOR" -gt 100 ]; then
        MINOR=0
        MAJOR=$((MAJOR + 1))
    fi
    if [ "$MAJOR" -gt 100 ]; then
        echo "ERROR: Version ceiling reached (100.100.100). Please specify a lower version manually."
        exit 1
    fi
    NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
fi

# Write new version
echo "$NEW_VERSION" > "$VERSION_FILE"
echo "✅ VERSION updated: $NEW_VERSION"

# Create git tag
git tag "v$NEW_VERSION"
echo "✅ Git tag created: v$NEW_VERSION"
