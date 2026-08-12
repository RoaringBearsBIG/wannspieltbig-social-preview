# DATA_INTERFACE — wannspieltbig-social-preview

Contract für den Share-Page-Service (2026-08 aus RoaringBot extrahiert).

## Konsumenten

| Konsument | Was | Vertrag |
|---|---|---|
| nginx (`~/website`) | proxied `bot.wannspieltbig.de` komplett (außer `/api/`) zu diesem Container | Alle untenstehenden Routen; `/api/` bleibt am Edge geblockt |
| WhatsApp / Bluesky / Discord | Link-Preview via `og:`-Tags | `/{id}` liefert og:image (volle Komposition) |
| X (Twitter) | Link-Preview via `twitter:*` | `/{id}` liefert `twitter:image` (ohne Game-Logo, ohne BO/Datum/Zeit) |
| RoaringBot | **kein Laufzeit-Consumer** — nur gespiegelte Bild-Komposition | `compose_versus_image` in `core/versus_image.py`; Änderungen hier MÜSSEN dort manuell nachgezogen werden |

## Routen (alle über nginx öffentlich)

| Route | Antwort |
|---|---|
| `GET /healthz` | 200 `ok` (intern, Docker-HEALTHCHECK) |
| `GET /` | HTML-Übersicht: eine Card pro anstehendem Match, WhatsApp/Copy-Buttons |
| `GET /{id}` | HTML mit `og:title/description/type/url/image` (+width/height 1600×800), `twitter:card summary_large_image`, `twitter:image`, dann JS-Redirect auf `html_detail_url` der wannspieltbig-API. Funktioniert auch für beendete Matches. |
| `GET /{id}/image.jpg` | Versus-JPEG 1600×800 (2:1), Quality 85, `Cache-Control: public, max-age=3600` — volle Komposition |
| `GET /{id}/image-twitter.jpg` | Dito, aber ohne Game-Logo und ohne BO/Datum/Zeit (Turnier-Label bleibt) |
| `GET /share/…` (Legacy) | Identische Handler wie kanonische URLs — **müssen bedient bleiben**, bestehende WhatsApp-Caches |
| `GET /share/{slug}/…` (Legacy) | Echter 301 auf die kanonische `/{id}`-URL (image.jpg / image-twitter.jpg je nach Suffix) |
| `GET /share-match/` (Legacy) | Alias der Übersicht |

## Datenquelle

- `wannspieltbig.de/api/match_upcoming/?limit=20` (Env `ESPORTS_API_URL`)
  — frischer Fetch pro Request, nicht-cancellte Matches, aufsteigend nach
  Kickoff. TBA-Placeholder wenn kein Gegner-Logo. Logo-Fetch direkt, dann
  images.weserv.nl-Proxy.

## Umgebungsvariablen

| Var | Default | Zweck |
|---|---|---|
| `SHARE_BASE_URL` | `https://bot.wannspieltbig.de` | Basis der og:url/og:image/twitter:image |
| `ESPORTS_API_URL` | `https://wannspieltbig.de/api/match_upcoming/` | Match-API |
| `PORT` | `8080` | Listen-Port (intern) |
| `WARM_INTERVAL_MINUTES` | `15` | Intervall des Image-Pre-Warmers |
