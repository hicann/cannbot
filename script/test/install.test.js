// Copyright (c) 2026 CANNBot contributors
// SPDX-License-Identifier: MIT
// See script/LICENSE for the full license text.

import assert from "node:assert/strict";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { pluginSourceDefinition } from "../lib/plugin-bundle.js";

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

test("model-train-precision-diagnose resolves its community Skill sources", () => {
  const definition = pluginSourceDefinition(repositoryRoot, "model-train-precision-diagnose");
  assert.equal(
    definition.pluginRoot,
    join(repositoryRoot, "plugins-community", "model-train-precision-diagnose"),
  );
  assert.deepEqual(definition.skills, [
    "model/model-train-precision-numerical-mismatch",
    "model/model-train-precision-nonfinite",
    "model/model-train-precision-determinism",
    "model/model-train-log-visualization",
  ]);
});

function configRoot(target, tool) {
  return join(target, tool === "opencode" ? ".opencode" : `.${tool}`);
}

function skillRoot(target, tool) {
  return tool === "codex" || tool === "opencode"
    ? join(target, ".agents", "skills")
    : join(configRoot(target, tool), "skills");
}

function assertSkillInstallation(installedSkill, source, plugin, skill) {
  const shouldLink = source === "repository";
  assert.equal(lstatSync(installedSkill).isSymbolicLink(), shouldLink);
  if (!shouldLink) return;
  assert.equal(isAbsolute(readlinkSync(installedSkill)), false);
  const definition = pluginSourceDefinition(repositoryRoot, plugin);
  assert.ok(definition, `missing source definition for ${plugin}`);
  const relativeSkill = definition.skills.find((candidate) => candidate.split("/").at(-1) === skill);
  assert.ok(relativeSkill, `missing source mapping for ${plugin}/${skill}`);
  assert.equal(
    realpathSync(installedSkill),
    realpathSync(join(repositoryRoot, definition.skillsRepository, relativeSkill)),
  );
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
  const sourceDefinition = pluginSourceDefinition(repositoryRoot, plugin);
  const pluginRoot = sourceDefinition?.pluginRoot ?? join(repositoryRoot, "plugins-official", plugin);
  const init = join(pluginRoot, "init.sh");
  const result = spawnSync("bash", [init, "project", tool, target], {
    cwd: pluginRoot,
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
    const root = join(repositoryRoot, "plugins-official", plugin);
    assert.equal(existsSync(join(root, ".claude-plugin", "plugin.json")), true);
    assert.equal(existsSync(join(root, ".codex-plugin", "plugin.json")), true);
    assert.equal(existsSync(join(root, "plugin-sources.json")), true);
    if (plugin !== "ops-direct-invoke") {
      assert.equal(existsSync(join(root, "skills")), false);
    }
    const sourceDefinition = JSON.parse(readFileSync(join(root, "plugin-sources.json"), "utf8"));
    assert.equal(sourceDefinition.skillInstallMode, "symlink");
    const quickstartPath = join(root, "quickstart.md");
    if (existsSync(quickstartPath)) {
      const quickstart = readFileSync(quickstartPath, "utf8");
      assert.doesNotMatch(quickstart, /cann\.cannbot\.cn/);
      assert.doesNotMatch(quickstart, /默认安装到当前目录并使用 OpenCode/);
      assert.match(quickstart, /git clone --recurse-submodules/);
    }
    const codexManifest = JSON.parse(readFileSync(join(root, ".codex-plugin", "plugin.json"), "utf8"));
    assert.equal(codexManifest.homepage, "https://gitcode.com/cann/cannbot");
    assert.equal(codexManifest.repository, "https://gitcode.com/cann/cannbot");
    const trackedFiles = spawnSync("git", ["ls-files", "-s", `plugins-official/${plugin}`], {
      cwd: repositoryRoot,
      encoding: "utf8",
    });
    assert.equal(trackedFiles.status, 0, trackedFiles.stderr);
    assert.equal(trackedFiles.stdout.split("\n").some((line) => line.startsWith("120000 ")), false);
  }
  // ops-direct-invoke ships self-contained workflow skills in plugins-official/<id>/skills/;
  // the other two plugins resolve all skills from the submodule only.
  assert.equal(existsSync(join(repositoryRoot, "plugins-official", "ops-direct-invoke", "skills")), true);
  assert.equal(existsSync(join(repositoryRoot, "plugins-official", "ascendc-st-design", "skills")), false);
  assert.equal(existsSync(join(repositoryRoot, "plugins-official", "model-infer-optimize", "skills")), false);
  assert.equal(existsSync(join(repositoryRoot, "vendor", "cannbot-skills", ".git")), true);
  for (const removed of ["catalog", "ops", "infra", "model", "plugins"]) {
    assert.equal(existsSync(join(repositoryRoot, removed)), false, `${removed} should not exist at repository root`);
  }
});

test("Claude marketplace matches the bundled official plugin manifests", () => {
  const marketplace = JSON.parse(readFileSync(join(repositoryRoot, ".claude-plugin", "marketplace.json"), "utf8"));
  const entries = new Map(marketplace.plugins.map((plugin) => [plugin.name, plugin]));
  const gitlink = spawnSync("git", ["ls-tree", "HEAD", "vendor/cannbot-skills"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  });
  assert.equal(gitlink.status, 0, gitlink.stderr);
  const skillCommit = gitlink.stdout.trim().split(/\s+/)[2];
  const expectedPlugins = ["ascendc-st-design", "model-infer-optimize", "ops-direct-invoke"];
  // Only bundled plugins have manifests; source-only workflow entries are not packaged.
  const officialPlugins = marketplace.plugins.filter((plugin) =>
    typeof plugin.source === "string" && existsSync(join(packageRoot, "dist", "plugins", plugin.name)));
  for (const plugin of marketplace.plugins.filter((entry) => typeof entry.source === "string")) {
    assert.ok(existsSync(resolve(repositoryRoot, plugin.source)), plugin.source);
  }
  assert.deepEqual(officialPlugins.map((plugin) => plugin.name).sort(), expectedPlugins);
  assert.equal(entries.has("model-train-precision-diagnose"), false);
  assert.equal(marketplace.owner.url, "https://gitcode.com/cann/cannbot");
  for (const plugin of officialPlugins) {
    assert.equal(plugin.source, `./plugins-official/${plugin.name}`);
    const manifest = JSON.parse(readFileSync(
      join(repositoryRoot, "plugins-official", plugin.name, ".claude-plugin", "plugin.json"),
      "utf8",
    ));
    assert.equal(plugin.version, manifest.version);
    assert.equal(plugin.description, manifest.description);
    assert.deepEqual(plugin.dependencies, manifest.dependencies);
    assert.equal(manifest.homepage, "https://gitcode.com/cann/cannbot");
    assert.equal(manifest.repository, "https://gitcode.com/cann/cannbot");
    assert.equal(manifest.skills, undefined);

    const sourceDefinition = JSON.parse(readFileSync(
      join(repositoryRoot, "plugins-official", plugin.name, "plugin-sources.json"),
      "utf8",
    ));
    const marketplaceSkills = (manifest.dependencies ?? []).flatMap((dependency) => {
      const entry = entries.get(dependency);
      assert.equal(entry.category, "skills");
      assert.equal(entry.strict, false);
      assert.equal(entry.source.source, "git-subdir");
      assert.equal(entry.source.url, "https://gitcode.com/cann/cannbot-skills.git");
      assert.equal(entry.source.sha, skillCommit);
      return entry.skills.map((skill) => `${entry.source.path}/${skill.replace(/^\.\//, "")}`);
    });
    if (manifest.dependencies) {
      assert.deepEqual(marketplaceSkills.sort(), sourceDefinition.skills.sort());
    } else {
      assert.equal(sourceDefinition.skillsRepository, '.');
      for (const skill of sourceDefinition.skills) {
        assert.ok(existsSync(join(repositoryRoot, skill, 'SKILL.md')), skill);
      }
    }

    const bundledManifest = JSON.parse(readFileSync(
      join(packageRoot, "dist", "plugins", plugin.name, ".claude-plugin", "plugin.json"),
      "utf8",
    ));
    assert.equal(bundledManifest.dependencies, undefined);
    // The bundled manifest lists the union of submodule skills (plugin-sources.json)
    // and any self-contained skills shipped inside the plugin (plugins-official/<id>/skills/).
    const bundledSkills = bundledManifest.skills.map((skill) => skill.replace(/^\.\/skills\//, "")).sort();
    const submoduleSkills = sourceDefinition.skills.map((skill) => skill.split("/").at(-1)).sort();
    const selfContainedSkills = [];
    const selfContainedRoot = join(repositoryRoot, "plugins-official", plugin.name, "skills");
    if (existsSync(selfContainedRoot)) {
      for (const entry of readdirSync(selfContainedRoot)) {
        if (existsSync(join(selfContainedRoot, entry, "SKILL.md"))) selfContainedSkills.push(entry);
      }
    }
    assert.deepEqual(bundledSkills, [...submoduleSkills, ...selfContainedSkills].sort());
  }
});

test("package bundle includes plugin licenses", () => {
  assert.equal(
    readFileSync(join(packageRoot, "dist", "plugins", "LICENSE"), "utf8"),
    readFileSync(join(repositoryRoot, "plugins-official", "LICENSE"), "utf8"),
  );
  for (const plugin of ["ascendc-st-design", "model-infer-optimize", "ops-direct-invoke"]) {
    assert.equal(
      readFileSync(join(packageRoot, "dist", "plugins", plugin, "LICENSE"), "utf8"),
      readFileSync(join(repositoryRoot, "plugins-official", "LICENSE"), "utf8"),
    );
    const source = JSON.parse(readFileSync(
      join(repositoryRoot, "plugins-official", plugin, "plugin-sources.json"), "utf8"));
    assert.equal(
      readFileSync(join(packageRoot, "dist", "plugins", plugin, "SKILLS_LICENSE"), "utf8"),
      readFileSync(join(repositoryRoot, source.skillsRepository, "LICENSE"), "utf8"),
    );
  }
  assert.equal(
    readFileSync(join(packageRoot, "dist", "plugins", "model-train-precision-diagnose", "LICENSE"), "utf8"),
    readFileSync(join(repositoryRoot, "plugins-community", "model-train-precision-diagnose", "LICENSE"), "utf8"),
  );
  assert.equal(
    readFileSync(join(packageRoot, "dist", "plugins", "model-train-precision-diagnose", "SKILLS_LICENSE"), "utf8"),
    readFileSync(join(repositoryRoot, "vendor", "cannbot-skills", "LICENSE"), "utf8"),
  );
});

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs ascendc-st-design for ${tool}`, () => {
      const { target } = installPlugin("ascendc-st-design", tool, source);
      const installedSkill = join(skillRoot(target, tool), "ascendc-st-design");
      assert.equal(existsSync(join(installedSkill, "SKILL.md")), true);
      assertSkillInstallation(installedSkill, source, "ascendc-st-design", "ascendc-st-design");
      const record = readPluginRecord(target, tool, "ascendc-st-design");
      assert.equal(record.sourcePackage, sourcePackage);
      assert.equal(record.source.kind, source);
      assert.equal(record.skillInstallMode, source === "repository" ? "symlink" : "copy");
      assert.equal(existsSync(join(target, ".cannbot", "plugins", "ascendc-st-design", "LICENSE")), true);
      assert.equal(existsSync(join(target, ".cannbot", "plugins", "ascendc-st-design", "SKILLS_LICENSE")), true);
    });
  }
}

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs ops-direct-invoke for ${tool}`, () => {
      const { sandbox, target } = installPlugin("ops-direct-invoke", tool, source);
      const root = configRoot(target, tool);
      const agent = tool === "codex" ? "ops-direct-invoke-architect.toml" : "ops-direct-invoke-architect.md";
      const workflowScript = join(skillRoot(target, tool), "ops-direct-invoke", "scripts", "assemble_workflow.py");
      const installedSharedSkill = join(skillRoot(target, tool), "ascendc-env-check");
      assert.equal(existsSync(join(installedSharedSkill, "SKILL.md")), true);
      assertSkillInstallation(installedSharedSkill, source, "ops-direct-invoke", "ascendc-env-check");
      assert.equal(existsSync(join(skillRoot(target, tool), "workflow-orchestrator", "SKILL.md")), true);
      assert.equal(existsSync(join(skillRoot(target, tool), "ops-direct-invoke", "SKILL.md")), true);
      assert.equal(existsSync(join(root, "agents", agent)), true);
      assert.equal(existsSync(workflowScript), true);
      assert.equal(existsSync(join(target, ".cannbot", "permissions", "PM.js")), false);
      assert.equal(existsSync(join(target, ".cannbot", "settings.json")), false);
      const record = readPluginRecord(target, tool, "ops-direct-invoke");
      assert.equal(record.skills.length, 31);
      assert.equal(record.agents.length, 3);
      assert.equal(record.sourcePackage, sourcePackage);
      assert.equal(record.source.kind, source);
      assert.equal(record.skillInstallMode, source === "repository" ? "symlink" : "copy");
      assertUnifiedInstall(target, tool, "ops-direct-invoke");
      if (tool === "codex") {
        assert.equal(existsSync(join(sandbox, "home", "plugins", "ops-direct-invoke", ".codex-plugin", "plugin.json")), true);
      }
    });
  }
}

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs model-infer-optimize for ${tool}`, () => {
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
      assert.equal(record.skillInstallMode, source === "repository" ? "symlink" : "copy");
      assertSkillInstallation(
        join(skillRoot(target, tool), "model-infer-migrator"),
        source,
        "model-infer-optimize",
        "model-infer-migrator",
      );
      assertUnifiedInstall(target, tool, "model-infer-optimize");
      if (tool === "claude") {
        assert.equal(existsSync(join(root, "settings.json")), true);
        assert.equal(existsSync(join(target, ".cannbot", "plugins", "model-infer-optimize", "hooks", "pre_tool_use.py")), true);
      }
    });
  }
}

const trainPrecisionSkills = [
  "model-train-precision-numerical-mismatch",
  "model-train-precision-nonfinite",
  "model-train-precision-determinism",
  "model-train-log-visualization",
];
const trainPrecisionAgents = [
  "model-train-precision-scope-reducer-agent",
  "model-train-precision-numerical-mismatch-agent",
  "model-train-precision-nonfinite-agent",
  "model-train-precision-determinism-agent",
  "model-train-precision-reviewer-agent",
];
const trainPrecisionReferences = [
  "cluster-execution-and-artifact-plane.md",
  "dump-integrity-and-compare-gate.md",
  "evidence-and-risk-policy.md",
  "intake-routing.md",
  "optional-hardware-and-silent-error-checks.md",
  "preflight-checklist.md",
  "record-templates.md",
  "reviewer-contract.md",
  "scope-reduction.md",
  "subagent-prompt-templates.md",
  "tool-semantics-and-version-probe.md",
];

for (const source of sources) {
  for (const tool of tools) {
    test(`${source} installs model-train-precision-diagnose for ${tool}`, () => {
      const plugin = "model-train-precision-diagnose";
      const { target } = installPlugin(plugin, tool, source);
      const root = configRoot(target, tool);
      const agentExtension = tool === "codex" ? ".toml" : ".md";
      const workflowRoot = join(target, ".cannbot", "plugins", plugin, "workflows");
      const installedReferencePrefix = `.cannbot/plugins/${plugin}/workflows/references/`;

      for (const skill of trainPrecisionSkills) {
        const installedSkill = join(skillRoot(target, tool), skill);
        assert.equal(existsSync(join(installedSkill, "SKILL.md")), true);
        assertSkillInstallation(installedSkill, source, plugin, skill);
      }
      for (const agent of trainPrecisionAgents) {
        const installedAgent = join(root, "agents", `${agent}${agentExtension}`);
        assert.equal(existsSync(installedAgent), true);
        const content = readFileSync(installedAgent, "utf8");
        assert.equal(content.includes(installedReferencePrefix), true);
        assert.doesNotMatch(content, /\.\.\/(?:\.cannbot|references|workflows)\//);
      }

      assert.equal(existsSync(join(workflowRoot, "precision-diagnose-workflow.md")), true);
      for (const reference of trainPrecisionReferences) {
        assert.equal(existsSync(join(workflowRoot, "references", reference)), true);
      }

      const instructionsPath = join(target, tool === "claude" ? "CLAUDE.md" : "AGENTS.md");
      const instructions = readFileSync(instructionsPath, "utf8");
      assert.equal(instructions.includes(installedReferencePrefix), true);
      assert.doesNotMatch(instructions, /\.\.\/(?:\.cannbot|references|workflows)\//);

      const record = readPluginRecord(target, tool, plugin);
      assert.equal(record.skills.length, 4);
      assert.equal(record.agents.length, 5);
      assert.equal(record.source.kind, source);
      assert.equal(record.skillInstallMode, source === "repository" ? "symlink" : "copy");
      assertUnifiedInstall(target, tool, plugin);
    });
  }
}

for (const plugin of ["ascendc-st-design", "model-infer-optimize"]) {
  test(`${plugin} source init delegates to the unified installer`, () => {
    const { target } = installWithSourceInit(plugin, "opencode");
    const record = readPluginRecord(target, "opencode", plugin);
    assert.equal(record.skillInstallMode, "symlink");
    assert.equal(lstatSync(join(target, record.skills[0])).isSymbolicLink(), true);
    assert.equal(existsSync(join(configRoot(target, "opencode"), "cannbot-plugin.json")), true);
    assertUnifiedInstall(target, "opencode", plugin);
  });
}

test("model-train-precision-diagnose source init delegates to the unified installer", () => {
  const plugin = "model-train-precision-diagnose";
  const { target } = installWithSourceInit(plugin, "opencode");
  const record = readPluginRecord(target, "opencode", plugin);
  assert.equal(record.skillInstallMode, "symlink");
  assert.equal(record.skills.length, 4);
  assert.equal(record.agents.length, 5);
  assert.equal(
    existsSync(join(target, ".cannbot", "plugins", plugin, "workflows", "references", "tool-semantics-and-version-probe.md")),
    true,
  );
  assertUnifiedInstall(target, "opencode", plugin);
});

test("ops-direct-invoke source init uses the unified installer", () => {
  const { target } = installWithSourceInit("ops-direct-invoke", "opencode");
  const root = configRoot(target, "opencode");
  assertUnifiedInstall(target, "opencode", "ops-direct-invoke");
  assert.equal(existsSync(join(target, ".cannbot", "permissions", "PM.js")), false);
  assert.equal(existsSync(join(skillRoot(target, "opencode"), "ops-direct-invoke", "SKILL.md")), true);
  assert.equal(existsSync(join(root, "agents", "ops-direct-invoke-verifier.md")), true);
});

test("source init defaults to the source repository root and reads the manifest name", () => {
  const sandbox = createSandbox("cannbot-init-default-");
  const fixtureRepository = join(sandbox, "repository");
  const pluginDir = join(fixtureRepository, "plugins-official", "fixture-plugin");
  const fixtureCli = join(fixtureRepository, "script", "bin", "cannbot.js");
  const capture = join(sandbox, "args.json");
  mkdirSync(join(pluginDir, ".claude-plugin"), { recursive: true });
  writeFileSync(join(pluginDir, ".claude-plugin", "plugin.json"), JSON.stringify({ name: "fixture-entry" }));
  mkdirSync(join(fixtureRepository, "script", "bin"), { recursive: true });
  writeFileSync(fixtureCli, [
    "const fs = require('node:fs');",
    "fs.writeFileSync(process.env.CANNBOT_CAPTURE, JSON.stringify(process.argv.slice(2)));",
    "",
  ].join("\n"));

  const result = spawnSync("bash", [join(packageRoot, "bin", "source-plugin-init.sh"), pluginDir], {
    cwd: pluginDir,
    encoding: "utf8",
    env: { ...process.env, CANNBOT_CAPTURE: capture },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const args = JSON.parse(readFileSync(capture, "utf8"));
  assert.deepEqual(args, [
    "install",
    "fixture-entry",
    "--tool",
    "opencode",
    "--target",
    fixtureRepository,
    "--source",
    fixtureRepository,
    "--plugin-dir",
    pluginDir,
  ]);
});

test("source install preserves an existing real Skill directory", () => {
  const sandbox = createSandbox("cannbot-skill-collision-");
  const target = join(sandbox, "project");
  const destination = join(target, ".agents", "skills", "ascendc-st-design");
  const sentinel = join(destination, "user-content.txt");
  mkdirSync(destination, { recursive: true });
  writeFileSync(sentinel, "keep\n");

  const result = spawnSync(process.execPath, [
    cli,
    "install",
    "ascendc-st-design",
    "--tool",
    "opencode",
    "--target",
    target,
    "--source",
    repositoryRoot,
  ], {
    cwd: target,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: join(sandbox, "home"),
      CANNBOT_SKIP_OPENCODE_PLUGIN_ADD: "1",
      CANNBOT_SKIP_DEPENDENCY_REPOS: "1",
    },
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Skill destination already exists and is not a symlink/);
  assert.equal(readFileSync(sentinel, "utf8"), "keep\n");
  assert.equal(lstatSync(destination).isDirectory(), true);
});

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
  assert.match(instructions, /^# 工作区 PM$/m);
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
  const bundleRoot = join(sandbox, "bundle");
  const pluginRoot = join(bundleRoot, "plugins-official", plugin);
  const skillsRepository = join(bundleRoot, "skills-repository");
  const fixtureSkill = join(skillsRepository, "fixture-skill");
  mkdirSync(join(pluginRoot, ".claude-plugin"), { recursive: true });
  mkdirSync(join(fixtureSkill, "scripts"), { recursive: true });
  mkdirSync(join(skillsRepository, ".git"));
  writeFileSync(join(pluginRoot, ".claude-plugin", "plugin.json"), JSON.stringify({
    name: plugin,
    version: "1.0.0",
    description: "Dependency fixture",
  }));
  writeFileSync(join(pluginRoot, "plugin-sources.json"), JSON.stringify({
    skillsRepository: "skills-repository",
    skillInstallMode: "symlink",
    skills: ["fixture-skill"],
  }));
  writeFileSync(join(fixtureSkill, "SKILL.md"), [
    "---",
    "name: fixture-skill",
    "description: Test fixture",
    "---",
    "",
  ].join("\n"));
  writeFileSync(join(fixtureSkill, "scripts", "clean_markdown.py"), [
    "import argparse",
    "from pathlib import Path",
    "parser = argparse.ArgumentParser()",
    "parser.add_argument('--dir', required=True)",
    "parser.add_argument('--no-backup', action='store_true')",
    "parser.add_argument('--quiet', action='store_true')",
    "args = parser.parse_args()",
    "Path(args.dir, '.cleaned-by-skill').write_text('cleaned\\n')",
    "",
  ].join("\n"));
  writeFileSync(join(pluginRoot, "plugin-install.json"), JSON.stringify({
    dependencies: [{
      name: "fixture-dependency",
      repository: dependencyRepository,
      expose: "fixture-dependency",
      cleanMarkdownWithSkill: "fixture-skill",
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
    bundleRoot,
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
  assert.equal(readFileSync(join(checkout, ".cleaned-by-skill"), "utf8"), "cleaned\n");
  assert.equal(lstatSync(join(target, "fixture-dependency")).isSymbolicLink(), true);
  assert.equal(isAbsolute(readlinkSync(join(target, "fixture-dependency"))), false);
  const record = readPluginRecord(target, "dsh", plugin);
  assert.deepEqual(record.dependencies, [join(".cannbot", "dependencies", plugin, "fixture-dependency")]);
});
