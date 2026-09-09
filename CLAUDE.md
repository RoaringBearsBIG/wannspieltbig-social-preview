# wannspieltbig-social-preview — Share-Page-Service für BIG Matches

Standalone aiohttp-Service für die öffentlichen Share-Seiten (Social-Media
Link-Previews für wannspieltbig-Matches) auf dem Subdomain
`bot.wannspieltbig.de`. 2026-08 aus RoaringBot extrahiert — die Share-Routen
liefen vorher im selben Prozess wie die Dashboard-Feedback-API.

Läuft als Docker-Container `wannspieltbig-social-preview` (Compose-Service
`social-preview`), Port 8080 nur im externen `dashboard-network` (kein
published Port). nginx (`~/website`) proxied den ganzen Host (außer `/api/`)
hierher.

## Architektur

```
main.py          # Entrypoint: aiohttp-Server + Background-Image-Warmer
app.py           # create_app(): alle Routen (kanonisch + Legacy)
share_pages.py   # Handler, HTML-Builder, Match-API-Fetch (TTL-gecached),
                 #   Logo-Fetch, Image-Cache
image.py         # Reine Bild-Komposition (PIL, kein Netz) — MUSS gespiegelt
                 #   werden mit RoaringBots core/versus_image.py!
config.py        # Env-Config (SHARE_BASE_URL, ESPORTS_API_URL, PORT, …)
resources/       # big_square.png, tba.png, {cs,lol,tm}-bg.jpg/-logo.png
```

## Routen

Kanonisch (kurze URLs) und Legacy (`/share/*`, `/share-match/`) — Legacy
MUSS bedient werden (nicht 301-en): bereits geteilte WhatsApp-Nachrichten
cachen die Previews.

| Route | Zweck |
|---|---|
| `/` | Übersicht: eine Card pro anstehendem Match, WhatsApp/Copy-Buttons |
| `/{id}` | Match-Seite: og:-Tags + twitter:image, dann JS-Redirect zu wannspieltbig |
| `/{id}/image.jpg` | og:image (WhatsApp/Bluesky/Discord) — volle Komposition, 2:1 |
| `/{id}/image-twitter.jpg` | twitter:image (X) — ohne Game-Logo, ohne BO/Datum/Zeit (Turnier bleibt) |
| `/share/*`, `/share-match/` | Legacy-Kompat (identische Handler) |
| `/healthz` | Docker-HEALTHCHECK |

## Schlüsselkonzepte

- **Datenquelle**: ausschließlich `wannspieltbig.de/api/match_upcoming/`
  (extern, kein Postgres, kein Discord). `ESPORTS_API_URL` konfigurierbar.
- **Match-API-Cache**: die Roh-API-Daten werden 30 s in-memory gecached
  (`_match_data_cache`, `MATCH_DATA_TTL_SECONDS`). Ohne diesen Cache macht
  jede Request (Match-Seite + Bild) einen frischen ~300 ms-Roundtrip zur
  externen API — genau der Burst, den ein Social-Crawler beim Posten eines
  Links auslöst. Fehlgeschlagene Fetches werden nie gecacht (Live-Retry beim
  nächsten Zugriff).
- **Image-Cache**: in-memory, keyed `(variant, slug)`, Signature enthält
  kickoff/tournament/logo/heutiges Datum (Today/Tomorrow-Label über
  Mitternacht korrekt). Bound 80 Einträge.
- **Warmer**: `main.py`-Loop baut alle `WARM_INTERVAL_MINUTES` (Default 15)
  beide Varianten aller anstehenden Matches vor — Social-Crawler droppen
  Bilder bei kalten Fetch-Zeiten von mehreren Sekunden. Zusätzlich
  request-getriggertes Pre-Warm in `handle_share_list`.
- **Bild-Komposition**: `image.py:compose_versus_image(opponent_png, *,
  game, tournament, bo_text, time_str, w, h, show_tournament,
  show_game_logo, show_info)` — Flags strippen einzelne Design-Elemente,
  Defaults = volle Komposition byte-identisch.
- **Zeit**: `first_map_at` als Berliner Wanduhr-Zeit interpretiert
  (Offset-Suffix wird verworfen, siehe `_parse_match_time`).
- **Logo-Fetch**: direkt zuerst, dann images.weserv.nl-Proxy (HLTV-CDN
  blockt Server-IPs; imgur blockt weserv). Eigener 10-s-Timeout-Session —
  ein retriender Client wäre für Crawler zu langsam.
- **Kein Meta-Refresh-Redirect** auf der Match-Seite (nur JS) — WhatsApp
  folgt Meta-Refresh und würde den Preview kaputtmachen.

## WICHTIG: Spiegel-Modul in RoaringBot

Die Komposition existiert zweimal: hier `image.py` und in RoaringBot als
`core/versus_image.py` (für Discord-Reminder/Event-Cover). Änderungen an
`compose_versus_image` oder den Loadern MÜSSEN manuell in das jeweils
andere Repo gespiegelt werden (Cross-Component-Contract, siehe
`DATA_INTERFACE.md`).

## Development

```bash
cp .env.example .env
docker compose up -d --build
.claude/skills/run-wannspieltbig-social-preview/smoke.sh
```

- Keine Secrets in `.env` nötig (nur öffentliche URLs).
- Smoke-Probes laufen über `docker run --rm --network dashboard-network
  curlimages/curl` — der Service hat keinen published Port.
- Deployment des Dienstes selbst: `docker compose up -d --build`.
- nginx-Umleitung liegt in `~/website` (anderer Komponenten-Scope, eigene
  Session): nur die Zeile `set $share_upstream …` in
  `nginx/nginx.conf` zeigt auf diesen Container.
- **nginx-Proxy-Cache**: `nginx/nginx.conf` (in `~/website`) cached alle
  `bot.wannspieltbig.de`-Responses via `proxy_cache share_cache`
  (`X-Proxy-Cache`-Header). Wiederholte Crawls (WhatsApp/X/…) werden von
  nginx bedient, ohne den Python-Service zu berühren. Deployment des
  nginx-Containers: `docker compose up -d --build nginx` in `~/website`.
  Requests mit Cache-Buster-Query (`?v=…`) sind neue Cache-Keys und laufen
  immer am Cache vorbei — nicht als Workaround verwenden.
