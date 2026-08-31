import assert from "node:assert/strict";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const packageRoot = resolve(import.meta.dirname, "..");
const repositoryRoot = resolve(packageRoot, "..");
const cli = join(packageRoot, "bin", "cannbot.js");
const installerPackage = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
const sourcePackage = `${installerPackage.name}@${installerPackage.version}`;
const tools = ["opencode", "codex", "claude", "trae", "dsh"];
const sources = ["repository", "package"];
process.env.CANNBOT_SKIP_DEPENDENCY_REPOS = "1";
const temporarySandboxes = new Set();

test.afterEach(() => {
  for (const sandbox of temporarySandboxes) {
    rmSync(sandbox, { recursive: true, force: true });
  }
  temporarySandboxes.clear();
});

function createSandbox(prefix) {
  const sandbox = mkdtempSync(join(tmpdir(), prefix));
  temporarySandboxes.add(sandbox);
  return sandbox;
}

function configRoot(target, tool) {
  return join(target, tool === "opencode" ? ".opencode" : `.${tool}`);
}

function skillRoot(target, tool) {
  return tool === "codex" ? join(target, ".agents", "skills") : join(configRoot(target, tool), "skills");
}

function installPlugin(plugin, tool, source = "repository") {
  const sandbox = createSandbox(`cannbot-${source}-${plugin}-${tool}-`);
  const target = join(sandbox, "project");
  mkdirSync(target);
  const args = [
    cli,
    "install",
    plugin,
    "--tool",
    tool,
    "--target",
    target,
  ];
  if (source === "repository") args.push("--source", repositoryRoot);
  const result = spawnSync(process.execPath, args, {
    cwd: target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(sandbox, "home"),
      XDG_CACHE_HOME: join(sandbox, "cache"),
      CANNBOT_SKIP_CODEX_PLUGIN_ADD: "1",
      CANNBOT_SKIP_OPENCODE_PLUGIN_ADD: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return { sandbox, target, result };
}

function installWithSourceInit(plugin, tool) {
  const sandbox = createSandbox(`cannbot-init-${plugin}-${tool}-`);
  const target = join(sandbox, "project");
  mkdirSync(target);
  const init = join(repositoryRoot, "plugins", plugin, "init.sh");
  const result = spawnSync("bash", [init, "project", tool, target], {
    cwd: join(repositoryRoot, "plugins", plugin),
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(sandbox, "home"),
      XDG_CACHE_HOME: join(sandbox, "cache"),
      CANNBOT_SKIP_CODEX_PLUGIN_ADD: "1",
      CANNBOT_SKIP_OPENCODE_PLUGIN_ADD: "1",
      CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return { sandbox, target, result };
}

function readPluginRecord(target, tool, plugin) {
  const registry = JSON.parse(readFileSync(join(configRoot(target, tool), "cannbot-plugin.json"), "utf8"));
  assert.equal(registry.schemaVersion, 2);
  assert.equal(Array.isArray(registry.plugins), true);
  const record = registry.plugins.find((candidate) => candidate.plugin === plugin);
  assert.ok(record, `missing install record for ${plugin}`);
  return record;
}

function assertUnifiedInstall(target, tool, plugin) {
  const root = configRoot(target, tool);
  assert.equal(existsSync(join(root, "cannbot-manifest.json")), false);
  const instructionsPath = join(target, tool === "claude" ? "CLAUDE.md" : "AGENTS.md");
  if (existsSync(instructionsPath)) {
    const instructions = readFileSync(instructionsPath, "utf8");
    assert.equal(instructions.match(new RegExp(`<!-- cannbot:${plugin}:start -->`, "g"))?.length, 1);
  }
}

test("repository maps every official plugin to the Skill submodule", () => {
  for (const plugin of ["ops-direct-invoke", "ascendc-st-design", "model-infer-optimize"]) {
    const root = join(repositoryRoot, "plugins", plugin);
    assert.equal(existsSync(join(root, ".claude-plugin", "plugin.json")), true);
    assert.equal(existsSync(join(root, ".codex-plugin", "plugin.json")), true);
    assert.equal(existsSync(join(root, "plugin-sources.json")), true);
    assert.equal(existsSync(join(root, "skills")), false);
  }
  assert.equal(existsSync(join(repositoryRoot, "vendor", "cannbot-skills", ".git")), true);
  for (const removed of ["catalog", "plugins-official", "ops", "infra", "model"]) {
    assert.equal(existsSync(join(repositoryRoot, removed)), false, `${removed} should not exist at repository root`);
  }
});

test("Claude marketplace matches the official plugin manifests", () => {
  const marketplace = JSON.parse(readFileSync(join(repositoryRoot, ".claude-plugin", "marketplace.json"), "utf8"));
  const entries = new Map(marketplace.plugins.map((plugin) => [plugin.name, plugin]));
  const gitlink = spawnSync("git", ["ls-tree", "HEAD", "vendor/cannbot-skills"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  });
  assert.equal(gitlink.status, 0, gitlink.stderr);
  const skillCommit = gitlink.stdout.trim().split(/\s+/)[2];
  const expectedPlugins = ["ascendc-st-design", "model-infer-optimize", "ops-direct-invoke"];
  const officialPlugins = marketplace.plugins.filter((plugin) => typeof plugin.source === "string");
  assert.deepEqual(officialPlugins.map((plugin) => plugin.name).sort(), expectedPlugins);
  assert.equal(marketplace.owner.url, "https://gitcode.com/cann/cannbot");
  for (const plugin of officialPlugins) {
    assert.equal(plugin.source, `./plugins/${plugin.name}`);
    const manifest = JSON.parse(readFileSync(
      join(repositoryRoot, "plugins", plugin.name, ".claude-plugin", "plugin.json"),
      "utf8",
    ));
    assert.equal(plugin.version, manifest.version);
    assert.equal(plugin.description, manifest.description);
    assert.deepEqual(plugin.dependencies, manifest.dependencies);
    assert.equal(manifest.skills, undefined);

    const sourceDefinition = JSON.parse(readFileSync(
      join(repositoryRoot, "plugins", plugin.name, "plugin-sources.json"),
      "utf8",
    ));
    const marketplaceSkills = manifest.dependencies.flatMap((dependency) => {
      const entry = entries.get(dependency);
      assert.equal(entry.category, "skills");
      assert.equal(entry.strict, false);
      assert.equal(entry.source.source, "git-subdir");
      assert.equal(entry.source.url, "https://gitcode.com/cann/cannbot-skills.git");
      assert.equal(entry.source.sha, skillCommit);
      return entry.skills.map((skill) => `${entry.source.path}/${skill.replace(/^\.\//, "")}`);
    });
    assert.deepEqual(marketplaceSkills.sort(), sourceDefinition.skills.sort());

    const bundledManifest = JSON.parse(readFileSync(
      join(packageRoot, "dist", "plugins", plugin.name, ".claude-plugin", "plugin.json"),
      "utf8",
    ));
    assert.equal(bundledManifest.dependencies, undefined);
    assert.deepEqual(
      bundledManifest.skills.map((skill) => skill.replace(/^\.\/skills\//, "")).sort(),
      sourceDefinition.skills.map((skill) => skill.split("/").at(-1)).sort(),
    );
  }
});

test("package bundle includes the official plugin license", () => {
  assert.equal(
    readFileSync(join(packageRoot, "dist", "plugins", "LICENSE"), "utf8"),
    readFileSync(join(repositoryRoot, "plugins", "LICENSE"), "utf8"),
  );
  for (const plugin of ["ascendc-st-design", "model-infer-optimize", "ops-direct-invoke"]) {
    assert.equal(
      readFileSync(join(packageRoot, "dist", "plugins", plugin, "LICENSE"), "utf8"),
      readFileSync(join(repositoryRoot, "plugins", "LICENSE"), "utf8"),
    );
    assert.equal(
      readFileSync(join(packageRoot, "dist", "plugins", plugin, "SKILLS_LICENSE"), "utf8"),
      readFileSync(join(repositoryRoot, "vendor", "cannbot-skills", "LICENSE"), "utf8"),
    );
  }
});

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs self-contained ascendc-st-design for ${tool}`, () => {
      const { target } = installPlugin("ascendc-st-design", tool, source);
      const installedSkill = join(skillRoot(target, tool), "ascendc-st-design");
      assert.equal(existsSync(join(installedSkill, "SKILL.md")), true);
      assert.equal(lstatSync(installedSkill).isSymbolicLink(), false);
      const record = readPluginRecord(target, tool, "ascendc-st-design");
      assert.equal(record.sourcePackage, sourcePackage);
      assert.equal(record.source.kind, source);
      assert.equal(existsSync(join(target, ".cannbot", "plugins", "ascendc-st-design", "LICENSE")), true);
      assert.equal(existsSync(join(target, ".cannbot", "plugins", "ascendc-st-design", "SKILLS_LICENSE")), true);
    });
  }
}

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs self-contained ops-direct-invoke for ${tool}`, () => {
      const { sandbox, target } = installPlugin("ops-direct-invoke", tool, source);
      const root = configRoot(target, tool);
      const agent = tool === "codex" ? "ascendc-kernel-architect.toml" : "ascendc-kernel-architect.md";
      const workflow = join(target, ".cannbot", "plugins", "ops-direct-invoke", "workflows");
      const installedSkill = join(skillRoot(target, tool), "ascendc-env-check");
      assert.equal(existsSync(join(installedSkill, "SKILL.md")), true);
      assert.equal(lstatSync(installedSkill).isSymbolicLink(), false);
      assert.equal(existsSync(join(skillRoot(target, tool), "gitcode-toolkit", "SKILL.md")), true);
      assert.equal(existsSync(join(root, "agents", agent)), true);
      assert.equal(existsSync(join(workflow, "scripts", "validate_state.py")), true);
      const record = readPluginRecord(target, tool, "ops-direct-invoke");
      assert.equal(record.skills.length, 21);
      assert.equal(record.agents.length, 4);
      assert.equal(record.sourcePackage, sourcePackage);
      assert.equal(record.source.kind, source);
      assertUnifiedInstall(target, tool, "ops-direct-invoke");
      if (tool === "codex") {
        assert.equal(existsSync(join(sandbox, "home", "plugins", "ops-direct-invoke", ".codex-plugin", "plugin.json")), true);
      }
    });
  }
}

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs self-contained model-infer-optimize for ${tool}`, () => {
      const { target } = installPlugin("model-infer-optimize", tool, source);
      const root = configRoot(target, tool);
      const agent = tool === "codex" ? "model-infer-analyzer.toml" : "model-infer-analyzer.md";
      const workflow = join(target, ".cannbot", "plugins", "model-infer-optimize", "workflows");
      assert.equal(existsSync(join(skillRoot(target, tool), "model-infer-migrator", "SKILL.md")), true);
      assert.equal(existsSync(join(root, "agents", agent)), true);
      assert.equal(existsSync(join(workflow, "optimize-workflow.md")), true);
      const record = readPluginRecord(target, tool, "model-infer-optimize");
      assert.equal(record.skills.length, 14);
      assert.equal(record.agents.length, 9);
      assert.equal(record.sourcePackage, sourcePackage);
      assert.equal(record.source.kind, source);
      assertUnifiedInstall(target, tool, "model-infer-optimize");
      if (tool === "claude") {
        assert.equal(existsSync(join(root, "settings.json")), true);
        assert.equal(existsSync(join(target, ".cannbot", "plugins", "model-infer-optimize", "hooks", "pre_tool_use.py")), true);
      }
    });
  }
}

for (const plugin of ["ops-direct-invoke", "ascendc-st-design", "model-infer-optimize"]) {
  test(`${plugin} source init delegates to the unified installer`, () => {
    const { target } = installWithSourceInit(plugin, "opencode");
    assert.equal(existsSync(join(configRoot(target, "opencode"), "cannbot-plugin.json")), true);
    assertUnifiedInstall(target, "opencode", plugin);
  });
}

test("reinstall preserves user instructions and keeps one managed block", () => {
  const { sandbox, target } = installPlugin("ops-direct-invoke", "dsh", "package");
  const instructionsPath = join(target, "AGENTS.md");
  writeFileSync(instructionsPath, `user instructions\n\n${readFileSync(instructionsPath, "utf8")}`);
  const result = spawnSync(process.execPath, [
    cli,
    "install",
    "ops-direct-invoke",
    "--tool",
    "dsh",
    "--target",
    target,
  ], {
    cwd: target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(sandbox, "home"),
      XDG_CACHE_HOME: join(sandbox, "cache"),
      CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const instructions = readFileSync(instructionsPath, "utf8");
  assert.match(instructions, /^user instructions/m);
  assert.equal(instructions.match(/<!-- cannbot:ops-direct-invoke:start -->/g)?.length, 1);
});

test("multiple plugins keep independent instructions and install records", () => {
  const first = installPlugin("ops-direct-invoke", "dsh", "package");
  const result = spawnSync(process.execPath, [
    cli,
    "install",
    "model-infer-optimize",
    "--tool",
    "dsh",
    "--target",
    first.target,
  ], {
    cwd: first.target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(first.sandbox, "home"),
      XDG_CACHE_HOME: join(first.sandbox, "cache"),
      CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);

  const instructions = readFileSync(join(first.target, "AGENTS.md"), "utf8");
  assert.equal(instructions.match(/<!-- cannbot:ops-direct-invoke:start -->/g)?.length, 1);
  assert.equal(instructions.match(/<!-- cannbot:model-infer-optimize:start -->/g)?.length, 1);
  assert.match(instructions, /^# CANNBot$/m);
  assert.match(instructions, /^# NPU 模型推理优化入口$/m);

  const registry = JSON.parse(readFileSync(join(first.target, ".dsh", "cannbot-plugin.json"), "utf8"));
  assert.equal(registry.schemaVersion, 2);
  assert.deepEqual(registry.plugins.map((plugin) => plugin.plugin), ["model-infer-optimize", "ops-direct-invoke"]);
  assert.equal(existsSync(join(skillRoot(first.target, "dsh"), "ascendc-env-check", "SKILL.md")), true);
  assert.equal(existsSync(join(skillRoot(first.target, "dsh"), "model-infer-migrator", "SKILL.md")), true);
});

test("Claude hook installation is idempotent", () => {
  const first = installPlugin("model-infer-optimize", "claude", "package");
  const settingsPath = join(first.target, ".claude", "settings.json");
  const before = readFileSync(settingsPath, "utf8");
  const result = spawnSync(process.execPath, [
    cli,
    "install",
    "model-infer-optimize",
    "--tool",
    "claude",
    "--target",
    first.target,
  ], {
    cwd: first.target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(first.sandbox, "home"),
      XDG_CACHE_HOME: join(first.sandbox, "cache"),
      CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(readFileSync(settingsPath, "utf8"), before);
});

test("declarative dependencies use the same project-level install flow", () => {
  const sandbox = createSandbox("cannbot-dependency-");
  const dependencyRepository = join(sandbox, "dependency-repository");
  mkdirSync(dependencyRepository);
  const initialized = spawnSync("git", ["init", "--quiet", dependencyRepository], { encoding: "utf8" });
  assert.equal(initialized.status, 0, initialized.stderr || initialized.stdout);

  const plugin = "dependency-fixture";
  const pluginRoot = join(sandbox, "bundle", "plugins", plugin);
  mkdirSync(join(pluginRoot, ".claude-plugin"), { recursive: true });
  mkdirSync(join(pluginRoot, "skills", "fixture-skill"), { recursive: true });
  writeFileSync(join(pluginRoot, ".claude-plugin", "plugin.json"), JSON.stringify({
    name: plugin,
    version: "1.0.0",
    description: "Dependency fixture",
    skills: ["./skills/fixture-skill"],
  }));
  writeFileSync(join(pluginRoot, "skills", "fixture-skill", "SKILL.md"), [
    "---",
    "name: fixture-skill",
    "description: Test fixture",
    "---",
    "",
  ].join("\n"));
  writeFileSync(join(pluginRoot, "plugin-install.json"), JSON.stringify({
    dependencies: [{
      name: "fixture-dependency",
      repository: dependencyRepository,
      expose: "fixture-dependency",
    }],
  }));

  const target = join(sandbox, "project");
  mkdirSync(target);
  const result = spawnSync(process.execPath, [
    cli,
    "install",
    plugin,
    "--tool",
    "dsh",
    "--target",
    target,
    "--source",
    join(sandbox, "bundle"),
  ], {
    cwd: target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(sandbox, "home"),
      XDG_CACHE_HOME: join(sandbox, "cache"),
      CANNBOT_SKIP_DEPENDENCY_REPOS: "0",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const checkout = join(target, ".cannbot", "dependencies", plugin, "fixture-dependency");
  assert.equal(existsSync(join(checkout, ".git")), true);
  assert.equal(lstatSync(join(target, "fixture-dependency")).isSymbolicLink(), true);
  const record = readPluginRecord(target, "dsh", plugin);
  assert.deepEqual(record.dependencies, [join(".cannbot", "dependencies", plugin, "fixture-dependency")]);
});
