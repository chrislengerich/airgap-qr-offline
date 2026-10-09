# OSS Scanner build for airgap-qr-offline (https://github.com/chrislengerich/airgap-qr-offline).
# Network is available during this build only; the audit afterwards runs offline.
# The project is zero-dependency by design: server.js and the tests use only Node
# built-ins, and the browser libraries are pinned and vendored in offline/vendor/,
# so the only tooling to fetch here is the Node.js and Python runtimes themselves.
FROM debian:bookworm
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git nodejs npm python3 \
    && rm -rf /var/lib/apt/lists/*

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Rebuild the single-file offline pages (generator.html, scanner.html) from the
# templates and the pinned, vendored libraries. No --fetch: nothing needs the network.
RUN python3 offline/build_offline.py

# Run the project's test suite (Node's built-in test runner; test/helpers.mjs
# drives the real built pages in a vm sandbox with DOM/camera stubs). Per the
# oss-scanner template, a failing test logs a warning instead of aborting the
# build, so the checkout is still in place for the audit either way.
RUN npm test || echo "WARNING: npm test reported failures"
