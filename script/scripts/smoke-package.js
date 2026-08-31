#!/usr/bin/env node

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const packageJson = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
const archiveName = `${packageJson.name.replace(/^@/, "").replace("/", "-")}-${packageJson.version}.tgz`;
const sandbox = mkdtempSync(join(tmpdir(), "cannbot-package-smoke-"));

function run(command, args, cwd, env = process.env) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8" });
  if (result.error || result.status !== 0) {
    const detail = result.error?.message || result.stderr || result.stdout;
    throw new Error(`${command} ${args.join(" ")} failed: ${detail}`);
  }
  return result;
}

try {
  const consumer = join(sandbox, "consumer");
  const target = join(sandbox, "target");
  mkdirSync(consumer, { recursive: true });
  mkdirSync(target, { recursive: true });
  writeFileSync(join(consumer, "package.json"), '{"name":"cannbot-package-smoke","private":true}\n');

  run("npm", ["pack", "--pack-destination", sandbox], packageRoot);
  const archive = join(sandbox, archiveName);
  if (!existsSync(archive)) throw new Error(`npm archive was not created: ${archive}`);
  run("npm", ["install", "--ignore-scripts", "--no-audit", "--no-fund", archive], consumer);

  const executable = join(consumer, "node_modules", ".bin", process.platform === "win32" ? "cannbot.cmd" : "cannbot");
  run(executable, ["install", "ascendc-st-design", "--tool", "dsh", "--target", target], consumer, {
    ...process.env,
    HOME: join(sandbox, "home"),
    XDG_CACHE_HOME: join(sandbox, "cache"),
    CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
  });

  for (const path of [
    join(target, ".dsh", "skills", "ascendc-st-design", "SKILL.md"),
    join(target, ".cannbot", "plugins", "ascendc-st-design", "LICENSE"),
    join(target, ".cannbot", "plugins", "ascendc-st-design", "SKILLS_LICENSE"),
  ]) {
    if (!existsSync(path)) throw new Error(`packaged install is missing: ${path}`);
  }
  console.log(`Verified ${archiveName} through the installed cannbot npm bin.`);
} finally {
  rmSync(sandbox, { recursive: true, force: true });
}
