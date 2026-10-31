# Fakeflix Personal — v0.4.0 — Vyla integration

A private mobile-first adaptation of [Th3Wall/Fakeflix](https://github.com/Th3Wall/Fakeflix), now with a self-hosted Vyla provider and TMDB catalog. The original MovieBox provider remains available only when explicitly selected with `MEDIA_PROVIDER=moviebox`.

**Status: adapter implemented and fixture-tested; full upstream playback/download is not verified.** A real TMDB v3 API key is still required. No public deployment has been created. No speed or full-catalog guarantee is made.

Vyla Stream API is pinned at GitLab commit `295c0efb66d8520e9052cd4981aab58bf5b71ea6`; SDK is pinned to npm `1.20.0` with a lockfile. Source and license are retained in `services/vyla`. Vyla uses CC BY-NC 4.0; preserve attribution and noncommercial use. Fakeflix's MIT license does not relicense Vyla or the supplied MovieBox backend.

## Vyla setup (current default)

1. Install the app prerequisites below and run `npm run setup:local` (or append the new settings to your existing `.env.local`).
2. Obtain your own **TMDB v3 API key** from https://www.themoviedb.org/settings/api and add it privately to `.env.local`. Do not paste it in chat, logs, screenshots, or Git. A long v4 bearer token is not interchangeable with this field.
3. Set these values in `.env.local`:

```dotenv
MEDIA_PROVIDER=vyla
VYLA_BASE_URL=http://127.0.0.1:7860
TMDB_API_KEY=your-v3-key
```

4. Install the service dependencies and start it in a separate terminal:

```bash
npm --prefix services/vyla ci --ignore-scripts
npm run source:vyla
```

5. In another terminal, run `npm run build` then `npm start`. Open http://localhost:5173.

The Account page shows Vyla setup status. Its status means configuration exists, not that every upstream provider works. MovieBox login is not needed in Vyla mode. Service launch refuses a missing key. The Vyla service listens only on loopback for local use; do not expose its unauthenticated upstream proxy to the internet.

### Docker Compose / VPS

After creating `.env.local` and adding the key:

```bash
docker compose up -d --build
```

The app binds `127.0.0.1:5173`; place your HTTPS reverse proxy in front for phone access. Set `COOKIE_SECURE=true` when using HTTPS. Vyla is private on the Compose network and has no published port. App watchlists/progress use a named SQLite volume in this single-instance VPS configuration. Docker deployment itself has not been run in this environment.

### Provider behavior

- Discovery uses TMDB metadata. IDs are namespaced as `vyla:movie:550` / `vyla:tv:1396`, so movie, TV, and old MovieBox titles cannot collide.
- TV selections are validated against the exact TMDB season episode list before resolution. Old MovieBox watchlist entries must be found again through Vyla search; no title guessing is used.
- Vyla's SSE source results appear in the existing source picker. The backend caches results briefly and blocks stale source IDs. Playback remains on the app's authenticated media proxy.
- HLS URLs hidden behind a query-string proxy receive an explicit player format, so hls.js is used even without a `.m3u8` URL suffix.
- Download resolution calls Vyla's **separate** downloads API. Only direct MP4 candidates are accepted. A working stream does not imply an offline download exists. No HLS/DASH-to-MP4 merging is implemented.
- MP4 download quality is used only if the downloads response actually supplies it; a streaming quality selection is not silently relabeled as a downloadable file.
- TMDB metadata does not establish upstream video identity or availability; real media still needs playback validation.
- Metadata provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See https://www.themoviedb.org/about/logos-attribution for branding before public release.

## Shared features / legacy MovieBox capabilities

- Mobile bottom navigation, browsing rows, title sheets, search and explicit season/episode selection.
- Private, administrator-configured accounts. No public registration. Each account has its own watchlist and per-episode progress.
- Same-origin session cookie, private API gateway and source media proxy. Upstream debug, arbitrary-proxy and local-player launch routes are not exposed.
- MP4/HLS/DASH player integration, with source-provided subtitle selection, SRT-to-VTT conversion, playback speed and HLS/DASH audio-track controls where supplied. Browser codec limits and restricted DASH manifest support still apply.
- Audio-version (dub) switching via the source's linked title IDs, followed by fresh episode/source discovery.
- Available source options read from live API metadata. A `resolutions` advertisement is not mislabeled as a selectable concrete-quality stream.
- Normal MovieBox account connection from the app's Account page. Passwords are forwarded only for the source login and are not saved; upstream tokens stay process-local. App accounts and source accounts are separate.
- Two simultaneous **device-local progressive MP4** downloads, season batch selection, progress, pause, conditional byte resume, retry, delete and export to the phone's Downloads folder. Source notice/preview clips are rejected before transfer.
- Offline playback of completed saved MP4s through a Blob URL; app shell precached by a service worker after production installation. Downloads remain on their original device.
- Season/episode validation against the source episode list **before** stream resolution. Contradictory metadata and stale source IDs are rejected. No subject-only legacy download fallback. This still cannot prove video content identity if the upstream mislabels a full-length video.
- An offline outbox for watchlists and progress: edits persist on the device, sync on reconnect and retry every 30 seconds online. Requests carry the expected app username so a stale tab cannot write to another signed-in account.
- App sign-out revokes the current session in the running process and disconnects its source account. Source tokens/client state remain process-local.
- Vite production frontend and a single FastAPI service, packaged for a Heroku container deployment.

## Not yet implemented / not verified

- HLS/DASH offline download merging, expired source-ID refresh mid-download, automatic next episode and profile PIN. Offline subtitle sidecars are not yet saved.
- Resume is conditional, not guaranteed. Partial bytes are retained. Resume requires the same strong ETag and an exact `206 Content-Range`; a `200` response replaces the partial file instead of appending. Sources without a strong ETag restart. Bad ranges are rejected. A browser reload marks active jobs interrupted.
- Guaranteed screen-off/background downloads. Mobile browsers can suspend the page. Keep it open while downloading.
- Cross-device sync of video files. Only online watchlists/progress use the server database.
- Reliable multi-tab queue coordination: Web Locks prevent the same job transferring concurrently, but concurrency is per tab; use one download tab.
- A representative real movie playback or completed movie download has not been verified. Source authentication/catalog access was verified; availability and quality depend on the upstream.
- Browser QA checked the rendered login screen. Authenticated UI and physical mobile devices have not been visually tested.
- Large Blob playback/export can use significant device memory. MP4 validation checks its signature/size, not the identity or codec of the episode.
- Multiple devices use last-write-wins sync. Simultaneous edits of the same progress item can overwrite each other; there is no conflict-resolution UI.

## App prerequisites and local accounts

Requires Node.js 22 and Python 3.12. From the project root:

```bash
npm ci
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
npm run setup:local
```

`setup:local` creates private `kishor` and `friend` logins with random passwords and a random session secret, and prints the login details. To display existing local credentials, run `npm run credentials:local`. You can also edit `.env.local` directly. Keep `COOKIE_SECURE=false` only for local HTTP. Do not commit this file.

Build and run the integrated app:

```bash
npm run build
npm start
```

Open `http://localhost:5173`. This production build allows service-worker/offline testing. Vite development mode does not register the service worker.

For frontend development, use two terminals:

```bash
npm run backend
npm run dev
```

The API uses port 8000 and Vite proxies app/API routes to it. `npm run dev` serves port 5173. Rebuild to test the integrated production version.

## Heroku container deployment (external Vyla service required)

1. Create a personal Heroku app and set its stack to **container**.
2. Provision a persistent PostgreSQL database. Its `DATABASE_URL` must be configured. SQLite is development-only; production startup refuses a Heroku dyno without PostgreSQL.
3. In the Heroku dashboard Config Vars, set `APP_USERS`, a generated `SESSION_SECRET`, `COOKIE_SECURE=true`, `MEDIA_PROVIDER=vyla`, `TMDB_API_KEY`, and `VYLA_BASE_URL` pointing to your separately deployed HTTPS Vyla service. The Python app image does not run Vyla. Keep that service accessible only to your gateway. Never put credentials into Git.
4. Push this code to **your own private repository**, connect it to Heroku and deploy. `heroku.yml` builds `Dockerfile`.
5. Run one web dyno, one process/worker. Source clients/media tokens are process-local; scaling across workers requires a shared session store first.
6. Check `/health`, sign in as each account, and verify separate libraries before testing an actual episode. A source link will need re-resolving after a dyno restart.

The container has Node only at build time; runtime is Python. Completed movies are stored on the phone/browser, not the Heroku filesystem. Media proxy transfers still consume Heroku bandwidth. No deployment or billed resources have been created by this package.

## Tests

```bash
backend/.venv/bin/pip install pytest
cd backend
.venv/bin/python -m pytest -q test_personal.py
```

Run the frontend download/sync tests too:

```bash
npm test
```

Backend tests cover private authentication, account isolation, stale account requests, logout revocation, exact source/episode validation, preview blocking, source metadata, source account response filtering, subtitle conversion and byte-range validation. Frontend tests cover two simultaneous jobs, exact episode identities, partial-byte resume, source changes, bad ranges, error bodies, device-account isolation and offline outbox races. A generated H.264 fixture is saved/exported and validated with ffprobe when ffmpeg is installed. This does not substitute for a physical phone/airplane-mode test or prove the upstream serves full movies.

## Source layout

- `src/personal/`: active app, player, local download storage and mobile styling.
- `src/components/RowPoster/RowPoster.jsx`: adapted Fakeflix browsing card.
- `src/` outside these paths: retained original Fakeflix source, not imported by this milestone.
- `backend/personal_server.py`: active private gateway, source-account connection and app data API.
- `backend/media_selection.py`: episode/source normalization and notice/preview detection.
- `src/personal/library.js`: device outbox and online account-bound sync.
- `backend/moviebox_api_server.py`, `backend/moviebox_api/`: supplied source integration; the upstream ASGI app is **not** mounted publicly.
- `scripts/precache.mjs`: production offline app-shell generation.
- `Dockerfile`, `heroku.yml`: deployment configuration.

## Connected API routes

| Route | Purpose |
|---|---|
| `GET /api/home`, `/api/movies`, `/api/anime`, `/api/trending` | Catalog categories |
| `GET /api/search?q=...` | Search |
| `GET /api/detail/{id}` | Metadata and linked audio versions |
| `GET /api/episodes/{id}` | Normalized season and episode lists |
| `GET /api/sources/{id}?season=2&episode=1` | Validate selection, list safe available sources; no raw source credentials returned |
| `GET /api/stream/{id}?season=2&episode=1&quality=auto&source_id=...` | Resolve a chosen source, proxy URL and source-provided captions |
| `GET /download/{id}?season=2&episode=1&quality=auto&source_id=...` | Progressive MP4 transfer; supports validated Range/If-Range |
| `GET/POST/DELETE /api/connection` | Source connection status / normal account connection / disconnect |
| `GET/PUT/DELETE /library` | Separate application watchlist and progress (DELETE uses `/library/{key}`) |

All these routes require the private application session. Authentication, source and media responses are not cached by the service worker. Source credentials are never written into offline library/download jobs.

## Optional local demo login

After installing the dependencies above, on a fresh extraction:

```bash
npm run setup:local -- --demo
npm run build
npm start
```

Open **http://localhost:5173 on the machine running this app**.

- Username: `preview`
- Password: `preview-only-12345`

The setup command will not overwrite an existing `.env.local`. `npm run credentials:local` displays whichever local accounts are configured. Demo credentials are for local testing, not public hosting. The ZIP contains no private environment file. A public Heroku app has not been created.

## v0.3.1 source compatibility status

- Normal v2 resolution now tries normal v1 resolution when v2 returns only notice clips.
- API-provided direct metadata links can be used only when a series link explicitly matches the requested subject/season/episode. Metadata entries requiring a media cookie are skipped by this fallback.
- Dated `/other/YYYY/MM/DD/` notice paths are filtered without treating a title like Red Notice as an ad.
- The tested series still had no exact direct metadata links, and the latest inspected guest response had no usable signed-media cookie. Full episode playback has not been established.
- A proposed live test forwarding a source media cookie to a derived external CDN was rejected by automatic approval review. It was not repeated; no cookie-derived CDN resolution was added. That live signed-media check remains pending explicit authorization and a usable source response.
