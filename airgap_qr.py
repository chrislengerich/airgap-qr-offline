#!/usr/bin/env python3
"""Airgapped file transfer using QR codes (Python port of the JS web app).

The wire format is byte-for-byte compatible with generator.html / scanner.html:

  * The whole file is gzip-compressed (level 9), then split into chunks of
    250 compressed bytes.
  * The first QR code carries the metadata JSON: {"name":"...","chunks":N}
  * Every following QR code carries "<index>,<base64(chunk)>" where the chunk
    bytes are first mapped through latin1 -> UTF-8 before base64, exactly like
    the JS encode_data()/decode_data() pair.

Usage:
  python3 airgap_qr.py send FILE [--delay SEC] [--no-fullscreen]
  python3 airgap_qr.py receive [-o OUT] [--camera N]
  python3 airgap_qr.py selfcheck

Dependencies (only needed for the mode you use):
  send:      pip install qrcode[pil] opencv-python
  receive:   pip install opencv-python zxing-cpp
  selfcheck: stdlib only for the codec part, deps for the image part
"""

import argparse
import base64
import gzip
import json
import os
import random
import sys
import time

CHUNK_SIZE = 250  # compressed bytes per QR; must match JS `chunk_size`


def encode_chunk(index, data):
    """Replicate JS encode_data(): binary string -> UTF-8 bytes -> base64."""
    binary_string = bytes(data).decode("latin-1")
    utf8_bytes = binary_string.encode("utf-8")
    return "{},{}".format(index, base64.b64encode(utf8_bytes).decode("ascii"))


def decode_chunk(payload):
    """Inverse of encode_chunk(): base64 -> UTF-8 -> binary string -> bytes."""
    index, b64 = payload.split(",", 1)
    utf8_bytes = base64.b64decode(b64)
    binary_string = utf8_bytes.decode("utf-8")
    return int(index), bytearray(binary_string.encode("latin-1"))


def build_frames(compressed, filename):
    """Return [metadata_payload, chunk_0_payload, chunk_1_payload, ...]."""
    total = (len(compressed) + CHUNK_SIZE - 1) // CHUNK_SIZE
    meta = json.dumps({"name": filename, "chunks": total}, separators=(",", ":"))
    frames = [meta]
    for i in range(total):
        frames.append(
            encode_chunk(i, compressed[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE])
        )
    return frames


def _deps_send():
    try:
        import cv2
        import numpy as np
        import qrcode
        from PIL import Image
        return cv2, np, qrcode, Image
    except ImportError as exc:
        sys.exit(
            "Missing dependency ({}). Install with: "
            "pip install qrcode[pil] opencv-python".format(exc)
        )


def _deps_receive():
    try:
        import cv2
        import numpy as np
        import zxingcpp
        return cv2, np, zxingcpp
    except ImportError as exc:
        sys.exit(
            "Missing dependency ({}). Install with: "
            "pip install opencv-python zxing-cpp".format(exc)
        )


def qr_image(np_, qrcode, Image, text, size=1100):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")
    img = img.resize((size, size), Image.NEAREST)
    return np_.array(img, dtype=np_.uint8)


def with_label(np_, cv2, img, label, strip=140):
    height, width = img.shape[:2]
    canvas = np_.full((height + strip, width), 255, dtype=np_.uint8)
    canvas[:height, :] = img
    cv2.putText(
        canvas, label, (40, height + strip // 2 + 12),
        cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3,
    )
    return canvas


def send(path, delay=0.0, fullscreen=True):
    cv2, np_, qrcode, Image = _deps_send()

    with open(path, "rb") as f:
        raw = f.read()
    print("Compressing {} ({} bytes) ...".format(path, len(raw)))
    compressed = gzip.compress(raw, compresslevel=9)
    frames = build_frames(compressed, os.path.basename(path))
    total = len(frames) - 1
    print("{} chunk(s) to send".format(total))

    win = "QR Sender"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    if fullscreen:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    idx = 0
    shown = -1
    while True:
        if idx != shown:
            label = "METADATA" if idx == 0 else "CHUNK {}/{}".format(idx, total)
            img = with_label(np_, cv2, qr_image(np_, qrcode, Image, frames[idx]), label)
            cv2.imshow(win, img)
            print(label, flush=True)
            shown = idx

        if delay > 0:
            key = cv2.waitKey(int(delay * 1000))
        else:
            if shown == idx:
                print("  [Space/Enter] next   [p/Backspace] prev   [q/Esc] quit")
            key = cv2.waitKey(0)

        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (8, ord("p"), ord("P")):
            idx = max(0, idx - 1)
        elif key in (13, 32, ord("n"), ord("N"), ord("s"), ord("S")):
            if idx < len(frames) - 1:
                idx += 1
    cv2.destroyAllWindows()
    print("Done.")


def receive(output=None, camera=0):
    cv2, np_, zxingcpp = _deps_receive()

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        sys.exit("Cannot open camera {}".format(camera))

    decoded = {}
    meta = None
    out_name = output
    started = time.time()

    win = "QR Receiver"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    print("Point the camera at the sender's screen. q/Esc to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for barcode in zxingcpp.read_barcodes(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ):
            data = barcode.text
            if "chunks" in data:
                try:
                    new_meta = json.loads(data)
                except ValueError:
                    pass
                else:
                    if new_meta != meta:
                        meta = new_meta
                        decoded = {}
                        out_name = output or meta["name"]
                        print(
                            "Receiving {} ({} chunks) ...".format(
                                meta["name"], meta["chunks"]
                            )
                        )
            elif data.count(",") == 1:
                try:
                    idx, chunk = decode_chunk(data)
                except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                    continue
                if idx not in decoded:
                    decoded[idx] = chunk
                    got = len(decoded)
                    total = meta["chunks"] if meta else "?"
                    print("  chunk {}/{}".format(got, total), flush=True)
                    if meta and got == meta["chunks"]:
                        break

        if meta and len(decoded) == meta["chunks"]:
            break

        status = "{}  {}/{}".format(
            meta["name"] if meta else "waiting for metadata...",
            len(decoded),
            meta["chunks"] if meta else "?",
        )
        cv2.putText(frame, status, (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imshow(win, frame)
        key = cv2.waitKey(1)
        if key in (27, ord("q"), ord("Q")):
            break

    cap.release()
    cv2.destroyAllWindows()

    if not meta or len(decoded) != meta["chunks"]:
        sys.exit(
            "Transfer incomplete: got {}/{} chunks".format(
                len(decoded), meta["chunks"] if meta else 0
            )
        )

    ordered = bytearray()
    for i in range(meta["chunks"]):
        ordered += decoded[i]
    try:
        raw = gzip.decompress(bytes(ordered))
    except OSError:
        raw = bytes(ordered)
        out_name = (out_name or "out") + ".gz"
        print("WARNING: decompression failed, wrote raw gzip payload instead.")

    with open(out_name, "wb") as f:
        f.write(raw)
    print(
        "Saved {} ({} bytes) in {:.1f}s".format(
            out_name, len(raw), time.time() - started
        )
    )


def selfcheck():
    ok = True
    random.seed(42)
    for size in (0, 1, 250, 12345):
        buf = bytes(random.randrange(256) for _ in range(size))
        compressed = gzip.compress(buf, compresslevel=9)
        frames = build_frames(compressed, "selfcheck.bin")
        meta = json.loads(frames[0])
        chunks = {}
        for frame in frames[1:]:
            idx, chunk = decode_chunk(frame)
            chunks[idx] = chunk
        assert len(chunks) == meta["chunks"]
        ordered = bytearray()
        for i in range(meta["chunks"]):
            ordered += chunks[i]
        assert gzip.decompress(bytes(ordered)) == buf
        print(
            "codec round-trip OK: {}-byte buffer -> {} chunks".format(
                size, meta["chunks"]
            )
        )

        try:
            import qrcode
            from PIL import Image
        except ImportError:
            ok = False
            continue
        np_ = __import__("numpy")
        try:
            import zxingcpp

            def read_qr(img):
                results = zxingcpp.read_barcodes(img)
                return results[0].text if results else ""
        except ImportError:
            try:
                import cv2
            except ImportError:
                ok = False
                continue
            _det = cv2.QRCodeDetector()

            def read_qr(img):
                text, _p, _q = _det.detectAndDecode(img)
                return text

        for i, frame in enumerate(frames):
            text = read_qr(qr_image(np_, qrcode, Image, frame))
            assert text == frame, "QR image decode mismatch on frame {}".format(i)
        print("  QR image round-trip OK for {}-byte buffer".format(size))

    print("All selfchecks passed.")
    if not ok:
        print("(install qrcode[pil] and opencv-python/zxing-cpp to enable the image round-trip)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send", help="show QR codes for a file on screen")
    s.add_argument("file")
    s.add_argument("--delay", type=float, default=0.0, metavar="SEC",
                   help="auto-advance every SEC seconds (default: wait for a key)")
    s.add_argument("--no-fullscreen", action="store_true",
                   help="show QR codes in a window instead of fullscreen")
    s.set_defaults(cmd="send")

    r = sub.add_parser("receive", help="scan QR codes from the camera and rebuild the file")
    r.add_argument("-o", "--out", help="output path (default: original file name)")
    r.add_argument("--camera", type=int, default=0, help="camera index (default: 0)")
    r.set_defaults(cmd="receive")

    sub.add_parser("selfcheck", help="round-trip a random buffer (no camera needed)")
    args = parser.parse_args(argv)

    if args.cmd == "send":
        send(args.file, delay=args.delay, fullscreen=not args.no_fullscreen)
    elif args.cmd == "receive":
        receive(output=args.out, camera=args.camera)
    elif args.cmd == "selfcheck":
        selfcheck()


if __name__ == "__main__":
    main()
