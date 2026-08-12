<h1 align="center">wannspieltbig-social-preview</h1>

<p align="center">
  <strong>Share-page service for BIG matches</strong> — public link-preview pages
  for WhatsApp, X, Bluesky and Discord, served at
  <a href="https://bot.wannspieltbig.de">bot.wannspieltbig.de</a>.
</p>

<p align="center">
  <a href="https://wannspieltbig.de">
    <img src="https://img.shields.io/badge/wannspieltbig.de-FF6B35?style=for-the-badge" alt="wannspieltbig.de">
  </a>
  <a href="https://github.com/RoaringBearsBIG/RoaringBot">
    <img src="https://img.shields.io/badge/RoaringBot-5865F2?logo=discord&logoColor=white&style=for-the-badge" alt="RoaringBot">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/aiohttp-3.x-2C5BB4?logo=aiohttp&logoColor=white" alt="aiohttp">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
</p>

---

Match data is powered by **[wannspieltbig](https://github.com/ckarrie/ckw-csgo)**,
the [ckarrie](https://github.com/ckarrie)-maintained Django fan page for the
BIG CLAN. This service reads its public match API, composes versus thumbnails,
and serves small HTML pages whose `og:`/`twitter:` meta tags drive the social
link previews.

Extracted from [RoaringBot](https://github.com/RoaringBearsBIG/RoaringBot) in
2026-08 — RoaringBot keeps only the pure image composition
(`core/versus_image.py`) for its Discord images, which is **mirrored** here as
`image.py`. Changes to the composition must be kept in sync manually.

## Routes

| Route | Purpose |
|---|---|
| `/` | Overview: one card per upcoming match with WhatsApp/Copy buttons |
| `/{id}` | Match page: `og:` tags + `twitter:image`, then JS redirect to the wannspieltbig match page |
| `/{id}/image.jpg` | `og:image` (WhatsApp/Bluesky/Discord) — full composition, 2:1 |
| `/{id}/image-twitter.jpg` | `twitter:image` (X) — without game logo and BO/date/time (tournament stays) |
| `/share/*`, `/share-match/` | Legacy paths — must keep working (already-shared WhatsApp messages cache the previews) |
| `/healthz` | Docker healthcheck |

## Setup

```bash
git clone https://github.com/RoaringBearsBIG/wannspieltbig-social-preview.git
cd wannspieltbig-social-preview
cp .env.example .env
docker compose up -d --build
```

The container listens on port 8080 **inside the `dashboard-network` docker
network** (no published port) — nginx proxies `bot.wannspieltbig.de` to it.

## Documentation

- **[DATA_INTERFACE.md](DATA_INTERFACE.md)** — route contract for consumers (nginx, social crawlers, RoaringBot mirror)
- **[CLAUDE.md](CLAUDE.md)** — architecture, key concepts, development guide
