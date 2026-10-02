# Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch (`git checkout -b feature-branch`).
3. Make your changes.
4. Commit your changes (`git commit -am 'Add new feature'`).
5. Push to the branch (`git push origin feature-branch`).
6. Create a new Pull Request.

## Repo assumptions

This repository is deliberately kept small. All contributions must respect
these assumptions:

- **Minimal code.** Each page is a single self-contained HTML file with its
  dependencies vendored inline (`offline/build_offline.py`). Prefer the
  smallest change that fixes the problem, and avoid introducing frameworks,
  transpilers, package managers, or any other build tooling.
- **Minimal features.** Bugfixes are always welcome. Feature requests are
  considered only when they fit the assumptions above; when in doubt, open an
  issue describing the problem before writing code.
- **Broad platform compatibility.** Everything must work from the fully
  offline single-file pages on current versions of the major browsers
  (Firefox, Chrome/Chromium, Safari, including mobile), without external
  network requests byond the first request. The served site must stay
  zero-dependency and need no build step; the only Node code is the static
  file server (`server.js`).

## Tests

The transfer protocol has a zero-dependency test suite (Node's built-in test
runner, Node 18+). Run it with:

```sh
npm test
```

Please run the tests (and add tests for bugfixes) before submitting a change.
