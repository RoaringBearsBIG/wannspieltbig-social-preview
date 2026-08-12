"""Entrypoint: aiohttp server + background image warmer.

The warmer pre-builds both image variants for upcoming matches every
WARM_INTERVAL_MINUTES so social crawlers (WhatsApp/X) never hit a cold
logo-fetch when they first visit a shared URL — a cold build can take
several seconds and crawlers drop images that respond too slowly.
"""

import asyncio
import logging

from aiohttp import web

from app import create_app
from config import config
from share_pages import VARIANTS, _fetch_upcoming_matches, _warm_image

log = logging.getLogger("social-preview.main")


async def warm_loop() -> None:
    """Periodically pre-build upcoming match images (both variants)."""
    while True:
        try:
            matches = await _fetch_upcoming_matches()
            tasks = [
                _warm_image(m, variant)
                for m in matches
                if m.get("slug")
                for variant in VARIANTS
            ]
            if tasks:
                await asyncio.gather(*tasks)  # _warm_image swallows failures
        except Exception:
            log.exception("warmer pass failed")
            await asyncio.sleep(60)
            continue
        await asyncio.sleep(config.warm_interval_minutes * 60)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    runner = web.AppRunner(create_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.port).start()
    log.info("social-preview listening on port %s", config.port)
    asyncio.create_task(warm_loop())
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
