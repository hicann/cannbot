# CANNBot npm installer

This directory is the complete npm project for `@cannbot-plugin/cannbot`.

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool opencode
npx @cannbot-plugin/cannbot install ascendc-st-design --tool codex
```

The package build reads plugin definitions from `../plugins/` and Skill sources from the `../vendor/cannbot-skills` submodule. `prepack` assembles the selected source trees into `dist/plugins/`, so npm users receive a self-contained package and never clone the source repository.

```bash
npm test
npm run build:plugins
npm pack --dry-run
npm run pack:smoke
npm publish --access public
```

`npm publish` runs the full test suite and installs the generated tarball through
its `cannbot` npm bin before publishing. Version `1.3.2` was released on 2026-08-31.

The npm package is a mixed-license distribution. The installer implementation
is MIT licensed. Assembled official plugins and bundled Skills retain the CANN
Open Software License Agreement Version 2.0 and any license notices included
with their content; see the package `LICENSE` overview and the license files in
each `dist/plugins/<plugin>/` directory.

All clients use the same Node installer. Each source `init.sh` forwards the selected plugin, source repository, tool, and target to the CLI, which links Skills to the submodule. npm installation copies the bundled Skills. Plugin-specific dependency repositories are declared in `plugin-install.json`.

See [the workflow installation and usage guide](docs/cannbot-workflows.md) for all supported commands and prompt examples.
