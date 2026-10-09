# Threat model — airgap-qr-offline

## What this project does and where untrusted input enters

A browser-based tool for moving files and text across an air gap: a sender page
(`offline/generator.html`) compresses data with pako, splits it into chunks, and
renders each chunk as a QR code; a receiver page (`offline/scanner.html`) scans
those codes with the camera, reassembles the chunks, gunzips the payload, and
offers it as a download. The pages are fully static and self-contained (pako,
qrcodejs and jsQR are vendored and inlined), served by a small zero-dependency
Node static file server (`server.js`). Hosted publicly at https://qrft.org and
self-hostable (Heroku/Cloud Run/Amplify instructions in README.md).

Trust boundaries, in priority order:

1. **HTTP requests to `server.js`.** The site is deployed on the public
   internet, so treat every request as adversarial. Inputs: the decoded URL
   path, `Host`, and `X-Forwarded-Proto`. The server reads files from disk and
   serves them; its contract is to serve **only** files under `offline/` —
   anything outside that directory must never be served, no matter how the
   path is encoded, normalized, or prefixed. Arbitrary file read / path
   traversal is the highest-value bug class here.
2. **The QR wire format — fully adversarial.** An attacker can display
   arbitrary QR codes to a victim's camera (e.g., a malicious web page shown
   on the sender screen, or a tampered sender). Every frame is attacker
   controlled: a metadata frame of JSON `{"name", "chunks", "size"}` (`size`
   is optional per `valid_meta`; `chunks` integer 1..1000000; `size` integer
   0..3 GiB; `name` string up to 5000 chars), then chunk frames
   `<index>,<base64>` whose bytes are treated as latin-1 and re-encoded as
   UTF-8. The receiver inflates the reassembled payload and writes it to
   disk under a name derived from `meta.name`. Inflate is streamed and
   hard-capped: declared size + 1 MiB slack, or 3 GiB when size is omitted —
   a decompression bomb must abort at the cap, never materialize past it.
   Only the first gzip member is inflated (no re-sync into trailing data).
3. **Sender-side inputs** (picked file, pasted text) are local user input —
   lower priority. The sender sanitizes the file name before encoding
   (`../../pwned.txt` must arrive as `pwned.txt`), validates pasted text
   (1,000,000-char limit, unpaired-surrogate rejection), and applies the
   receiver's limits before rendering any QR code: a file over 3 GiB (or a
   compression past 1 000 000 chunks) is refused.
4. **The received file itself is attacker content by design** — this is a
   data diode. Do not report that the tool "allows transferring malicious
   files"; that is the feature.

## Components that matter most / least

Most:

- `offline/templates/scanner.tpl.html` (built into `offline/scanner.html`):
  the whole receiver pipeline — `valid_meta` (declared size is optional;
  when omitted, inflate is capped at 3 GiB instead of the exact-match
  check), chunk index/base64 parsing and range checks, reassembly into a
  preallocated `Uint8Array` (no per-chunk plain-JS-array growth), streamed
  inflate with a hard output cap (see above — bombs must abort at the cap,
  never materialize past it), `safe_filename` (strips path separators and
  U+0000–U+001F/U+007F, collapses `.`/`..`, caps at 200 chars, falls back
  to `received_file.bin`), and `download_file` (blob + `a.download`).
- `offline/templates/generator.tpl.html`: send-side filename sanitization and
  pasted-text validation.
- `server.js`: path handling, the `X-Forwarded-Proto` redirect, MIME and
  cache headers.
- `offline/sw.js`: cache-first service worker (precaches the four pages,
  caches any same-origin GET). Bugs here persist across visits — cache
  poisoning that leads to code execution is the worst case for this app.
- `offline/build_offline.py`: build-time script that splices the vendored
  libraries into the templates (escaping `</script`). Its inputs are pinned
  in-repo files, so treat it as lower priority — but an escaping bug there
  would inject script into every built page.

Least:

- `offline/vendor/*` — third-party snapshots (pako 2.0.3, qrcodejs 1.0.0,
  jsQR 1.4.0), inlined. In scope **only** when a defect is reachable through
  this app's use (e.g., pako inflate on attacker-shaped data); please label
  such findings as third-party. Do not report library-internal issues with no
  path through this app.
- `index.html` / `about.html` / `Procfile` — static content and config, little
  logic.

## How to exercise it

- Build: `python3 offline/build_offline.py` (offline; vendored libs are committed).
- Tests: `npm test` (Node's built-in runner). `test/helpers.mjs` loads the real
  built pages into a `node:vm` sandbox with DOM/camera stubs;
  `test/transfer.test.mjs` drives end-to-end transfers and already contains
  adversarial cases (malformed metadata, bad indices, `__proto__`, traversal
  names, pre-metadata chunks, decompression bombs, transfer-size limits), and
  `test/server.test.mjs` pins the server's path contract (raw and encoded
  traversal, sibling directories sharing the root's name prefix). This harness
  is the ideal place to prototype receiver PoCs: `encodeChunk(i, bytes)` builds
  a chunk frame and `senderFrames(name, bytes, {gzipSync})` builds an honest
  frame sequence — modify them to craft malicious ones.
- Serve: `npm start` → `http://localhost:3000` (`PORT` env supported).
  For `server.js` PoCs, plain `curl` suffices.
- A receiver PoC is a frame sequence: metadata JSON followed by
  `i,<base64>` frames whose decoded bytes are the latin-1 re-encoding of the
  gzip data (exactly what `encodeChunk` produces).

## How you rate severity

- **Critical:** arbitrary file read / path traversal in `server.js`; RCE in
  `server.js` or the build; any XSS that persists in the service worker cache
  (cache poisoning → code runs on every future visit to the site).
- **High:** HTML/DOM injection reachable from the QR wire format or metadata
  fields in generator/scanner (today dynamic strings are rendered via
  `textContent` only — anything that reaches `innerHTML` or an event handler
  is at least High); prototype pollution with concrete security impact.
- **Medium:** client-side DoS — bypasses of the inflate cap (declared size +
  1 MiB slack, or 3 GiB when size is omitted), memory amplification during
  reassembly, unbounded loops, ReDoS; logic bugs that splice or corrupt
  transfers between senders or complete with wrong bytes (beyond a cosmetic
  correctness nit); sanitizer bypasses that let path components, control
  characters, or RTL-override tricks reach `a.download`; service worker
  staleness bugs without code execution.
- **Low:** missing hardening headers, MIME confusion on unusual extensions,
  cache-header issues, informational path/stack disclosure, wire-format spec
  nits with no security effect.
- Explicitly **not** issues: receiving malicious file content (by design);
  no auth on the static server (by design); plain-http on localhost
  (localhost is a secure context — intentional for local testing); trusting
  `X-Forwarded-Proto` behind a reverse proxy is the documented deployment
  contract (Heroku/Cloud Run) — only interesting if spoofing it enables
  something concrete on a directly exposed origin.

## Anything to leave alone

- Do not rate the absence of CSP/SRI/other hardening headers above Low — the
  app is deliberately a self-contained static tool with all libraries vendored
  and no third-party origins.
- Do not report cache-first service worker staleness after an update as more
  than Low — the versioned cache name (`airgap-qr-offline-v3`) plus
  `skipWaiting` is the intended refresh mechanism.
- Findings in `offline/vendor/*` should be marked third-party and only
  reported when reachable through this app.

## Reports and dedup

- Dedupe by root cause and sink, not by symptom: e.g., all injections through
  `meta.name` into the DOM are one finding; all `safe_filename` bypasses are
  one; all `server.js` traversal variants are one.
- PoC format: a QR frame sequence (metadata + chunk frames) for receiver
  bugs, a `curl` command for `server.js` bugs.
- A minimal patch is preferred to demonstrate the fix; a merge-ready patch is
  welcome — the codebase is small and `test/` will validate it.
- If you patch something found here, a credit line such as
  `Discovered by Anthropic's OSS Scanner, as vulnerability ANT-2026-XXXXXXX`
  in the commit message is appreciated.
