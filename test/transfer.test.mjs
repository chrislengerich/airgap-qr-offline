// End-to-end and adversarial tests for the QR file transfer protocol.
//
// The generator page (offline/generator.html) is driven through DOM stubs:
// pasting text / picking a file and clicking Start, then reading the QR
// payloads it renders. Those payloads (or hand-crafted malicious ones) are
// fed to the scanner page (offline/scanner.html) through a stubbed jsQR,
// simulating camera frames, and the resulting download is inspected.

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { randomBytes } from "node:crypto";

import { loadGenerator, loadScanner, encodeChunk, senderFrames } from "./helpers.mjs";

const MAX_CHUNKS = 200000; // mirrors scanner MAX_CHUNKS
const MAX_SIZE = 64 * 1024 * 1024; // mirrors scanner MAX_SIZE

// Drive a generator page to completion and return the rendered QR frames.
async function framesForText(page, text) {
  page.el("speed").value = "250";
  page.el("text_input").value = text;
  page.click("btn_start");
  const meta = JSON.parse(page.frames[0]);
  page.pumpTimers(meta.chunks); // render the remaining chunk frames
  return page.frames;
}

async function framesForFile(page, name, bytes) {
  page.el("speed").value = "250";
  page.el("file_input").files = [
    { name, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) },
  ];
  page.click("btn_start");
  await new Promise((r) => setImmediate(r)); // let arrayBuffer() resolve
  const meta = JSON.parse(page.frames[0]);
  page.pumpTimers(meta.chunks);
  return page.frames;
}

// Feed frames to a started scanner and return what it downloaded.
async function receive(page, frames) {
  await page.startReceiver();
  page.feed(...frames);
  page.pumpFrames(frames.length + 1);
  return page.downloads;
}

describe("generator", () => {
  it("emits a JSON metadata frame plus index,base64 chunk frames", async () => {
    const text = "hello transfer " + randomBytes(512).toString("hex");
    const page = loadGenerator();
    const frames = await framesForText(page, text);
    const meta = JSON.parse(frames[0]);
    assert.equal(frames.length, meta.chunks + 1);
    assert.equal(typeof meta.name, "string");
    assert.ok(Number.isInteger(meta.chunks) && meta.chunks >= 2);
    assert.equal(meta.size, new TextEncoder().encode(text).length);
    for (const f of frames.slice(1)) {
      assert.match(f, /^\d+,([A-Za-z0-9+/]+=*)$/);
    }
  });

  it("names pastes 'Paste @ <timestamp>'", async () => {
    const page = loadGenerator();
    const frames = await framesForText(page, "hi");
    assert.match(JSON.parse(frames[0]).name, /^Paste @ \d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$/);
  });

  it("prefers pasted text over a selected file", async () => {
    const page = loadGenerator();
    page.el("speed").value = "250";
    page.el("text_input").value = "pasted text";
    page.el("file_input").files = [
      { name: "ignored.bin", arrayBuffer: async () => new ArrayBuffer(4) },
    ];
    page.click("btn_start");
    assert.match(JSON.parse(page.frames[0]).name, /^Paste @ /);
  });

  it("does nothing without input", () => {
    const page = loadGenerator();
    page.click("btn_start");
    assert.equal(page.frames.length, 0);
    assert.equal(page.message, "Choose a file or paste text to get started");
  });

  it("rejects pasted text with invalid UTF-16", () => {
    const page = loadGenerator();
    page.el("text_input").value = "ends with lone high surrogate \uD800";
    page.click("btn_start");
    assert.equal(page.frames.length, 0);
    assert.equal(page.message, "Text contains an unpaired surrogate");

    page.el("text_input").value = "high surrogate before \uD800 a space";
    page.click("btn_start");
    assert.equal(page.frames.length, 0);
    assert.equal(page.message, "Text contains invalid Unicode characters");

    page.el("text_input").value = "lone low surrogate \uDC00";
    page.click("btn_start");
    assert.equal(page.frames.length, 0);
    assert.equal(page.message, "Text contains invalid Unicode characters");
  });

  it("rejects oversized pasted text", () => {
    const page = loadGenerator();
    page.el("text_input").value = "a".repeat(1000001);
    page.click("btn_start");
    assert.equal(page.frames.length, 0);
    assert.match(page.message, /^Text too long/);
  });

  it("strips path components from the sent filename", async () => {
    const page = loadGenerator();
    const frames = await framesForFile(page, "../../pwned.txt", new Uint8Array([1, 2, 3]));
    assert.equal(JSON.parse(frames[0]).name, "pwned.txt");
  });
});

describe("paste and file round-trips (generator -> scanner)", () => {
  it("round-trips a pasted text containing unicode", async () => {
    const text =
      "héllo wörld 🌍 — 中文\nline2\twith \"quotes\" 'and' apostrophes\n" + "y".repeat(600);
    const page = loadGenerator();
    const frames = await framesForText(page, text);
    const dl = await receive(loadScanner(), frames);
    assert.equal(dl.length, 1);
    assert.match(dl[0].name, /^Paste @ \d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$/);
    assert.equal(new TextDecoder().decode(dl[0].data), text);
  });

  it("round-trips a multi-chunk binary file byte-for-byte", async () => {
    const bytes = randomBytes(2048); // incompressible -> several 250-byte chunks
    const gen = loadGenerator();
    const frames = await framesForFile(gen, "report.bin", bytes);
    const meta = JSON.parse(frames[0]);
    assert.ok(meta.chunks >= 2);
    const scanner = loadScanner();
    const dl = await receive(scanner, frames);
    assert.equal(dl.length, 1);
    assert.equal(dl[0].name, "report.bin");
    assert.ok(Buffer.from(dl[0].data).equals(Buffer.from(bytes)));
    assert.equal(scanner.message, "Data Transfer Complete");
  });
});

describe("scanner robustness against malicious QR codes", () => {
  const startScanner = async () => {
    const page = loadScanner();
    await page.startReceiver();
    return page;
  };

  it("ignores malformed metadata JSON", async () => {
    const page = await startScanner();
    page.feed("{oops", '{"name"');
    page.pumpFrames(2);
    assert.equal(page.progress, "Progress: 0 / 0");
    assert.equal(page.downloads.length, 0);
  });

  it("rejects metadata with invalid fields", async () => {
    const badMetas = [
      '{"name":"a","chunks":0}',
      '{"name":"a","chunks":1.5}',
      `{"name":"a","chunks":${MAX_CHUNKS + 1}}`,
      '{"name":"a","chunks":1,"size":-1}',
      `{"name":"a","chunks":1,"size":${MAX_SIZE + 1}}`,
      "[1,2]",
      '{"chunks":1,"size":0}',
      `{"name":"${"x".repeat(5001)}","chunks":1}`,
    ];
    const page = await startScanner();
    for (const m of badMetas) {
      page.feed(m);
      page.pumpFrames(1);
      assert.equal(page.progress, "Progress: 0 / 0", "rejected: " + m);
    }
    assert.equal(page.downloads.length, 0);
  });

  it("does not pollute Object.prototype via __proto__ in metadata", async () => {
    const page = await startScanner();
    page.feed('{"__proto__":{"polluted":1},"name":"x.bin","chunks":1,"size":0}');
    page.pumpFrames(1);
    assert.equal({}.polluted, undefined);
    assert.equal(page.progress, "Progress: 0 / 1");
  });

  it("rejects out-of-range and malformed chunk indices", async () => {
    const page = await startScanner();
    page.feed('{"name":"a.bin","chunks":1,"size":0}');
    page.pumpFrames(1);
    const junk = ["-1," + btoa("junk"), "1," + btoa("junk"), "999999999," + btoa("junk"),
                  "abc," + btoa("junk"), "," + btoa("junk"), "0nope", "0,,extra", "0,!!!not-base64!!!"];
    for (const j of junk) {
      page.feed(j);
      page.pumpFrames(1);
    }
    assert.equal(page.progress, "Progress: 0 / 1");
    assert.equal(page.downloads.length, 0);
    // a legitimate chunk still completes the transfer afterwards
    page.feed(encodeChunk(0, gzipSync(new Uint8Array(0))));
    page.pumpFrames(1);
    assert.equal(page.downloads.length, 1);
    assert.equal(page.downloads[0].data.length, 0);
  });

  it("fails loudly on declared-size mismatch and downloads nothing", async () => {
    const page = await startScanner();
    page.feed('{"name":"x.bin","chunks":1,"size":9999}');
    page.feed(encodeChunk(0, gzipSync(new TextEncoder().encode("hello")))); // inflates to 5 bytes
    page.pumpFrames(2);
    assert.equal(page.downloads.length, 0);
    assert.match(page.message, /^Transfer failed: size mismatch/);
  });

  it("fails loudly on non-gzip payload and downloads nothing", async () => {
    const page = await startScanner();
    page.feed('{"name":"x.bin","chunks":1,"size":3}');
    page.feed(encodeChunk(0, new TextEncoder().encode("abc"))); // raw bytes, not gzip
    page.pumpFrames(2);
    assert.equal(page.downloads.length, 0);
    assert.match(page.message, /^Transfer failed/);
  });

  it("resets collected chunks when new metadata arrives", async () => {
    const page = await startScanner();
    const frames = senderFrames("a.txt", randomBytes(900), { gzipSync }); // multi-chunk
    page.feed(frames[0], frames[1]); // meta A + chunk 0
    page.pumpFrames(2);
    assert.equal(page.progress, "Progress: 1 / " + (frames.length - 1));
    page.feed('{"name":"b.txt","chunks":1,"size":0}'); // a second sender's meta
    page.pumpFrames(1);
    assert.equal(page.progress, "Progress: 0 / 1");
    assert.equal(page.downloads.length, 0);
  });

  it("keeps progress when the same metadata is re-scanned", async () => {
    const page = await startScanner();
    const frames = senderFrames("a.txt", randomBytes(900), { gzipSync }); // multi-chunk
    page.feed(frames[0], frames[1], frames[0]); // meta, chunk 0, meta again
    page.pumpFrames(3);
    assert.equal(page.progress, "Progress: 1 / " + (frames.length - 1));
    assert.equal(page.downloads.length, 0);
  });

  it("never completes while chunks are missing", async () => {
    const page = await startScanner();
    const frames = senderFrames("a.txt", randomBytes(900), { gzipSync });
    page.feed(frames[0], frames[1]); // 1 of >=4 chunks
    page.pumpFrames(10);
    assert.equal(page.downloads.length, 0);
    assert.equal(page.progress, "Progress: 1 / " + (frames.length - 1));
  });

  it("downloads under a sanitized filename regardless of the claimed name", async () => {
    const cases = [
      ["../../../etc/passwd", "passwd"],
      ["..\\..\\evil.exe", "evil.exe"],
      [".", "received_file.bin"],
      ["..", "received_file.bin"],
      ["", "received_file.bin"],
      ["bad\nname\x00.txt", "badname.txt"],
      ["A".repeat(500), "A".repeat(200)],
    ];
    for (const [evil, expected] of cases) {
      const page = await startScanner();
      page.feed(...senderFrames(evil, new Uint8Array([7, 7]), { gzipSync }));
      page.pumpFrames(4);
      assert.equal(page.downloads.length, 1, "case: " + JSON.stringify(evil));
      assert.equal(page.downloads[0].name, expected);
      assert.ok(!/[\\/]/.test(page.downloads[0].name));
      assert.ok(!/[\u0000-\u001f\u007f]/.test(page.downloads[0].name));
    }
  });

  it("discards chunks scanned before the first valid metadata", async () => {
    const page = await startScanner();
    const frames = senderFrames("a.txt", new TextEncoder().encode("aaa"), { gzipSync });
    page.feed(frames[1], frames[0]); // chunk first, then meta
    page.pumpFrames(2);
    assert.equal(page.progress, "Progress: 0 / 1"); // pre-meta chunks were wiped
    assert.equal(page.downloads.length, 0);
    // scanning the chunks again after the metadata completes the transfer
    page.feed(...frames.slice(1));
    page.pumpFrames(frames.length);
    assert.equal(page.downloads.length, 1);
    assert.equal(new TextDecoder().decode(page.downloads[0].data), "aaa");
  });
});
