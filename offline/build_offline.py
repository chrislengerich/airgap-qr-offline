#!/usr/bin/env python3
"""Build the fully-offline (single-file) versions of the QR transfer site.

Every dependency (pako, qrcodejs, jsQR) is inlined into a single HTML file so
the resulting pages have no external references and work from file://. The
pages register a service worker (sw.js) so that once opened over http(s) they
are precached and work offline.

The inlined libraries are pinned and vendored in offline/vendor/.

Usage:
  python3 build_offline.py          # build from vendored libraries
  python3 build_offline.py --fetch  # (re)download the pinned libraries first
"""

import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
TEMPLATES = HERE / "templates"

LIBS = {
    "pako.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pako/2.0.3/pako.min.js",
    "qrcode.min.js": "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js",
    "jsQR.js": "https://unpkg.com/jsqr@1.4.0/dist/jsQR.js",
}

JOBS = [
    ("generator.tpl.html", "generator.html", {"__PAKO__": "pako.min.js",
                                              "__QRCODE__": "qrcode.min.js"}),
    ("scanner.tpl.html", "scanner.html", {"__PAKO__": "pako.min.js",
                                          "__JSQR__": "jsQR.js"}),
]


def fetch(url, dest):
    if dest.exists():
        print("using cached", dest.name)
        return
    print("downloading", url)
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())


def main():
    if "--fetch" in sys.argv:
        VENDOR.mkdir(exist_ok=True)
        for name, url in LIBS.items():
            fetch(url, VENDOR / name)

    for template, output, markers in JOBS:
        tpl = (TEMPLATES / template).read_text()
        for marker, lib in markers.items():
            content = (VENDOR / lib).read_text()
            tpl = tpl.replace(marker, content.replace("</script", "<\\/script"))
        out = HERE / output
        out.write_text(tpl)
        print("wrote %s (%d bytes)" % (output, out.stat().st_size))


if __name__ == "__main__":
    main()
