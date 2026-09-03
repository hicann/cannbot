# CANNBot managed plugins

This directory contains the official CANNBot plugin definitions and non-Skill files:

- `ops-direct-invoke`
- `ascendc-st-design`
- `model-infer-optimize`

Each plugin declares the Skills it needs in `plugin-sources.json`. The actual Skill source is maintained in the `vendor/cannbot-skills` submodule and is not duplicated in this repository.

Each plugin's `init.sh` creates project Skill symlinks to the submodule. `npm --prefix script run build:plugins` instead copies the declared Skills into `script/dist/plugins/<plugin>/skills/` for a self-contained npm package.

Each `init.sh` is a thin source adapter for the shared Node installer. Optional dependency repositories are declared in `plugin-install.json`.
