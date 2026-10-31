Vyla Stream API by Vyla Entertainment; core authors @alwaysmesmerizingyou and @GavinGoGaming (see upstream README.md).
Source: https://gitlab.com/vyla-entertainment/stream-api
Pinned upstream commit: 295c0efb66d8520e9052cd4981aab58bf5b71ea6
License: CC BY-NC 4.0, see LICENSE. Noncommercial personal integration.
Local changes: pin SDK 1.20.0 and dotenv 17.4.2; remove unused latest dependency; default bind to loopback and support explicit PUBLIC_BASE_URL for private Docker networking; stream progressive MP4 responses with Range support instead of buffering the full movie.
Run only on loopback or a private container network; the upstream API/proxy has no authentication.
