# Airgapped QR File Transfer (Offline Version)

Airgapped QR File Transfer is a simple static JS site to transfer data between devices using QR codes. It allows for the transfer of files without the need for network connectivity, leveraging QR codes to encode and decode file data. The web pages are fully self-contained: pako for compression, qrcode.js for QR code generation, and jsQR for scanning — no CDN, framework or WASM dependencies.

This is a fully offline and heavily rewritten fork of the nice work of https://github.com/mohankumarelec/airgap-qr-transfer.git.

## Online @:
https://qrft.org

## Installation
Visit the above link once, and bookmark it in your browser (on Android, via hamburger icon -> "Install shortcut"). After the initial load, the page will be cached and available offline.

## Features

### Fully offline

- pako, qrcodejs and jsQR are inlined, and there are no CDN, Vue or WASM dependencies that require fetches on each use. They work from `file://` and are served with a service worker (`offline/sw.js`) so that once a page is opened once over http(s) the browser precaches it and it keeps working — fully interactive, camera included — when offline. Rebuild them with `python3 build_offline.py`; the pinned libraries live in `offline/vendor/`.
- Wire format is preserved, so QR codes are compatible with scanners from the online repo.

### Transfers both files and pastes

- The sender adds Prev/Next buttons, a speed selector and support for pastes in addition to files. 

### Hardening and self-hosting instructions

- Adds basic hardening and unit tests against malicious payloads and self-hosting instructions for popular cloud providers.

## Technical overview

### Data Sender (offline/generator.html)

1. **Source Selection**: The user either picks a file from their device or pastes text into the text box (text takes priority over any selected file). Pastes are sent as a file named `Paste @ <timestamp>` (local time, e.g. `Paste @ 2026-08-11_14-30-05`).
2. **Validation**: Text is checked for an empty value, a size limit (`1000000` characters), and malformed Unicode (unpaired surrogates) before sending; file names are sanitized to a bare, safe name.
3. **Compression**: The payload is compressed using the pako library.
4. **Chunking**: The compressed payload is split into smaller chunks.
5. **QR Code Generation**: Each chunk is encoded into a QR code using qrcode.js.
6. **Display QR Codes**: The QR codes are displayed sequentially for the receiver to scan. The sender auto-advances continuously, looping through metadata → every chunk → back to metadata until stopped.

### Data Receiver (offline/scanner.html)

1. **QR Code Scanning**: The device's camera scans QR codes using jsQR.
2. **Decoding**: Each QR code is decoded to extract the chunk of data.
3. **Reconstruction**: The chunks are reassembled into the original compressed file.
4. **Decompression**: The file is decompressed using pako.
5. **File Download**: The reconstructed file is made available for download.

## Self-Hosting

The receiver needs a **secure context** for camera access, so serve the pages over https. The site is fully static (`offline/`), needs no build step, and has zero dependencies. The bundled zero-dependency Node server (`server.js`, Node 18+) serves it, listens on `$PORT` (default `3000`), and auto-redirects plain http to https when behind a reverse proxy that sets `X-Forwarded-Proto` (e.g. Heroku or Cloud Run). To test locally, `npm start` serves `offline/` at <http://localhost:3000/> — `localhost` is a secure context, so the scanner can use the camera.

### Heroku

The repo ships with a `Procfile` (`web: npm start`), so it deploys as-is:

```sh
heroku create my-airgap-qr
git push heroku main
heroku open
```

Heroku terminates TLS and sets `X-Forwarded-Proto`, so the bundled server's http→https redirect works out of the box.

### Google Cloud (Cloud Run)

`gcloud run deploy` builds the repo with Google Cloud buildpacks, which honor the included `Procfile`, and provisions TLS for you:

```sh
gcloud run deploy airgap-qr --source . --region us-central1 --allow-unauthenticated
```

### AWS (Amplify Hosting)

Since the site is static, host the `offline/` files directly — no Node server needed. In the [Amplify Hosting console](https://console.aws.amazon.com/amplify/), connect the GitHub repo and use this build spec (no build, static artifacts):

```yaml
version: 1
frontend:
  phases:
    build:
      commands: []
  artifacts:
    baseDirectory: offline
    files:
      - "**/*"
```

Amplify provisions the https domain. (An S3 bucket alone won't work — its website endpoint is plain http, and the camera needs a secure context; if you prefer S3, put CloudFront with https in front of it.)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the repo's assumptions (minimal code, minimal features, broad platform compatibility) and how to submit changes.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

It is a heavily modified fork of [Airgapped QR Code Transfer](https://github.com/mohankumarelec/airgapped-qr-code-transfer) by Mohankumar Ramachandran, which was originally released under the MIT License. Due to extensive rewriting, original MIT-licensed code is interleaved throughout the codebase; the original MIT copyright notice and license text are preserved verbatim in the [LICENSE](LICENSE) file, as that license requires.

## Acknowledgments
- [pako](https://github.com/nodeca/pako) - Compression library.
- [qrcode.js](https://github.com/davidshimjs/qrcodejs) - QR code generation library.
- [jsQR](https://github.com/cozmo/jsQR) - QR code scanning library.
