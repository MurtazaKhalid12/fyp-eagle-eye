# EagleEye relay (live-video, Plane 2)

A tiny WebSocket "meeting room" that the **camera** and the **phone** both dial *out* to,
so live video works across networks (no IP, no port-forwarding).

```
camera  ->  wss://<host>/cam/<deviceId>?token=...     pushes JPEG frames
phone   ->  wss://<host>/view/<deviceId>?token=...     receives frames
```
The relay forwards the camera's binary frames to every viewer in the same room.
When the last viewer leaves it sends the camera `{"type":"no-viewers"}` so the firmware
stops streaming (saves power + bandwidth).

## Why it must be deployed (not just localhost)
The ESP32 firmware connects with **`wss://` (TLS)** on port **443**. A hosting platform
(Fly.io / Railway / Render) gives you a free HTTPS/WSS endpoint automatically. That host
name is what you put in the firmware (`DEV_RELAY_HOST` in `config.h`).

## Deploy (Railway — easiest, free)
1. Push this `relay/` folder to a GitHub repo (or use the Railway CLI).
2. On **railway.app** → New Project → Deploy from repo → pick this folder.
3. Railway auto-detects Node, runs `npm start`. It assigns a URL like
   `eagleeye-relay-production.up.railway.app`.
4. (Optional, for auth) add an env var `RELAY_SECRET` = a long random string — the same
   value goes into the `issueStreamToken` Cloud Function. Leave it unset for first bring-up
   (auth disabled).
5. Put the host in firmware `config.h`:
   ```
   #define DEV_RELAY_HOST  "eagleeye-relay-production.up.railway.app"
   #define DEV_RELAY_PORT  443
   ```

## Deploy (Fly.io alternative)
```
fly launch --no-deploy        # generates fly.toml; choose a name
fly deploy
```
Use the `*.fly.dev` host in `config.h`.

## Test it without hardware (browser)
After deploy, open the host URL in a browser → you should see "EagleEye relay up".
Then in two browser tabs' dev consoles:
```js
// tab 1 = fake camera
const cam = new WebSocket('wss://YOUR_HOST/cam/cam-01');
cam.onopen = () => setInterval(() => cam.send(new Uint8Array([1,2,3])), 200);

// tab 2 = viewer
const v = new WebSocket('wss://YOUR_HOST/view/cam-01');
v.binaryType = 'arraybuffer';
v.onmessage = e => console.log('frame', e.data.byteLength, 'bytes');
```
Tab 2 logging "frame 3 bytes" proves the relay forwards correctly.

## Auth (production)
With `RELAY_SECRET` set, connections must carry a short-lived token issued by the
`issueStreamToken` Cloud Function:
`token = base64url({"d":deviceId,"r":role,"exp":unixSeconds}) + "." + hexHMAC_SHA256(body, RELAY_SECRET)`.
The camera fetches a `cam` token; the app fetches a `view` token. Tokens expire (≤120 s),
so a leaked URL can't be reused.

## Env vars
| Var | Default | Meaning |
|---|---|---|
| `PORT` | 8080 | listen port (the host sets this for you) |
| `RELAY_SECRET` | _empty_ | HMAC secret; empty = auth OFF (dev) |
| `MAX_FPS` | 15 | advisory cap (frames are passed through as-is) |
