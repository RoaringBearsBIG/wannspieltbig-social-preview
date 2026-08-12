---
name: run-wannspieltbig-social-preview
description: Run, smoke-test, deploy, and health-check the wannspieltbig-social-preview service (share pages behind bot.wannspieltbig.de). Use when asked to run, start, restart, test, verify, deploy, or check the share pages, their images (og:image / twitter:image), or logs.
---

# Run: wannspieltbig-social-preview

Standalone aiohttp share-page service (social link previews for
wannspieltbig matches), container `wannspieltbig-social-preview`. Its user
surface is the public web (`bot.wannspieltbig.de` via nginx) — not
headless-drivable beyond HTTP. Verify it through: HTTP probes over
`dashboard-network`, container health, and logs. Paths relative to
`/root/wannspieltbig-social-preview`.

## Smoke test (agent path — run this first)

```bash
.claude/skills/run-wannspieltbig-social-preview/smoke.sh   # read-only, ~10 s
```

Checks: container running, `/healthz`, list page renders cards, per-match
probes (meta tags, both image variants as valid JPEGs, byte-different
variants), legacy routes, slug 301, recent log error count. Optional UI
screenshot of the list page (`SKIP_UI=1` to skip).

## Individual probes (no published port — docker network only)

```bash
docker run --rm --network dashboard-network curlimages/curl -sf \
  http://wannspieltbig-social-preview:8080/healthz

# list page + first match id
docker run --rm --network dashboard-network curlimages/curl -sf \
  http://wannspieltbig-social-preview:8080/

# og:image vs twitter:image for a known match id
docker run --rm --network dashboard-network curlimages/curl -sf \
  http://wannspieltbig-social-preview:8080/<id>/image-twitter.jpg

# logs
docker logs wannspieltbig-social-preview --tail 100
```

Public URL (after nginx): `https://bot.wannspieltbig.de/`.

## Deploy

```bash
cd /root/wannspieltbig-social-preview && docker compose up -d --build
```

After deploy: wait ~20 s, run the smoke test.

## Gotchas

- The service has **no published port** — probes go over `dashboard-network`.
- Legacy routes `/share/*` and `/share-match/` must stay served (not 301):
  already-shared WhatsApp messages cache the previews.
- Image builds can take several seconds cold (logo fetch + PIL) — the
  warmer task pre-builds every `WARM_INTERVAL_MINUTES`; a fresh deploy needs
  one warm pass before first-request latency is optimal.
- `image.py` is mirrored in RoaringBot as `core/versus_image.py` — changes
  to the composition must be mirrored there manually (see DATA_INTERFACE.md).
- nginx proxying lives in `~/website` (different component scope): only the
  `set $share_upstream` line in `nginx/nginx.conf` targets this container.

## Troubleshooting

| Symptom | Fix |
|---|---|
| 502 from public URL | Check `docker logs website-nginx-1`; container must be running and on `dashboard-network`: `docker inspect wannspieltbig-social-preview -f '{{json .NetworkSettings.Networks}}'` |
| 404 on `/{id}` but match exists | Match may be >20 API pages deep or ended; probe `wannspieltbig.de/api/match_upcoming/?limit=20` directly |
| image.jpg 500 | `docker logs wannspieltbig-social-preview` — logo fetch failed AND TBA placeholder missing? resources/ must be in the image |
| ZoneInfoNotFoundError | Install `tzdata` in the Dockerfile and rebuild |
