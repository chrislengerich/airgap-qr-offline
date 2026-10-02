// Test harness: loads the built single-file pages (offline/*.html) into a
// `vm` sandbox with DOM/camera stubs so the inline app scripts can be driven
// without a browser. Uses only Node builtins to keep the repo zero-dependency.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// ---- fake timer / animation-frame queues (pumped manually by tests) ----

function makeQueue() {
  const q = new Map();
  let seq = 0;
  return {
    add(fn) {
      const id = ++seq;
      q.set(id, fn);
      return id;
    },
    del(id) {
      q.delete(id);
    },
    pump(n = 1) {
      for (let i = 0; i < n; i++) {
        const it = q.entries().next();
        if (it.done) return;
        const [id, fn] = it.value;
        q.delete(id);
        fn();
      }
    },
  };
}

// ---- DOM stubs ----

function makeEl(id, downloads) {
  const el = {
    id,
    textContent: "",
    value: "",
    disabled: false,
    files: [],
    videoWidth: 64,
    videoHeight: 64,
    srcObject: null,
    download: "",
    href: "",
    listeners: {},
    addEventListener(type, fn) {
      (this.listeners[type] ||= []).push(fn);
    },
    // canvas stub for the scanner's <canvas id="scan">
    getContext() {
      return {
        drawImage() {},
        getImageData: () => ({ data: new Uint8ClampedArray(64 * 64 * 4) }),
      };
    },
  };
  // <a> elements created by download_file(): clicking records the download
  el.click = () => {
    if (id === "a" || el.tagName === "a") {
      downloads.push({ name: el.download, data: FakeBlob.last?.parts?.[0] });
    }
  };
  return el;
}

class FakeBlob {
  constructor(parts) {
    this.parts = parts;
    FakeBlob.last = this;
  }
}
FakeBlob.last = null;

// ---- page loader ----

export function loadPage(file) {
  const html = readFileSync(path.join(ROOT, file), "utf8");
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(
    (m) => m[1]
  );

  const downloads = [];
  const els = new Map();
  const getElementById = (id) => {
    if (!els.has(id)) els.set(id, makeEl(id, downloads));
    return els.get(id);
  };

  const qrFrames = []; // texts passed to QRCode.makeCode()
  function QRCode(elId, opts) {
    this.elId = elId;
    this.opts = opts;
  }
  QRCode.CorrectLevel = { L: 1, M: 2, Q: 3, H: 4 };
  QRCode.prototype.clear = function () {};
  QRCode.prototype.makeCode = function (text) {
    qrFrames.push(text);
  };

  const timers = makeQueue(); // generator's setTimeout loop
  const raf = makeQueue(); // scanner's requestAnimationFrame loop
  const feed = []; // queued payloads returned by the jsQR stub

  const ctx = vm.createContext({
    document: {
      getElementById,
      createElement(tag) {
        const el = makeEl(tag, downloads);
        el.tagName = tag;
        return el;
      },
    },
    navigator: {
      mediaDevices: {
        getUserMedia: async () => ({ getTracks: () => [] }),
      },
    },
    window: { innerWidth: 1024, innerHeight: 768 },
    QRCode,
    jsQR: () => (feed.length ? { data: feed.shift() } : null),
    Blob: FakeBlob,
    URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
    TextEncoder,
    TextDecoder,
    atob,
    btoa,
    setTimeout: (fn) => timers.add(fn),
    clearTimeout: (id) => timers.del(id),
    requestAnimationFrame: (fn) => raf.add(fn),
    cancelAnimationFrame: (id) => raf.del(id),
    console,
  });

  // Evaluate every inline script except the vendored QR-code libraries
  // (qrcode.js and jsQR), which the stubs above replace.
  for (const code of scripts) {
    if (code.includes("var QRCode;") || code.includes("webpackUniversalModuleDefinition")) {
      continue;
    }
    vm.runInContext(code, ctx, { filename: file });
  }

  return {
    el: getElementById,
    click(id) {
      for (const fn of getElementById(id).listeners.click ?? []) fn({});
    },
    frames: qrFrames,
    downloads,
    feed: (...payloads) => feed.push(...payloads),
    pumpFrames: (n = 1) => raf.pump(n),
    pumpTimers: (n = 1) => timers.pump(n),
    get message() {
      return getElementById("user_message").textContent;
    },
    get progress() {
      return getElementById("progress").textContent;
    },
    // Click "Start Receiver" and let the fake getUserMedia promise settle.
    async startReceiver() {
      this.click("btn");
      await new Promise((r) => setImmediate(r));
    },
  };
}

export const loadGenerator = () => loadPage("offline/generator.html");
export const loadScanner = () => loadPage("offline/scanner.html");

// ---- helpers for crafting attacker-controlled QR payloads ----

// Mirror of the sender's chunk encoding: raw bytes are treated as latin-1
// characters, re-encoded as UTF-8, then base64'd:  "index,<base64>"
export function encodeChunk(index, bytes) {
  const latin1 = Array.from(bytes, (b) => String.fromCharCode(b)).join("");
  return index + "," + Buffer.from(latin1, "utf8").toString("base64");
}

// Build the frames an honest sender would emit for the given bytes/name,
// using real gzip so the payloads actually decompress.
export function senderFrames(name, bytes, { gzipSync }) {
  const gz = gzipSync(bytes);
  const meta = JSON.stringify({
    name,
    chunks: Math.max(1, Math.ceil(gz.length / 250)),
    size: bytes.length,
  });
  const chunks = [];
  for (let i = 0; i < Math.ceil(gz.length / 250); i++) {
    chunks.push(encodeChunk(i, gz.subarray(i * 250, (i + 1) * 250)));
  }
  return [meta, ...chunks];
}
