# CANNBot managed plugins

This directory contains the self-contained plugins in the official CANNBot catalog:

- `ops-direct-invoke`
- `ascendc-st-design`
- `model-infer-optimize`

Each plugin declares the Skills it needs in `plugin-sources.json`. The actual Skill source is maintained in the `vendor/cannbot-skills` submodule and is not duplicated in this repository.

`npm --prefix script run build:plugins` copies the declared Skills into `script/dist/plugins/<plugin-id>/skills/`. Every direct child in that generated directory is a discoverable Skill, keeping the published layout valid for Codex, Claude Code, OpenCode, TRAE, and DSH.

The submodule is currently pinned to `cann/cannbot-skills` commit `38728be73688df97a84d9570a24dae616ea4542e`. To consume an update, move the submodule commit, verify each plugin mapping, run `npm --prefix script test`, and bump the npm package version so users receive a new immutable cache directory.

Each plugin includes a thin `init.sh` source adapter. It delegates to the same Node installer used by the published npm package; installation behavior is not implemented in the plugin scripts. Optional dependency repositories are declared in `plugin-install.json`.
