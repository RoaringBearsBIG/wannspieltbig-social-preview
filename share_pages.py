"""Public share pages for upcoming BIG matches (standalone service).

Served by this service on the bot.wannspieltbig.de subdomain (nginx proxies
the whole host except /api/). Moved out of RoaringBot in 2026-08 — the bot
keeps only the pure image composition (core/versus_image.py) for its Discord
images; changes to the composition must be mirrored there.

Flow: the operator opens /, taps "Share to WhatsApp" on a match → only the
match-page URL is shared → WhatsApp/Bluesky/Discord generate a link preview
from the page's og: tags (versus image via og:image), Twitter/X from
twitter:image → tapping the link opens the page, which redirects to the
specific match page on wannspieltbig.de.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from aiohttp import web
from aiohttp import ClientSession, ClientTimeout
from PIL import Image

from config import config
from image import compose_versus_image, _crop_visible, _make_tba_placeholder

log = logging.getLogger("social-preview.share")

BERLIN_TZ = ZoneInfo("Europe/Berlin")
GAME_LABELS = {"cs": "CS", "lol": "LoL", "tm": "TM"}
API_PAGE_SIZE = 20

# Image variants: "og" is the full composition for WhatsApp/Bluesky/Discord,
# "twitter" strips the game logo and BO/date/time (tournament stays).
VARIANTS = ("og", "twitter")

_session: Optional[ClientSession] = None


def _http_session() -> ClientSession:
    """Shared 10 s-timeout session. Short timeout matters: WhatsApp's
    crawler drops the image if the og:image fetch takes too long."""
    global _session
    if _session is None or _session.closed:
        _session = ClientSession(
            timeout=ClientTimeout(total=10),
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        )
    return _session


async def close_http_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()


async def _get_json(url: str) -> Optional[dict]:
    """GET + parse JSON; None on any failure."""
    try:
        async with _http_session().get(url) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except Exception:
        log.exception("share: fetch failed for %s", url)
        return None


# ── Handlers ────────────────────────────────────────────────────────────────


async def handle_health(request: web.Request) -> web.Response:
    """Liveness probe for the Docker HEALTHCHECK."""
    return web.Response(text="ok")


async def handle_share_list(request: web.Request) -> web.Response:
    """List page: one card per upcoming match with a Share-to-WhatsApp button."""
    matches = await _fetch_upcoming_matches()
    # Pre-warm versus images (both variants) in the background, so the first
    # WhatsApp/X crawl of a match URL hits a warm JPEG instead of a slow cold
    # logo fetch (crawlers drop the image if the fetch takes too long).
    for m in matches:
        if m.get("slug"):
            for variant in VARIANTS:
                asyncio.create_task(_warm_image(m, variant))
    cards = "\n".join(_build_card(m) for m in matches)
    html = _LIST_HTML.replace("<!-- CARDS -->", cards)
    return web.Response(text=html, content_type="text/html")


async def handle_share_match(request: web.Request) -> web.Response:
    """Match page: og:/twitter: tags for the social previews, then redirect
    to the wannspieltbig match page. Crawlers parse the meta tags from this
    response; real visitors are redirected via JS (no meta refresh —
    WhatsApp follows it)."""
    match = await _find_match_by_id(int(request.match_info["match_id"]))
    if match is None:
        return web.Response(text="Match not found", status=404)
    return web.Response(
        text=_match_page_html(match), content_type="text/html"
    )


async def handle_share_image(request: web.Request) -> web.Response:
    """Versus JPEG for og:image — full composition, 2:1."""
    return await _serve_image(request, "og")


async def handle_share_twitter_image(request: web.Request) -> web.Response:
    """Versus JPEG for twitter:image — no game logo, no BO/date/time."""
    return await _serve_image(request, "twitter")


async def _serve_image(request: web.Request, variant: str) -> web.Response:
    match = await _find_match_by_id(int(request.match_info["match_id"]))
    if match is None:
        return web.Response(status=404)
    try:
        jpg = await _ensure_image(match, variant)
    except Exception:
        log.exception("share: %s image build failed for %s", variant, match.get("slug"))
        return web.Response(status=500)
    return web.Response(
        body=jpg,
        content_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def handle_share_slug_redirect(request: web.Request) -> web.Response:
    """Compatibility: old slug-based URLs 301 to their id-based URL, so
    already-shared messages keep working (WhatsApp previews too)."""
    match = await _find_match_by_slug(request.match_info["slug"])
    if match is None:
        return web.Response(status=404)
    if request.path.endswith("/image-twitter.jpg"):
        target = _twitter_image_url(match["id"])
    elif request.path.endswith("/image.jpg"):
        target = _image_url(match["id"])
    else:
        target = _share_url(match["id"])
    return web.Response(status=301, headers={"Location": target})


# /share-match/ serves the same overview as /share/: one card per upcoming
# match, each sharing its /share/{slug}/ page (WhatsApp embed picture via
# the og: tags on that page). Kept under the old URL the operator knows.
handle_share_next_match = handle_share_list


# ── Data ────────────────────────────────────────────────────────────────────


async def _fetch_matches(upcoming_only: bool) -> list:
    """Fetch non-cancelled matches from wannspieltbig, sorted by kickoff."""
    url = config.esports_api_url.rstrip("/") + f"/?limit={API_PAGE_SIZE}"
    data = await _get_json(url)
    if not data:
        return []

    matches = [m for m in data.get("results", []) if not m.get("cancelled")]
    if upcoming_only:
        matches = [m for m in matches if not m.get("has_ended")]
    matches.sort(
        key=lambda m: _parse_match_time(m.get("first_map_at", ""))[0]
        or datetime.max.replace(tzinfo=BERLIN_TZ)
    )
    return matches


async def _fetch_upcoming_matches() -> list:
    """Upcoming non-cancelled matches, sorted by kickoff."""
    return await _fetch_matches(upcoming_only=True)


async def _fetch_all_matches() -> list:
    """Full list (incl. ended matches) — /share/{id}/ keeps working for past
    matches, so previously shared games can be re-shared."""
    return await _fetch_matches(upcoming_only=False)


async def _find_match_by_id(match_id: int) -> Optional[dict]:
    for m in await _fetch_all_matches():
        if m.get("id") == match_id:
            return m
    return None


async def _find_match_by_slug(slug: str) -> Optional[dict]:
    for m in await _fetch_all_matches():
        if m.get("slug") == slug:
            return m
    return None


def _parse_match_time(first_map_at: str):
    """Parse '2026-08-09T14:45:00+02:00' → (Berlin datetime, display label)."""
    try:
        ts = re.sub(r"[+-]\d{2}:\d{2}$", "", first_map_at)
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=BERLIN_TZ)
    except (ValueError, TypeError):
        return None, first_map_at or ""

    today = datetime.now(BERLIN_TZ).date()
    d = dt.date()
    if d == today:
        label = "Today"
    elif d == today + timedelta(days=1):
        label = "Tomorrow"
    else:
        label = dt.strftime("%d %b")
    return dt, f"{label} {dt.strftime('%H:%M')}"


# ── HTML builders ───────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Escape text for safe inclusion in an HTML attribute."""
    return (text or "").replace("&", "&amp;").replace('"', "&quot;")


def _match_info(m: dict) -> tuple:
    """Extract display info from an API match dict."""
    lineup_b = m.get("lineup_b") or {}
    team_b = (lineup_b.get("team") or {}).get("name")
    lineup_a = m.get("lineup_a") or {}
    team_a = (lineup_a.get("team") or {}).get("name") or "BIG"

    game = (m.get("game") or "").lower()
    game_label = GAME_LABELS.get(game, game.upper())
    bo = f"BO{m['bestof']}" if m.get("bestof") else ""
    tournament = (m.get("tournament") or {}).get("name") or ""
    match_url = m.get("html_detail_url") or "https://wannspieltbig.de/"
    _, time_str = _parse_match_time(m.get("first_map_at", ""))

    title = f"{team_a} vs. {team_b}" if team_b else f"{team_a} vs. TBA"
    bo_line = f"{game_label} · {bo}" if bo else game_label
    return title, bo_line, tournament, time_str, match_url


def _share_url(match_id: int) -> str:
    return f"{config.share_base_url}/{match_id}"


def _image_url(match_id: int) -> str:
    return f"{config.share_base_url}/{match_id}/image.jpg"


def _twitter_image_url(match_id: int) -> str:
    return f"{config.share_base_url}/{match_id}/image-twitter.jpg"


def _build_card(m: dict) -> str:
    """One list-page card; the share button posts the match info as plain
    text plus the match-page URL (WhatsApp renders the preview from the og:
    tags on that page)."""
    title, bo_line, tournament, time_str, _ = _match_info(m)
    share_url = _share_url(m["id"])
    # WhatsApp SVG icon (official brand icon, simplified)
    wa_icon = '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>'
    # Clipboard copy icon
    copy_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    check_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    return f"""<div class="card">
<img class="versus-img" src="/{m['id']}/image.jpg" alt="{_esc(title)}">
<div class="info">{_esc(title)} &middot; {_esc(bo_line)}</div>
<div class="info">{_esc(tournament)} &middot; {_esc(time_str)}</div>
<div class="btn-row">
<button class="btn-wa" type="button" data-url="{_esc(share_url)}">{wa_icon} WhatsApp</button>
<button class="btn-copy" type="button" data-url="{_esc(share_url)}" data-wa-icon="{_esc(wa_icon)}" data-copy-icon="{_esc(copy_icon)}" data-check-icon="{_esc(check_icon)}">{copy_icon} Copy</button>
</div>
</div>"""


def _match_page_html(m: dict) -> str:
    """Match page: og: tags (WhatsApp/Bluesky/Discord preview), twitter:image
    (X preview, stripped variant) + redirect to wannspieltbig."""
    title, bo_line, tournament, time_str, match_url = _match_info(m)
    og_title = f"{title} · {time_str} · {bo_line}"
    og_image = _image_url(m["id"])
    twitter_image = _twitter_image_url(m["id"])
    share_url = _share_url(m["id"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)} – {_esc(time_str)}</title>
<meta property="og:title" content="{_esc(og_title)}">
<meta property="og:description" content="{_esc(tournament)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{_esc(share_url)}">
<meta property="og:image" content="{_esc(og_image)}">
<meta property="og:image:width" content="1600">
<meta property="og:image:height" content="800">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{_esc(twitter_image)}">
<script>location.replace({json.dumps(match_url)});</script>
</head>
<body style="margin:0;background:#0f0f0f;color:#ccc;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh">
<p style="text-align:center">Opening match page&hellip;<br>
<a href="{_esc(match_url)}" style="color:#6c9bcf">{_esc(match_url)}</a></p>
</body>
</html>"""


# ── Image building & cache ──────────────────────────────────────────────────

# Built JPEGs, keyed by (variant, slug) → (content signature, bytes). The
# signature changes on reschedule/opponent swap, so a stale cache entry is
# rebuilt. Without this, every request (e.g. a WhatsApp crawl after a
# restart) would re-download the opponent logo and risk timing out the
# crawler. JPEG is used instead of PNG to stay under WhatsApp's ~300 KB
# og:image limit. Bound covers 2 variants × 20 API matches with slack.
_image_cache: dict[tuple[str, str], tuple[str, bytes]] = {}


def _image_signature(m: dict) -> str:
    """Content key for the image cache: rebuild when kickoff, tournament,
    opponent logo, or current Berlin date changes.  Including today's date
    ensures the "Today"/"Tomorrow" label baked into the JPEG is always
    correct across midnight (BIG logo is always local big_square.png)."""
    lineup_b = m.get("lineup_b") or {}
    today = datetime.now(BERLIN_TZ).date().isoformat()
    return "|".join(
        [
            m.get("slug") or "",
            m.get("first_map_at") or "",
            (m.get("tournament") or {}).get("name") or "",
            (lineup_b.get("team_logo_url") or "").strip(),
            today,
        ]
    )


async def _ensure_image(match: dict, variant: str = "og") -> bytes:
    """Return the cached versus JPEG for a match, building it if stale/missing."""
    slug = match.get("slug") or ""
    sig = _image_signature(match)
    cached = _image_cache.get((variant, slug))
    if cached and cached[0] == sig:
        return cached[1]
    jpg = await _build_versus_image(match, variant)
    _image_cache[(variant, slug)] = (sig, jpg)
    if len(_image_cache) > 80:  # bound memory; newest entries stay anyway
        _image_cache.pop(next(iter(_image_cache)))
    return jpg


async def _warm_image(match: dict, variant: str = "og") -> None:
    """Background pre-warm; failures are logged, never surfaced."""
    try:
        await _ensure_image(match, variant)
    except Exception:
        log.warning("share: pre-warm %s image build failed for %s", variant, match.get("slug"))


async def _build_versus_image(m: dict, variant: str = "og") -> bytes:
    """Fetch opponent logo and delegate to compose_versus_image for the
    shared composition (game background, both logos, overlays, text).
    The "twitter" variant drops the game logo and BO/date/time."""
    lineup_b = m.get("lineup_b") or {}
    opp_logo = (lineup_b.get("team_logo_url") or "").strip()
    game = (m.get("game") or "").lower()
    bo_text = f"BO{m['bestof']}" if m.get("bestof") else ""
    _, _, tournament, time_str, _ = _match_info(m)

    # Fetch opponent logo bytes (or TBA placeholder)
    if opp_logo:
        try:
            opponent_img = await _fetch_logo(opp_logo)
            opponent_img = _crop_visible(opponent_img)
            buf = io.BytesIO()
            opponent_img.save(buf, format="PNG")
            opponent_bytes = buf.getvalue()
        except Exception:
            log.warning("share: opponent logo fetch failed, using TBA placeholder")
            buf = io.BytesIO()
            _make_tba_placeholder().save(buf, format="PNG")
            opponent_bytes = buf.getvalue()
    else:
        buf = io.BytesIO()
        _make_tba_placeholder().save(buf, format="PNG")
        opponent_bytes = buf.getvalue()

    compose_kwargs = dict(game=game, tournament=tournament, bo_text=bo_text, time_str=time_str)
    if variant == "twitter":
        compose_kwargs.update(show_game_logo=False, show_info=False)

    return compose_versus_image(opponent_bytes, **compose_kwargs)


async def _fetch_logo(url: str) -> Image.Image:
    """Download a logo; direct fetch first, weserv proxy as fallback.

    imgur (BIG's logos) blocks weserv but serves direct requests; HLTV CDN
    blocks direct requests from server IPs but works through weserv.
    """
    proxy_url = (
        "https://images.weserv.nl/?url="
        + urllib.parse.quote(re.sub(r"^https?://", "", url), safe="")
        + "&w=400"
    )
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    timeout = ClientTimeout(total=10)
    async with ClientSession(timeout=timeout) as session:
        for attempt in (url, proxy_url):
            try:
                async with session.get(attempt, headers=headers) as resp:
                    if resp.status == 200:
                        return Image.open(io.BytesIO(await resp.read())).convert(
                            "RGBA"
                        )
            except Exception:
                continue
    raise RuntimeError(f"logo fetch failed: {url}")


# ── List page ───────────────────────────────────────────────────────────────

_LIST_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BIG Matches</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f0f0f;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;min-height:100vh;padding:16px}
h1{text-align:center;font-size:20px;margin:8px 0 16px;color:#fff}
.cards{display:flex;flex-direction:column;gap:16px;max-width:420px;margin:0 auto}
.card{background:#1a1a1a;border-radius:12px;padding:16px;text-align:center}
.versus-img{width:100%;border-radius:8px;margin-bottom:12px;background:#222}
.info{color:#ccc;font-size:14px;margin-bottom:4px}
.btn-row{display:flex;gap:10px;margin-top:4px}
.btn-row button{flex:1;display:flex;align-items:center;justify-content:center;gap:8px;padding:12px 16px;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;touch-action:manipulation}
.btn-wa{background:#25D366;color:#000}
.btn-wa:active{background:#1da851}
.btn-copy{background:#333;color:#e0e0e0}
.btn-copy:active{background:#444}
.btn-copy.copied{background:#2a6b3a}
.btn-row svg{flex-shrink:0}
</style>
</head>
<body>
<h1>Upcoming Matches</h1>
<div class="cards">
<!-- CARDS -->
</div>
<script>
(function(){
// WhatsApp button — open wa.me with the URL pre-filled
document.querySelectorAll('.btn-wa').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const waUrl='https://wa.me/?text='+encodeURIComponent(btn.dataset.url);
    window.open(waUrl,'_blank');
  });
});
// Copy button — copy URL to clipboard with visual feedback
document.querySelectorAll('.btn-copy').forEach(btn=>{
  btn.addEventListener('click',async()=>{
    try{
      await navigator.clipboard.writeText(btn.dataset.url);
      btn.innerHTML=btn.dataset.checkIcon+' Copied';
      btn.classList.add('copied');
      setTimeout(()=>{
        btn.innerHTML=btn.dataset.copyIcon+' Copy';
        btn.classList.remove('copied');
      },2000);
    }catch(e){
      // Fallback for older browsers / non-HTTPS
      const ta=document.createElement('textarea');
      ta.value=btn.dataset.url;ta.style.position='fixed';ta.style.opacity='0';
      document.body.appendChild(ta);ta.select();
      document.execCommand('copy');document.body.removeChild(ta);
      btn.innerHTML=btn.dataset.checkIcon+' Copied';
      btn.classList.add('copied');
      setTimeout(()=>{
        btn.innerHTML=btn.dataset.copyIcon+' Copy';
        btn.classList.remove('copied');
      },2000);
    }
  });
});
})();
</script>
</body>
</html>"""
