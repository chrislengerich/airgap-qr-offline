// Tests for the static file server (server.js). The path contract is that only
// files under offline/ are served: traversal (raw or percent-encoded) and
// sibling directories whose name shares the root's prefix must all be refused.

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

process.env.PORT = String(20000 + crypto.randomInt(30000));
const server = (await import("../server.js")).default;

// http.request with an options object sends `path` verbatim (a URL string would
// normalize "/../" before the server ever sees it).
const get = (rawPath, headers = {}) =>
  new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port: process.env.PORT, path: rawPath, headers },
      (res) => {
        res.resume();
        res.on("end", () => resolve(res.statusCode));
      }
    );
    req.on("error", reject);
    req.end();
  });

const getHeaders = (rawPath, headers = {}) =>
  new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port: process.env.PORT, path: rawPath, headers },
      (res) => {
        res.resume();
        res.on("end", () => resolve(res.headers));
      }
    );
    req.on("error", reject);
    req.end();
  });

describe("server.js static file handling", () => {
  let sibling;

  before(async () => {
    // A sibling of offline/ whose name shares the root's prefix — exactly the
    // case a bare startsWith(ROOT) check would wrongly serve.
    sibling = fs.mkdtempSync(path.join(ROOT, "offline-traversal-check-"));
    fs.writeFileSync(path.join(sibling, "secret.txt"), "top secret");
    for (let i = 0; ; i++) {
      try {
        await get("/");
        break;
      } catch (e) {
        if (i > 50) throw e;
        await new Promise((r) => setTimeout(r, 50));
      }
    }
  });

  after(() => {
    fs.rmSync(sibling, { recursive: true, force: true });
    server.close();
  });

  it("serves files under offline/", async () => {
    assert.equal(await get("/index.html"), 200);
  });

  it("404s missing files inside offline/", async () => {
    assert.equal(await get("/nope.txt"), 404);
  });

  it("refuses traversal above offline/, raw and percent-encoded", async () => {
    assert.equal(await get("/../server.js"), 403);
    assert.equal(await get("/..%2fserver.js"), 403);
    assert.equal(await get("/%2e%2e/server.js"), 403);
  });

  it("refuses sibling directories sharing the root's name prefix", async () => {
    assert.equal(await get("/../" + path.basename(sibling) + "/secret.txt"), 403);
  });

  it("redirects plain http when behind a reverse proxy", async () => {
    assert.equal(await get("/", { "X-Forwarded-Proto": "http" }), 301);
  });

  it("sends HSTS on https requests", async () => {
    const headers = await getHeaders("/index.html", { "X-Forwarded-Proto": "https" });
    assert.equal(headers["strict-transport-security"], "max-age=31536000; includeSubDomains");
  });

  it("does not send HSTS over plain http (RFC 6797)", async () => {
    const headers = await getHeaders("/index.html");
    assert.equal(headers["strict-transport-security"], undefined);
  });
});
