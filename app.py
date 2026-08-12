"""aiohttp app factory: the share-page routes formerly hosted by RoaringBot.

Canonical URLs are short paths on bot.wannspieltbig.de; the /share/* and
/share-match/ routes are legacy compat for already-shared WhatsApp messages
and MUST be served (not redirected) — WhatsApp caches link previews.
"""

from aiohttp import web

from share_pages import (
    close_http_session,
    handle_health,
    handle_share_list,
    handle_share_match,
    handle_share_image,
    handle_share_twitter_image,
    handle_share_slug_redirect,
    handle_share_next_match,
)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", handle_health)

    # Canonical short URLs
    app.router.add_get("/", handle_share_list)
    app.router.add_get(r"/{match_id:\d+}", handle_share_match)
    app.router.add_get(r"/{match_id:\d+}/image.jpg", handle_share_image)
    app.router.add_get(r"/{match_id:\d+}/image-twitter.jpg", handle_share_twitter_image)

    # Legacy URLs — keep serving them, already-shared messages rely on them
    app.router.add_get("/share/", handle_share_list)
    app.router.add_get(r"/share/{match_id:\d+}/", handle_share_match)
    app.router.add_get(r"/share/{match_id:\d+}/image.jpg", handle_share_image)
    app.router.add_get(r"/share/{match_id:\d+}/image-twitter.jpg", handle_share_twitter_image)
    app.router.add_get("/share/{slug}/", handle_share_slug_redirect)
    app.router.add_get("/share/{slug}/image.jpg", handle_share_slug_redirect)
    app.router.add_get("/share/{slug}/image-twitter.jpg", handle_share_slug_redirect)
    app.router.add_get("/share-match/", handle_share_next_match)

    app.on_shutdown.append(lambda _app: close_http_session())
    return app
