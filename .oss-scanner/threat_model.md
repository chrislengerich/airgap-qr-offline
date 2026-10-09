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

Attack surfaces:
1. **HTTP requests to `server.js`.** The site is deployed on the public
   internet (at qrft.org), so treat every request as adversarial. Inputs: the decoded URL
   path, `Host`, and `X-Forwarded-Proto`. Site is static, any compromises on 
   the webserver that compromise the hosted site, network or github repo are high-sev.
2. **Sender-side inputs** (picked file, pasted text) are local user inputs and
   a primary attack surface.
3. Static dependencies - dependencies are trusted, but only those that are 
   served from the repo's static files, which change slowly.

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
