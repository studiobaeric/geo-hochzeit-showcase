# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and version numbers follow [Semantic Versioning](https://semver.org/) once
the first tagged release exists. See [RELEASING.md](RELEASING.md) for how
entries here turn into a tagged release with downloadable binaries.

## [Unreleased]

### Changed

- CI workflows now use `actions/checkout@v7`, `actions/setup-python@v7`,
  `actions/upload-artifact@v7`, `actions/download-artifact@v8`, and
  `softprops/action-gh-release@v3`, all of which run on Node.js 24 instead
  of the deprecated Node.js 20.
