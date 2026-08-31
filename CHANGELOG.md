# Changelog

This file records notable changes to the CANNBot plugin orchestration and delivery repository.

## 1.3.2 - 2026-08-31

### Changed

- Switched plugin homepage URLs to the canonical production HTTPS endpoint.

## 1.3.1 - 2026-08-31

### Changed

- Aligned plugin homepage URLs with the production HTTP endpoint.
- Added the static CANNBot plugin portal and aligned its operator test page with `ascendc-st-design`.

## 1.3.0 - 2026-08-31

### Added

- Added repository-level CANN Open Software License 2.0 metadata and OAT compliance configuration.
- Added a Claude Code marketplace catalog for the three official plugins.
- Added Git text normalization and binary file rules.
- Added per-plugin license delivery and npm package installation smoke tests.
- Added the `ascendc-st-design` plugin for L0/L1/L2 system test design.

### Changed

- Standardized repository metadata on the official URL, `https://gitcode.com/cann/cannbot`.
- Unified npm and source installations behind the same Node.js installer.
- Added plugin-level `init.sh` adapters for source installations.
- Made source installation initialize the Skill submodule only when required.
- Renamed `npm/` to `script/` and `plugin-official/` to `plugins/`.
- Added the repository architecture, directory responsibilities, and release flow to the root README.
- Made plugin instructions and installation records coexist across multiple installed plugins.
- Renamed the internal CLI entry point to `cannbot.js`.

## 1.2.2 - 2026-08-21

### Changed

- Moved npm tooling into its own directory.
- Enabled shallow initialization of the Skill submodule.

## 1.2.1 - 2026-08-21

### Changed

- Established `cannbot-skills` as the single Skill source through a pinned Git submodule.
- Added build-time plugin assembly for npm packages.

## 1.2.0 - 2026-08-21

### Changed

- Made published official plugins self-contained so npm users do not clone the Skill repository.

## 1.1.0 - 2026-08-21

### Added

- Added packaged official plugins and native plugin initialization support.

## 1.0.0 - 2026-08-19

### Added

- Published the cross-client installer as `@cannbot-plugin/cannbot`.
