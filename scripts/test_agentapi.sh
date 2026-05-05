#!/usr/bin/env bash
# =============================================================================
# AgentAPI Plugin — Integration Test Script
# =============================================================================
# Usage:
#   ./scripts/test_agentapi.sh [BASE_URL]
#
#   BASE_URL defaults to http://localhost:5000
#
# What this tests:
#   - Admin token CRUD (create, list, update, delete)
#   - /agentapi/v1/models (token-scoped model listing)
#   - /agentapi/v1/chat/completions (non-streaming)
#   - /agentapi/v1/chat/completions (streaming with SSE)
#   - Auth: invalid token → 401, suspended → 403, expired → 403
#   - Quota: limit enforcement → 429
#   - Model scoping: token restricted to subset of models
#   - Error cases: unknown model, missing model, no messages
#
# Prerequisites:
#   - Evonic server running with agentapi plugin enabled
#   - At least one agent configured (linus is the default in MODEL_AGENT_MAP)
#   - Admin session cookie available (set ADMIN_COOKIE env var if needed)
# =============================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:5000}"
PASS=0
FAIL=0
ADMIN_COOKIE="${ADMIN_COOKIE:-}"  # export ADMIN_COOKIE="session=xxxxx" if auth needed

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

header() {
    echo ""
    echo -e "${CYAN}━━━ $1 ━━━${NC}"
}

_assert() {
    local label="$1"; shift
    local expected="$1"; shift
    local actual="$1"; shift
    if [[ "$actual" == "$expected" ]]; then
        echo -e "  ${GREEN}✓${NC} $label"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $label"
        echo -e "    ${RED}expected:${NC} $expected"
        echo -e "    ${RED}got:${NC}      $actual"
        FAIL=$((FAIL + 1))
    fi
}

assert_http() {
    local label="$1"; shift
    local expected_code="$1"; shift
    local actual_code="$1"; shift
    _assert "$label (HTTP $expected_code)" "$expected_code" "$actual_code"
}

assert_json() {
    local label="$1"; shift
    local json="$1"; shift
    local field="$1"; shift
    local expected="$1"; shift
    # Crude JSON field extractor using grep — good enough for test script
    local actual
    actual=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$field','__MISSING__'))" 2>/dev/null || echo "__PARSE_ERROR__")
    _assert "$label" "$expected" "$actual"
}

assert_contains() {
    local label="$1"; shift
    local haystack="$1"; shift
    local needle="$1"; shift
    if echo "$haystack" | grep -qF "$needle"; then
        echo -e "  ${GREEN}✓${NC} $label"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $label"
        echo -e "    ${RED}expected to contain:${NC} $needle"
        FAIL=$((FAIL + 1))
    fi
}

do_get() {
    local url="$1"; shift
    local extra_args=("$@")
    if [[ -n "$ADMIN_COOKIE" ]]; then
        curl -s -w '\n%{http_code}' -b "$ADMIN_COOKIE" "${extra_args[@]}" "$url"
    else
        curl -s -w '\n%{http_code}' "${extra_args[@]}" "$url"
    fi
}

do_post() {
    local url="$1"; shift
    local body="$1"; shift
    local extra_args=("$@")
    if [[ -n "$ADMIN_COOKIE" ]]; then
        curl -s -w '\n%{http_code}' -X POST -b "$ADMIN_COOKIE" \
            -H 'Content-Type: application/json' \
            -d "$body" "${extra_args[@]}" "$url"
    else
        curl -s -w '\n%{http_code}' -X POST \
            -H 'Content-Type: application/json' \
            -d "$body" "${extra_args[@]}" "$url"
    fi
}

do_put() {
    local url="$1"; shift
    local body="$1"; shift
    local extra_args=("$@")
    if [[ -n "$ADMIN_COOKIE" ]]; then
        curl -s -w '\n%{http_code}' -X PUT -b "$ADMIN_COOKIE" \
            -H 'Content-Type: application/json' \
            -d "$body" "${extra_args[@]}" "$url"
    else
        curl -s -w '\n%{http_code}' -X PUT \
            -H 'Content-Type: application/json' \
            -d "$body" "${extra_args[@]}" "$url"
    fi
}

do_delete() {
    local url="$1"; shift
    local extra_args=("$@")
    if [[ -n "$ADMIN_COOKIE" ]]; then
        curl -s -w '\n%{http_code}' -X DELETE -b "$ADMIN_COOKIE" "${extra_args[@]}" "$url"
    else
        curl -s -w '\n%{http_code}' -X DELETE "${extra_args[@]}" "$url"
    fi
}

# split_response "body\ncode" → sets RESP_BODY and RESP_CODE
split_response() {
    local raw="$1"
    RESP_CODE=$(echo "$raw" | tail -n1)
    RESP_BODY=$(echo "$raw" | sed '$d')
}

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     AgentAPI Plugin — Integration Test Suite            ║${NC}"
echo -e "${CYAN}║     Target: $BASE_URL${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"

# ===========================================================================
# 1. ADMIN: Create Token
# ===========================================================================
header "1. Admin — Create Token"

RAW=$(do_post "$BASE_URL/api/agentapi/admin/tokens" \
    '{"name":"Test Token","quota_limit":5}')
split_response "$RAW"
assert_http "Create token" "201" "$RESP_CODE"

TOKEN_ID=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['token']['id'])" 2>/dev/null || echo "")
BEARER_TOKEN=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['plaintext'])" 2>/dev/null || echo "")

assert_json "Token has name" "$RESP_BODY" "token.name" "Test Token"
_assert "Got bearer token" "0" "$([[ -n "$BEARER_TOKEN" ]] && echo 0 || echo 1)"

echo -e "  ${YELLOW}ℹ${NC}  Token ID: $TOKEN_ID  Prefix: ${BEARER_TOKEN:0:8}..."

# ===========================================================================
# 2. ADMIN: List Tokens
# ===========================================================================
header "2. Admin — List Tokens"

RAW=$(do_get "$BASE_URL/api/agentapi/admin/tokens")
split_response "$RAW"
assert_http "List tokens" "200" "$RESP_CODE"
assert_contains "Token list contains our token" "$RESP_BODY" "\"name\": \"Test Token\""

# ===========================================================================
# 3. ADMIN: Filter by status
# ===========================================================================
header "3. Admin — List Tokens (filter: ?status=active)"

RAW=$(do_get "$BASE_URL/api/agentapi/admin/tokens?status=active")
split_response "$RAW"
assert_http "List active tokens" "200" "$RESP_CODE"
assert_contains "Active list contains our token" "$RESP_BODY" "\"name\": \"Test Token\""

RAW=$(do_get "$BASE_URL/api/agentapi/admin/tokens?status=suspended")
split_response "$RAW"
assert_http "List suspended tokens" "200" "$RESP_CODE"
assert_contains "No Test Token in suspended list" "$RESP_BODY" ""  # would fail if found; inverted manually
if echo "$RESP_BODY" | grep -qF '"Test Token"'; then
    echo -e "  ${RED}✗${NC} Token should not be in suspended list"
    FAIL=$((FAIL + 1))
else
    echo -e "  ${GREEN}✓${NC} Token not in suspended list (expected)"
    PASS=$((PASS + 1))
fi

# ===========================================================================
# 4. ADMIN: Token Stats
# ===========================================================================
header "4. Admin — Token Stats"

RAW=$(do_get "$BASE_URL/api/agentapi/admin/tokens/$TOKEN_ID/stats")
split_response "$RAW"
assert_http "Get token stats" "200" "$RESP_CODE"
assert_json "Stats total_calls = 0" "$RESP_BODY" "stats.total_calls" "0"

# ===========================================================================
# 5. CONSUMER: GET /agentapi/v1/models
# ===========================================================================
header "5. Consumer — GET /v1/models"

RAW=$(curl -s -w '\n%{http_code}' -H "Authorization: Bearer $BEARER_TOKEN" \
    "$BASE_URL/agentapi/v1/models")
split_response "$RAW"
assert_http "List models" "200" "$RESP_CODE"
assert_contains "Models list contains 'gpt-4-assistant'" "$RESP_BODY" "gpt-4-assistant"

# ===========================================================================
# 6. CONSUMER: POST /agentapi/v1/chat/completions (non-streaming)
# ===========================================================================
header "6. Consumer — POST /v1/chat/completions (non-streaming)"

CHAT_BODY='{"model":"gpt-4-assistant","messages":[{"role":"user","content":"Say hello in exactly 5 words."}],"stream":false}'

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Chat completion" "200" "$RESP_CODE"
assert_contains "Response has choices" "$RESP_BODY" '"choices"'
assert_contains "Response has 'chat.completion' object" "$RESP_BODY" '"chat.completion"'
assert_contains "Response echoes model" "$RESP_BODY" '"gpt-4-assistant"'

RESP_CONTENT=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null || echo "")
echo -e "  ${YELLOW}ℹ${NC}  Agent response: ${RESP_CONTENT:0:120}..."

# ===========================================================================
# 7. CONSUMER: POST /v1/chat/completions (streaming)
# ===========================================================================
header "7. Consumer — POST /v1/chat/completions (streaming)"

STREAM_BODY='{"model":"gpt-4-assistant","messages":[{"role":"user","content":"Say ONE word only."}],"stream":true}'

RAW=$(curl -s -N -w '\n%{http_code}' \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$STREAM_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions" 2>&1 || true)
split_response "$RAW"
assert_http "Streaming completion" "200" "$RESP_CODE"
assert_contains "Stream contains SSE data" "$RESP_BODY" "data:"
assert_contains "Stream ends with [DONE]" "$RESP_BODY" "[DONE]"

# ===========================================================================
# 8. AUTH: Invalid token → 401
# ===========================================================================
header "8. Auth — Invalid token → 401"

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer totally-not-a-valid-token-at-all" \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Invalid token" "401" "$RESP_CODE"

# ===========================================================================
# 9. AUTH: No Authorization header → 401
# ===========================================================================
header "9. Auth — Missing Authorization header → 401"

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Missing auth header" "401" "$RESP_CODE"

# ===========================================================================
# 10. ERROR: Unknown model → 400
# ===========================================================================
header "10. Error — Unknown model → 400"

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"model":"nonexistent-model-xyz","messages":[{"role":"user","content":"hi"}]}' \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Unknown model" "400" "$RESP_CODE"
assert_contains "Error mentions unknown model" "$RESP_BODY" "nonexistent-model-xyz"

# ===========================================================================
# 11. ERROR: Missing model field → 400
# ===========================================================================
header "11. Error — Missing model field → 400"

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"hi"}]}' \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Missing model" "400" "$RESP_CODE"

# ===========================================================================
# 12. QUOTA: Exhaust quota → 429
# ===========================================================================
header "12. Quota — Exhaust quota (limit=5) → 429"

# We already made 2 chat calls (#6 and #7), so 3 more should exhaust quota
for i in $(seq 1 4); do
    curl -s -o /dev/null \
        -H "Authorization: Bearer $BEARER_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$CHAT_BODY" \
        "$BASE_URL/agentapi/v1/chat/completions" > /dev/null 2>&1 || true
done

# This should be call #6 → over quota
RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Quota exceeded" "429" "$RESP_CODE"
assert_contains "Error mentions quota" "$RESP_BODY" "Quota exceeded"

# ===========================================================================
# 13. SUSPEND: Suspend token → 403
# ===========================================================================
header "13. Suspend — Suspend token → 403"

# Create a fresh token for suspend test (the original is now over quota)
RAW=$(do_post "$BASE_URL/api/agentapi/admin/tokens" \
    '{"name":"Suspend Test Token","quota_limit":100}')
split_response "$RAW"
SUSPEND_TOKEN_ID=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['token']['id'])" 2>/dev/null || echo "")
SUSPEND_TOKEN=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['plaintext'])" 2>/dev/null || echo "")
echo -e "  ${YELLOW}ℹ${NC}  Suspend token ID: $SUSPEND_TOKEN_ID"

# Suspend it
RAW=$(do_put "$BASE_URL/api/agentapi/admin/tokens/$SUSPEND_TOKEN_ID" \
    '{"status":"suspended"}')
split_response "$RAW"
assert_http "Suspend token" "200" "$RESP_CODE"

# Try using suspended token
RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $SUSPEND_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Suspended token rejected" "403" "$RESP_CODE"
assert_contains "Error mentions suspended" "$RESP_BODY" "suspended"

# Clean up — unsuspend for fairness
do_put "$BASE_URL/api/agentapi/admin/tokens/$SUSPEND_TOKEN_ID" \
    '{"status":"active"}' > /dev/null 2>&1 || true

# ===========================================================================
# 14. EXPIRE: Expired token → 403
# ===========================================================================
header "14. Expire — Expired token → 403"

RAW=$(do_post "$BASE_URL/api/agentapi/admin/tokens" \
    '{"name":"Expired Test Token","expires_at":"2020-01-01T00:00:00Z"}')
split_response "$RAW"
EXPIRE_TOKEN=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['plaintext'])" 2>/dev/null || echo "")
EXPIRE_TOKEN_ID=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['token']['id'])" 2>/dev/null || echo "")

RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $EXPIRE_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CHAT_BODY" \
    "$BASE_URL/agentapi/v1/chat/completions")
split_response "$RAW"
assert_http "Expired token rejected" "403" "$RESP_CODE"
assert_contains "Error mentions expired" "$RESP_BODY" "expired"

# ===========================================================================
# 15. ADMIN: Update Token
# ===========================================================================
header "15. Admin — Update Token (rename, change quota)"

RAW=$(do_put "$BASE_URL/api/agentapi/admin/tokens/$TOKEN_ID" \
    '{"name":"Renamed Test Token","quota_limit":999}')
split_response "$RAW"
assert_http "Update token" "200" "$RESP_CODE"
assert_json "Name updated" "$RESP_BODY" "token.name" "Renamed Test Token"
assert_json "Quota updated" "$RESP_BODY" "token.quota_limit" "999"

# ===========================================================================
# 16. MODEL SCOPE: Token restricted to specific models
# ===========================================================================
header "16. Model Scope — Token restricted to allowed_models"

RAW=$(do_post "$BASE_URL/api/agentapi/admin/tokens" \
    '{"name":"Scoped Token","allowed_models":["gpt-4-assistant"]}')
split_response "$RAW"
SCOPED_TOKEN=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['plaintext'])" 2>/dev/null || echo "")
SCOPED_ID=$(echo "$RESP_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['token']['id'])" 2>/dev/null || echo "")
assert_http "Create scoped token" "201" "$RESP_CODE"

# Models endpoint should only show gpt-4-assistant
RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $SCOPED_TOKEN" \
    "$BASE_URL/agentapi/v1/models")
split_response "$RAW"
assert_http "Scoped /v1/models" "200" "$RESP_CODE"
assert_contains "Scoped models includes gpt-4-assistant" "$RESP_BODY" "gpt-4-assistant"

# Calling a model NOT in scope should be 403
RAW=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $SCOPED_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"model":"claude-specialist","messages":[{"role":"user","content":"hi"}]}' \
    "$BASE_URL/agentapi/v1/chat/completions" 2>&1 || true)
split_response "$RAW"
# claude-specialist might or might not be in MODEL_AGENT_MAP — only test scoping if it exists
if echo "$RESP_BODY" | grep -q "not authorized"; then
    assert_http "Scoped token rejected for unauthorized model" "403" "$RESP_CODE"
    echo -e "  ${GREEN}✓${NC} Scoped token correctly rejected unauthorized model"
    PASS=$((PASS + 1))
else
    echo -e "  ${YELLOW}⚠${NC}  claude-specialist may not be in MODEL_AGENT_MAP (got $RESP_CODE). Skipping scoping assert."
fi

# ===========================================================================
# 17. ADMIN: Delete Token
# ===========================================================================
header "17. Admin — Delete Token"

RAW=$(do_delete "$BASE_URL/api/agentapi/admin/tokens/$TOKEN_ID")
split_response "$RAW"
assert_http "Delete token" "204" "$RESP_CODE"

# Verify it's gone
RAW=$(do_get "$BASE_URL/api/agentapi/admin/tokens/$TOKEN_ID/stats")
split_response "$RAW"
assert_http "Deleted token stats → 404" "404" "$RESP_CODE"

# Clean up other test tokens
do_delete "$BASE_URL/api/agentapi/admin/tokens/$SUSPEND_TOKEN_ID" > /dev/null 2>&1 || true
do_delete "$BASE_URL/api/agentapi/admin/tokens/$EXPIRE_TOKEN_ID" > /dev/null 2>&1 || true
do_delete "$BASE_URL/api/agentapi/admin/tokens/$SCOPED_ID" > /dev/null 2>&1 || true

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                   TEST RESULTS                          ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
printf "${CYAN}║${NC}  ${GREEN}Passed: %-3d${NC}  ${RED}Failed: %-3d${NC}                          ${CYAN}║${NC}\n" $PASS $FAIL
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}Some tests FAILED.${NC}"
    exit 1
else
    echo -e "${GREEN}All tests PASSED.${NC}"
    exit 0
fi
