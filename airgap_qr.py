#!/usr/bin/env python3
"""Airgapped file transfer using QR codes (Python port of the JS web app).

The wire format is byte-for-byte compatible with generator.html / scanner.html:

  * The whole file is gzip-compressed (level 9), then split into chunks of
    250 compressed bytes.
  * The first QR code carries the metadata JSON:
    {"name":"...","chunks":N,"size":M}. `size` (original byte count) is
    optional and ignored by older receivers; receivers validate the
    decompressed length against it when present.
  * Every following QR code carries "<index>,<base64(chunk)>" where the chunk
    bytes are first mapped through latin1 -> UTF-8 before base64, exactly like
    the JS encode_data()/decode_data() pair.

Receivers reject untrusted input: names are reduced to a bare file name
(no path components), metadata must pass validate_meta(), chunk indices are
bounded, and reconstruct() refuses corrupt or size-mismatched payloads.

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

# Upper bounds enforced by receivers so a malicious sender cannot cause
# unbounded memory allocation, loops, or absurd file names.
MAX_CHUNKS = 200000  # must match MAX_CHUNKS in scanner.html / offline scanner
MAX_SIZE = 64 * 1024 * 1024  # decompressed bytes; must match MAX_SIZE in JS
DEFAULT_NAME = "received_file.bin"


def safe_filename(name):
    """Reduce a sender-supplied name to a bare, safe file name.

    Strips path components (blocks traversal like "../x" or "/etc/passwd"),
    removes control characters, caps the length, and falls back to a default.
    """
    n = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    n = "".join(ch for ch in n if ch >= " " and ch != "\x7f")
    n = n.strip().rstrip(".")
    if n in ("", ".", ".."):
        n = ""
    n = n[:200]
    return n or DEFAULT_NAME


def validate_meta(m):
    """Reject malformed or abusive metadata from an untrusted sender."""
    if not isinstance(m, dict):
        return False
    if not isinstance(m.get("name"), str) or not m.get("name"):
        return False
    chunks = m.get("chunks")
    if not isinstance(chunks, int) or isinstance(chunks, bool):
        return False
    if not (1 <= chunks <= MAX_CHUNKS):
        return False
    size = m.get("size")
    if size is not None:
        if not isinstance(size, int) or isinstance(size, bool):
            return False
        if not (0 <= size <= MAX_SIZE):
            return False
    return True


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


def build_frames(compressed, filename, size):
    """Return [metadata_payload, chunk_0_payload, chunk_1_payload, ...]."""
    total = (len(compressed) + CHUNK_SIZE - 1) // CHUNK_SIZE
    meta = json.dumps(
        {"name": safe_filename(filename), "chunks": total, "size": size},
        separators=(",", ":"),
    )
    frames = [meta]
    for i in range(total):
        frames.append(
            encode_chunk(i, compressed[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE])
        )
    return frames


def reconstruct(meta, chunks):
    """Validate and reassemble received chunks into the original bytes.

    Raises ValueError on decompression failure or size mismatch instead of
    returning garbage for the caller to write to disk.
    """
    ordered = bytearray()
    for i in range(meta["chunks"]):
        ordered += chunks[i]
    try:
        raw = gzip.decompress(bytes(ordered))
    except OSError:
        raise ValueError(
            "decompression failed: data is corrupt or not a valid transfer"
        )
    if meta.get("size") is not None and len(raw) != meta["size"]:
        raise ValueError(
            "size mismatch: expected {} bytes, got {}".format(meta["size"], len(raw))
        )
    return bytes(raw)


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
    frames = build_frames(compressed, os.path.basename(path), len(raw))
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
            if data.startswith("{"):
                try:
                    new_meta = json.loads(data)
                except ValueError:
                    pass
                else:
                    if validate_meta(new_meta) and new_meta != meta:
                        meta = new_meta
                        decoded = {}
                        out_name = output or safe_filename(meta["name"])
                        print(
                            "Receiving {} ({} chunks) ...".format(
                                meta["name"], meta["chunks"]
                            )
                        )
            elif meta and data.count(",") == 1:
                try:
                    idx, chunk = decode_chunk(data)
                except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                    continue
                if not (0 <= idx < meta["chunks"]):
                    continue
                if idx not in decoded:
                    decoded[idx] = chunk
                    got = len(decoded)
                    total = meta["chunks"]
                    print("  chunk {}/{}".format(got, total), flush=True)
                    if got == meta["chunks"]:
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

    try:
        raw = reconstruct(meta, decoded)
    except ValueError as exc:
        sys.exit("Transfer failed: {}".format(exc))

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
        frames = build_frames(compressed, "selfcheck.bin", size)
        meta = json.loads(frames[0])
        assert validate_meta(meta)
        assert meta["size"] == size
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

    print("--- security validation ---")
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("/abs/path/file.bin") == "file.bin"
    assert safe_filename("..\\..\\win\\evil.txt") == "evil.txt"
    assert safe_filename("a\n\x00b\r") == "ab"
    assert safe_filename("") == DEFAULT_NAME
    assert safe_filename("x" * 500) == "x" * 200
    assert validate_meta({"name": "a", "chunks": 0}) is False
    assert validate_meta({"name": "a", "chunks": MAX_CHUNKS + 1}) is False
    assert validate_meta({"name": "", "chunks": 1}) is False
    assert validate_meta({"name": "a", "chunks": 1}) is True
    assert validate_meta({"name": "a", "chunks": 1, "size": -1}) is False
    assert validate_meta({"name": "a", "chunks": 1, "size": MAX_SIZE + 1}) is False
    assert validate_meta({"name": "a", "chunks": 1, "size": 7}) is True
    buf = b"hello"
    compressed = gzip.compress(buf, compresslevel=9)
    frames = build_frames(compressed, "ok.bin", len(buf))
    chunks = {}
    for frame in frames[1:]:
        idx, chunk = decode_chunk(frame)
        chunks[idx] = chunk
    assert reconstruct(json.loads(frames[0]), chunks) == buf
    try:
        reconstruct(json.loads(frames[0]), {0: bytearray(b"garbage")})
        raise AssertionError("corrupt payload must be rejected")
    except ValueError:
        pass
    bad_meta = {"name": "x", "chunks": 1, "size": 99}
    try:
        reconstruct(bad_meta, chunks)
        raise AssertionError("size mismatch must be rejected")
    except ValueError:
        pass
    print("  all security checks passed")

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
