# Validation — v0.4.0

## Vyla integration

- 34 Python tests pass (26 existing plus 8 Vyla cases): namespace isolation, person filtering, exact season/episode request, SSE sources/subtitles, stale source rejection, separate MP4 download endpoint, HLS download rejection, missing configuration, and private-proxy target validation, route dispatch without MovieBox initialization, and blocked media URL tampering.
- Production build and all 11 frontend/storage tests pass.
- Actual vendored Vyla service booted locally: root HTTP 200; playback without a TMDB key returns HTTP 400 with a clear missing-key error. This checks startup, not media playback.
- Current GitLab source fetched at commit 295c0efb66d8520e9052cd4981aab58bf5b71ea6; npm SDK 1.20.0 dependencies resolved and pinned in a lockfile.
- A local synthetic HTTPS MP4 fixture passed actual Vyla proxy transfer (200) and exact byte-range transfer (206), with certificate verification enabled. This is not upstream movie playback.
- No TMDB key was available, so no real Vyla catalog, full movie, real episode, provider speed, or full offline download was verified. Tests use synthetic HTTP/SSE fixtures, not real media.
- Docker Compose is provided but not executed here. Physical phone/browser-offline testing remains outstanding.

## Previous provider validation (historical)

### MovieBox v0.3.1

## Passed

- Production Vite build, service-worker syntax and Python compilation.
- 26 backend tests: app authentication, logout revocation, user isolation, stale-account requests, episode/season existence, source IDs, real `resolutions` handling, notice/preview detection, movie requests without series parameters, minimal detail mapping, source-account result filtering, SRT conversion and validated range proxying.
- 11 frontend/storage tests: two simultaneous downloads, episode separation, safe resume, changed source restart, wrong range rejection, invalid-body rejection, account isolation and offline outbox synchronization/races.
- A locally generated one-second H.264 MP4 was stored/exported through the download manager and validated with ffprobe. This is a synthetic fixture, not a movie from the upstream.
- Previous live source checks: guest authentication success; catalog code 0; 19 normalized sections and 364 title entries through the authenticated gateway.
- Current live integration check: source episode list exposes seasons 1–5 for the tested Breaking Bad Hindi subject. S1E1 and S2E1 source discovery correctly return HTTP 409 / SOURCE_PREVIEW_ONLY.

## Confirmed source limitation

Normal v1 and v2 guest playback calls returned the identical ~23-second / 824,720-byte video URL for distinct S1E1, S2E1 and S5E1 selections, despite different resource IDs. The response resembles an upgrade/notice clip, not the requested episode. The app now blocks that response. An existing source account may be connected through normal login, but no source-account credentials or full-video access were available for verification. Other titles have not been exhaustively checked.

## Not verified / outstanding

- No Heroku deployment or billable resource creation.
- No representative full-movie transfer from this upstream; no measured playback speed/buffering.
- No physical Android/airplane-mode test or authenticated visual QA. The earlier login screen was visually inspected.
- HLS/DASH offline merging, offline subtitle sidecars, automatic episode advance and profile PIN remain unimplemented.
- Browser background/locked-screen transfer continuity is not guaranteed.
- MP4 resume requires a stable strong ETag and valid byte-range support. Without those, retry restarts the file.

## Additional v0.3.1 checks

- Fresh local demo setup created the documented preview login without storing credentials in the archive.
- Integrated local HTTP server: login 200, account verification 200, built frontend 200. This is localhost-only; it is not a public deployment.
- Added tests for exact-episode metadata fallbacks, rejecting cookie-bearing metadata entries, and avoiding false notice matches for Red Notice.
- The proposed cookie-forwarding CDN live test was rejected by automatic approval review and was not retried. Subsequent diagnostics contacted only the existing API and did not fetch declared media hosts.
- Automatic review cited the risk of exposing signed session cookies to a derived third-party CDN, especially with an unrelated Referer. No signed-media compatibility success is claimed.
