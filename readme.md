# Airgapped QR Code Transfer Web App

Airgapped QR Code Transfer is a simple web-based tool to transfer data between devices using QR codes. It allows for the transfer of files without the need for network connectivity, leveraging QR codes to encode and decode file data. This project uses Vue.js for the frontend and libraries like pako for compression, qrcode.js for QR code generation, and zbar-wasm for QR code scanning.

This is a fork of https://github.com/mohankumarelec/airgap-qr-transfer.git, improved to be available fully offline (after initial download), along with other stability improvements.

## Live Online Demo:
https://qrft.org

## Features

- **Data Sender Mode**: Allows a user to select a file, compress it, and transfer it via QR codes.
- **Data Receiver Mode**: Allows a user to scan QR codes to receive and reconstruct the file.
- **File Compression**: Uses gzip compression to reduce the size of the data being transferred.
- **QR Code Generation and Scanning**: Uses qrcode.js for generation and zbar-wasm for scanning QR codes.

## Getting Started

### Prerequisites

- A modern web browser (preferably Chrome or Firefox) that supports JavaScript and the WebRTC API.

### Installing

1. Clone the repository:

```sh
git clone https://github.com/chrislengerich/airgap-qr-transfer.git
cd airgap-qr-transfer
```

### Data Sender (generator.html)

1. **Source Selection**: The user either picks a file from their device or pastes text into the text box (text takes priority over any selected file). Text is sent as a file named `Paste @ <timestamp>` (local time, e.g. `Paste @ 2026-08-11_14-30-05`), and the sender's status line shows that name once transfer starts.
2. **Validation**: Text is checked for an empty value, a size limit (`1000000` characters), and malformed Unicode (unpaired surrogates) before sending; file names are sanitized to a bare, safe name.
3. **Compression**: The payload is compressed using the pako library.
4. **Chunking**: The compressed payload is split into smaller chunks.
5. **QR Code Generation**: Each chunk is encoded into a QR code using qrcode.js.
6. **Display QR Codes**: The QR codes are displayed sequentially for the receiver to scan.

### Data Receiver (scanner.html)

1. **QR Code Scanning**: The device's camera scans QR codes using zbar-wasm.
2. **Decoding**: Each QR code is decoded to extract the chunk of data.
3. **Reconstruction**: The chunks are reassembled into the original compressed file.
4. **Decompression**: The file is decompressed using pako.
5. **File Download**: The reconstructed file is made available for download.

## Offline / Single-File Version

`offline/generator.html`, `offline/scanner.html` and `offline/index.html` are fully self-contained: pako, qrcodejs and jsQR are inlined, so there are no CDN, Vue or WASM dependencies. They work from `file://` and are served with a service worker (`offline/sw.js`) so that once a page is opened over http(s) the browser precaches it and it keeps working — fully interactive, camera included — when offline. Rebuild them with `python3 build_offline.py`; the pinned libraries live in `offline/vendor/`.

Differences from the online version:

- The offline scanner uses **jsQR** (pure JavaScript) instead of zbar-wasm, so no WASM file needs to be fetched.
- The offline sender adds Prev/Next buttons and a speed selector. Both senders auto-advance continuously, looping through metadata → every chunk → back to metadata until stopped, and both accept a pasted text message in place of a file.
- The wire format is unchanged, so online and offline pages interoperate.

### Camera access and Android (Vanadium / GrapheneOS)

The receiver needs `getUserMedia`, which browsers only expose on **secure contexts**. Chromium-based browsers (including Vanadium) do not treat `file://` as a secure context, so the offline scanner cannot access the camera when opened directly from a file on Android — a "Camera unavailable" message is shown. The sender needs no camera and works fine from `file://`.

To use the receiver offline on Android:

1. **Serve the folder locally** (guaranteed to work): on the phone, run `python3 -m http.server 8000` in a terminal app (e.g. Termux), then open `http://localhost:8000/scanner.html` in Vanadium. `localhost` is a secure context, so the camera works with no network at all.
2. **Let the service worker cache it** (recommended for a phone): the pages register `offline/sw.js`, which precaches `index.html`, `generator.html` and `scanner.html`. Open `https://<host>/scanner.html` once while online so the cache is populated, then open the *same URL* again with no network — the browser serves the cached, fully interactive page, and `https` keeps the camera usable.

   A deployed copy is available at `https://airgap-qr-offline-32e58287c4cc.herokuapp.com/` (see the `Procfile`/`server.js` in the repo root). Redeploy after rebuilding with `git push heroku feat/python-and-offline:main`.

> **Why not "Download page"?** Chromium intentionally disables every form control (buttons, inputs, selects) in MHTML files, and Android's "Download page" produces an MHTML file. The saved copy therefore renders with all buttons greyed out and cannot be interacted with — there is no way around this restriction. Use the service worker path instead.


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

- [Vue.js](https://vuejs.org/) - JavaScript framework for building user interfaces.
- [pako](https://github.com/nodeca/pako) - Compression library.
- [qrcode.js](https://github.com/davidshimjs/qrcodejs) - QR code generation library.
- [zbar-wasm](https://github.com/undecaf/zbar-wasm) - QR code scanning library.
