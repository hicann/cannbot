#!/usr/bin/env node

import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { assemblePlugins } from "../lib/plugin-bundle.js";

const repositoryRoot = fileURLToPath(new URL("../../", import.meta.url));
const outputRoot = resolve(process.argv[2] ?? new URL("../dist", import.meta.url).pathname);
rmSync(outputRoot, { recursive: true, force: true });
const assembled = assemblePlugins(repositoryRoot, outputRoot);
for (const plugin of assembled) {
  console.error(`assembled ${plugin.pluginId}: ${plugin.skills} Skills`);
}
