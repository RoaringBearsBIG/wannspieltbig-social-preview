#!/usr/bin/env bash
# Read-only health check for the wannspieltbig-social-preview service.
# Probes the container over dashboard-network (no published port).
set -u
FAIL=0
CONT=wannspieltbig-social-preview
CURL="docker run --rm --network dashboard-network curlimages/curl"
BASE="http://$CONT:8080"

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAIL=1; }

# 1. Container running
if docker inspect -f '{{.State.Running}}' "$CONT" 2>/dev/null | grep -q true; then
    pass "container $CONT running"
else
    fail "container $CONT not running"
    echo "ALL CHECKS FAILED"
    exit 1
fi

# 2. Health endpoint
if $CURL -sf "$BASE/healthz" >/dev/null; then pass "GET /healthz"; else fail "GET /healthz"; fi

# 3. List page renders cards
LIST_HTML=$($CURL -sf "$BASE/" 2>/dev/null || true)
if echo "$LIST_HTML" | grep -q 'class="card"'; then
    pass "GET / renders match cards"
else
    fail "GET / renders match cards (upstream match API down?)"
fi

# 4. Per-match probes (needs at least one match in the list)
MID=$(echo "$LIST_HTML" | grep -oE '/[0-9]+/image\.jpg' | head -1 | grep -oE '[0-9]+' || true)
if [ -z "$MID" ]; then
    echo "info  no match id found in list — skipping per-match probes"
else
    PAGE=$($CURL -sf "$BASE/$MID" 2>/dev/null || true)
    if echo "$PAGE" | grep -q 'og:image' && echo "$PAGE" | grep -q 'twitter:image'; then
        pass "GET /$MID carries og:image + twitter:image"
    else
        fail "GET /$MID carries og:image + twitter:image"
    fi

    for name in image.jpg image-twitter.jpg; do
        BODY=$($CURL -sf "$BASE/$MID/$name" 2>/dev/null || true)
        SIZE=${#BODY}
        MAGIC=$(printf '%s' "$BODY" | head -c 3 | od -An -tx1 | tr -d ' \n')
        if [ "$MAGIC" = "ffd8ff" ] && [ "$SIZE" -gt 10000 ]; then
            pass "GET /$MID/$name (JPEG, $SIZE B)"
        else
            fail "GET /$MID/$name (magic=$MAGIC size=$SIZE)"
        fi
    done

    # Variants must differ (twitter strips game logo + BO/date/time)
    A=$($CURL -sf "$BASE/$MID/image.jpg" 2>/dev/null || true)
    B=$($CURL -sf "$BASE/$MID/image-twitter.jpg" 2>/dev/null || true)
    if [ -n "$A" ] && [ -n "$B" ] && [ "$A" != "$B" ]; then
        pass "og and twitter variants differ"
    else
        fail "og and twitter variants are identical"
    fi

    # Legacy routes must be served (not redirected) — WhatsApp caches
    for legacy in "share/$MID/" "share/$MID/image.jpg" "share/$MID/image-twitter.jpg"; do
        CODE=$($CURL -s -o /dev/null -w '%{http_code}' "$BASE/$legacy" 2>/dev/null || true)
        if [ "$CODE" = "200" ]; then pass "GET /$legacy 200"; else fail "GET /$legacy ($CODE)"; fi
    done
fi

# 5. /share-match/ alias
CODE=$($CURL -s -o /dev/null -w '%{http_code}' "$BASE/share-match/" 2>/dev/null || true)
if [ "$CODE" = "200" ]; then pass "GET /share-match/ 200"; else fail "GET /share-match/ ($CODE)"; fi

# 6. Slug 301 (informational — depends on external API + jq-less python)
SLUG=$(curl -sf "https://wannspieltbig.de/api/match_upcoming/?limit=1" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['results'][0].get('slug',''))" 2>/dev/null || true)
if [ -n "$SLUG" ]; then
    RES=$($CURL -s -o /dev/null -w '%{http_code}' "$BASE/share/$SLUG/" 2>/dev/null || true)
    if [ "$RES" = "301" ]; then pass "GET /share/$SLUG/ 301"; else echo "info  GET /share/$SLUG/ ($RES)"; fi
else
    echo "info  slug 301 check skipped (external API unreachable)"
fi

# 7. Recent log errors
ERRS=$(docker logs "$CONT" --since 10m 2>&1 | grep -cE 'Traceback|ERROR' || true)
echo "info  ERROR/Traceback lines in last 10m of logs: $ERRS"

# 8. Optional UI screenshot of the list page
if [ "${SKIP_UI:-0}" != "1" ] && [ -f ".claude/skills/run-wannspieltbig-social-preview/verify_png.py" ]; then
    SHOTDIR=/tmp/wsp-shots
    mkdir -p "$SHOTDIR" && chmod 777 "$SHOTDIR"
    if docker run --rm --network dashboard-network -v "$SHOTDIR:/out" \
        zenika/alpine-chrome --no-sandbox --headless --disable-gpu --hide-scrollbars \
        --window-size=1400,900 --virtual-time-budget=10000 \
        --screenshot=/out/wsp-list.png "$BASE/" >/dev/null 2>&1; then
        if python3 ".claude/skills/run-wannspieltbig-social-preview/verify_png.py" "$SHOTDIR/wsp-list.png" >/dev/null 2>&1; then
            pass "UI screenshot rendered non-blank ($SHOTDIR/wsp-list.png)"
        else
            fail "UI screenshot blank — page did not render"
        fi
    else
        echo "info  UI screenshot skipped (alpine-chrome unavailable)"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "SOME CHECKS FAILED"
fi
exit "$FAIL"
