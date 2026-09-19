# Airgapped QR File Transfer (Offline Version)

Airgapped QR File Transfer is a simple web-based tool to transfer data between devices using QR codes. It allows for the transfer of files without the need for network connectivity, leveraging QR codes to encode and decode file data. The web pages are fully self-contained: pako for compression, qrcode.js for QR code generation, and jsQR for scanning — no CDN, framework or WASM dependencies.

This is a fully offline and heavily rewritten fork of the nice work of https://github.com/mohankumarelec/airgap-qr-transfer.git.

## Online @:
https://qrft.org

## Offline / Single-File Version

`offline/*` is fully self-contained: pako, qrcodejs and jsQR are inlined, so there are no CDN, Vue or WASM dependencies. They work from `file://` and are served with a service worker (`offline/sw.js`) so that once a page is opened over http(s) the browser precaches it and it keeps working — fully interactive, camera included — when offline. Rebuild them with `python3 build_offline.py`; the pinned libraries live in `offline/vendor/`.

Differences from the online version:

- The offline scanner uses **jsQR** (pure JavaScript) instead of zbar-wasm, so no WASM file needs to be fetched.
- The offline sender adds Prev/Next buttons and a speed selector. Both senders auto-advance continuously, looping through metadata → every chunk → back to metadata until stopped, and both accept a pasted text message in place of a file.
- The wire format is unchanged, so online and offline pages interoperate.

## Features

- **Data Sender Mode**: Allows a user to select a file, compress it, and transfer it via QR codes.
- **Data Receiver Mode**: Allows a user to scan QR codes to receive and reconstruct the file.
- **File Compression**: Uses gzip compression to reduce the size of the data being transferred.
- **QR Code Generation and Scanning**: Uses qrcode.js for generation and jsQR for scanning QR codes.

## Getting Started

### Prerequisites

- A modern web browser (preferably Chrome or Firefox) that supports JavaScript and the WebRTC API.
- Node.js 18+ only if you want to run the bundled static server (any other static file server works too).

### Local server

The receiver needs a **secure context** for camera access, so serve the pages over http(s) rather than opening them from `file://`. The bundled zero-dependency server (`server.js`, the same one used for deployment) serves the `offline/` folder:

```sh
npm start                  # serves offline/ at http://localhost:3000
PORT=8000 npm start        # different port
```

Open <http://localhost:3000/> — `localhost` is a secure context, so the scanner can use the camera. The server only redirects plain http to https when it detects a reverse proxy (`X-Forwarded-Proto` header, e.g. on Heroku); locally it serves plain http as-is.

Any other static file server works too, e.g.:

```sh
python3 -m http.server -d offline 8000
```

### Data Sender (offline/generator.html)

1. **Source Selection**: The user either picks a file from their device or pastes text into the text box (text takes priority over any selected file). Text is sent as a file named `Paste @ <timestamp>` (local time, e.g. `Paste @ 2026-08-11_14-30-05`), and the sender's status line shows that name once transfer starts.
2. **Validation**: Text is checked for an empty value, a size limit (`1000000` characters), and malformed Unicode (unpaired surrogates) before sending; file names are sanitized to a bare, safe name.
3. **Compression**: The payload is compressed using the pako library.
4. **Chunking**: The compressed payload is split into smaller chunks.
5. **QR Code Generation**: Each chunk is encoded into a QR code using qrcode.js.
6. **Display QR Codes**: The QR codes are displayed sequentially for the receiver to scan.

### Data Receiver (offline/scanner.html)

1. **QR Code Scanning**: The device's camera scans QR codes using jsQR.
2. **Decoding**: Each QR code is decoded to extract the chunk of data.
3. **Reconstruction**: The chunks are reassembled into the original compressed file.
4. **Decompression**: The file is decompressed using pako.
5. **File Download**: The reconstructed file is made available for download.

## Python CLI

`airgap_qr.py` is a Python port with a byte-for-byte compatible wire format, so the Python and web tools interoperate in any combination.

Dependencies:

```sh
pip install qrcode[pil] opencv-python    # sender
pip install opencv-python zxing-cpp      # receiver
```

Usage:

```sh
python3 airgap_qr.py send FILE       # compress + show QR codes on screen
python3 airgap_qr.py receive         # scan QR codes from the camera, rebuild file
python3 airgap_qr.py selfcheck       # offline round-trip test (no camera needed)
```

Sender keys: `Space`/`Enter` next, `p`/`Backspace` previous, `q`/`Esc` quit. Add `--delay SEC` to auto-advance.

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch (`git checkout -b feature-branch`).
3. Make your changes.
4. Commit your changes (`git commit -am 'Add new feature'`).
5. Push to the branch (`git push origin feature-branch`).
6. Create a new Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments
- [pako](https://github.com/nodeca/pako) - Compression library.
- [qrcode.js](https://github.com/davidshimjs/qrcodejs) - QR code generation library.
- [jsQR](https://github.com/cozmo/jsQR) - QR code scanning library.
- [zxing-cpp](https://github.com/nu-book/zxing-cpp) - QR code scanning for the Python CLI.
