#!/usr/bin/env node

import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { pluginSourceDefinition } from "../lib/plugin-bundle.js";

const installerPackage = readJson(new URL("../package.json", import.meta.url));
const OPENCODE_PLUGIN_SPEC = `${installerPackage.name}@${installerPackage.version}`;
const BUNDLED_REPOSITORY = fileURLToPath(new URL("../", import.meta.url));
const PACKAGE_CACHEBUSTER = `cannbot-${installerPackage.version.replaceAll(".", "-")}`;
const TOOL_DIRECTORIES = Object.freeze({
  opencode: { configDirs: [".opencode"], defaultConfigDir: ".opencode", skillsDir: [".agents", "skills"] },
  codex: { configDirs: [".codex"], defaultConfigDir: ".codex", skillsDir: [".agents", "skills"] },
  claude: { configDirs: [".claude"], defaultConfigDir: ".claude" },
  trae: { configDirs: [".traecli", ".marscode", ".trae", ".trae-cn"], defaultConfigDir: ".trae" },
  dsh: { configDirs: [".dsh"], defaultConfigDir: ".dsh" },
});
const TOOL_NAMES = Object.keys(TOOL_DIRECTORIES);

function fail(message) {
  console.error(`cannbot: ${message}`);
  process.exit(1);
}

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  if (result.error) fail(`${command} failed: ${result.error.message}`);
  if (result.status !== 0) fail(`${command} exited with status ${result.status}`);
}

function tryRun(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  return !result.error && result.status === 0;
}

function parseArgs(argv) {
  const [command, pluginId, ...rest] = argv;
  if (command !== "install" || !pluginId) {
    fail(`usage: cannbot install <plugin> --tool <${TOOL_NAMES.join("|")}> [--target <dir>] [--source <repository>]`);
  }
  const options = { command, pluginId, target: process.cwd() };
  for (let index = 0; index < rest.length; index += 1) {
    const key = rest[index];
    const value = rest[index + 1];
    if (!value) fail(`missing value for ${key}`);
    if (key === "--tool") options.tool = value;
    else if (key === "--target") options.target = resolve(value);
    else if (key === "--source" || key === "--repo") options.source = resolve(value);
    else fail(`unknown option: ${key}`);
    index += 1;
  }
  if (!TOOL_DIRECTORIES[options.tool]) {
    fail(`--tool must be one of: ${TOOL_NAMES.join(", ")}`);
  }
  return options;
}

function resolvePluginDir(repoPath, pluginId) {
  for (const parent of ["plugins", join("dist", "plugins")]) {
    const candidate = join(repoPath, parent, pluginId);
    if (existsSync(join(candidate, ".claude-plugin", "plugin.json"))
        && existsSync(join(candidate, "skills"))) return candidate;
  }
  return null;
}

function containsPlugin(repoPath, pluginId) {
  return resolvePluginDir(repoPath, pluginId) !== null;
}

function resolveBundle(override, pluginId) {
  if (override) {
    const source = pluginSourceDefinition(override, pluginId);
    if (source) {
      const skillsRepository = resolve(override, source.skillsRepository);
      if (!existsSync(join(skillsRepository, ".git"))) {
        console.log(`Initializing ${source.skillsRepository} submodule...`);
        run("git", ["submodule", "update", "--init", "--recursive", "--depth", "1", source.skillsRepository], override);
      }
      return source.pluginRoot;
    }
    if (containsPlugin(override, pluginId)) return resolvePluginDir(override, pluginId);
    fail(`invalid CANNBot repository: ${override}`);
  }

  if (containsPlugin(BUNDLED_REPOSITORY, pluginId)) return resolvePluginDir(BUNDLED_REPOSITORY, pluginId);

  fail(`plugin not included in this CANNBot release: ${pluginId}`);
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJsonAtomic(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`);
  renameSync(temporary, path);
}

function instructionMarkers(pluginName) {
  return {
    start: `<!-- cannbot:${pluginName}:start -->`,
    end: `<!-- cannbot:${pluginName}:end -->`,
  };
}

function installSkill(source, destination, mode) {
  if (mode === "symlink") {
    if (pathExists(destination)) {
      if (!lstatSync(destination).isSymbolicLink()) {
        fail(`Skill destination already exists and is not a symlink: ${destination}`);
      }
      rmSync(destination, { force: true });
    }
    const linkTarget = relative(dirname(destination), source) || ".";
    symlinkSync(linkTarget, destination, "dir");
    return;
  }
  rmSync(destination, { recursive: true, force: true });
  cpSync(source, destination, { recursive: true, dereference: true });
}

function installPluginAssets(pluginDir, plugin, target, sourceDefinition) {
  const relativeRoot = `.cannbot/plugins/${plugin.name}`;
  const destinationRoot = join(target, relativeRoot);
  rmSync(destinationRoot, { recursive: true, force: true });
  mkdirSync(destinationRoot, { recursive: true });
  const assets = { destinationRoot, relativeRoot };
  let installed = false;
  for (const name of ["workflows", "hooks", "LICENSE", "SKILLS_LICENSE"]) {
    let source = join(pluginDir, name);
    if (!existsSync(source) && sourceDefinition && name === "LICENSE") {
      source = join(dirname(pluginDir), "LICENSE");
    } else if (!existsSync(source) && sourceDefinition && name === "SKILLS_LICENSE") {
      source = join(resolve(pluginDir, "..", "..", sourceDefinition.skillsRepository), "LICENSE");
    }
    if (!existsSync(source)) continue;
    cpSync(source, join(destinationRoot, name), { recursive: true, dereference: true });
    installed = true;
  }
  if (!installed) {
    rmSync(destinationRoot, { recursive: true, force: true });
    return null;
  }
  const workflows = join(destinationRoot, "workflows");
  if (existsSync(workflows)) rewriteTreeReferences(workflows, assets);
  return assets;
}

function rewritePluginReferences(markdown, assets) {
  if (!assets) return markdown;
  return markdown.replaceAll("workflows/", `${assets.relativeRoot}/workflows/`);
}

function rewriteTreeReferences(root, assets) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      rewriteTreeReferences(path, assets);
      continue;
    }
    if (!entry.isFile() || !/\.(?:md|txt|sh|py|json|ya?ml)$/i.test(entry.name)) continue;
    const current = readFileSync(path, "utf8");
    const rewritten = rewritePluginReferences(current, assets);
    if (rewritten !== current) writeFileSync(path, rewritten);
  }
}

function toolConfigDir(target, tool) {
  const layout = TOOL_DIRECTORIES[tool];
  return layout.configDirs
    .map((name) => join(target, name))
    .find((path) => existsSync(path)) ?? join(target, layout.defaultConfigDir);
}

function toolSkillsDir(target, tool) {
  const skillsDir = TOOL_DIRECTORIES[tool].skillsDir;
  if (skillsDir) return join(target, ...skillsDir);
  return join(toolConfigDir(target, tool), "skills");
}

function toolAgentsDir(target, tool) {
  return join(toolConfigDir(target, tool), "agents");
}

function resolveSkills(plugin, pluginDir) {
  const skills = new Map();
  const addSkill = (source) => {
    const skillPath = join(source, "SKILL.md");
    if (!existsSync(skillPath)) fail(`skill is missing SKILL.md: ${source}`);
    const name = readFileSync(skillPath, "utf8").match(/^name:\s*([^\r\n]+)$/m)?.[1]?.trim();
    if (!name) fail(`skill is missing a frontmatter name: ${skillPath}`);
    skills.set(name, source);
  };

  for (const relativeSkill of plugin.skills ?? []) {
    addSkill(resolve(pluginDir, relativeSkill));
  }

  const localSkills = join(pluginDir, "skills");
  if (existsSync(localSkills)) {
    for (const entry of readdirSync(localSkills, { withFileTypes: true })) {
      if (entry.isDirectory() && existsSync(join(localSkills, entry.name, "SKILL.md"))) {
        addSkill(join(localSkills, entry.name));
      }
    }
  }
  for (const entry of readdirSync(pluginDir, { withFileTypes: true })) {
    const source = join(pluginDir, entry.name);
    if (entry.isDirectory() && existsSync(join(source, "SKILL.md"))) addSkill(source);
  }

  return [...skills.entries()].map(([name, source]) => ({ name, source }));
}

function resolveSourceSkills(repositoryRoot, sourceDefinition) {
  const skillsRepository = resolve(repositoryRoot, sourceDefinition.skillsRepository);
  const skills = new Map();
  for (const relativeSkill of sourceDefinition.skills) {
    if (typeof relativeSkill !== "string" || !relativeSkill) {
      fail(`invalid Skill path in ${sourceDefinition.definitionPath}`);
    }
    const source = resolve(skillsRepository, relativeSkill);
    const pathFromRoot = relative(skillsRepository, source);
    if (pathFromRoot.startsWith("..") || isAbsolute(pathFromRoot)) {
      fail(`Skill path escapes its repository root: ${relativeSkill}`);
    }
    const skillPath = join(source, "SKILL.md");
    if (!existsSync(skillPath)) fail(`skill is missing SKILL.md: ${source}`);
    const name = readFileSync(skillPath, "utf8").match(/^name:\s*([^\r\n]+)$/m)?.[1]?.trim();
    if (!name) fail(`skill is missing a frontmatter name: ${skillPath}`);
    if (skills.has(name)) fail(`duplicate Skill name in source definition: ${name}`);
    skills.set(name, source);
  }
  return [...skills.entries()].map(([name, source]) => ({ name, source }));
}

function parseAgent(markdown) {
  const match = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  const frontmatter = match?.[1] ?? "";
  const body = (match?.[2] ?? markdown).trim();
  const name = frontmatter.match(/^name:\s*(.+)$/m)?.[1]?.trim();
  const description = frontmatter.match(/^description:\s*(.+)$/m)?.[1]?.trim();
  if (!name || !description) fail("agent markdown requires name and description frontmatter");
  return { name, description, body };
}

function installAgents(pluginDir, plugin, tool, target, assets, agentsDirOverride) {
  const agentsDir = agentsDirOverride ?? toolAgentsDir(target, tool);
  mkdirSync(agentsDir, { recursive: true });
  const installed = [];

  for (const relativeAgent of plugin.agents ?? []) {
    const source = resolve(pluginDir, relativeAgent);
    const markdown = rewritePluginReferences(readFileSync(source, "utf8"), assets);
    if (tool !== "codex") {
      const destination = join(agentsDir, basename(source));
      rmSync(destination, { recursive: true, force: true });
      writeFileSync(destination, markdown);
      installed.push(destination);
      continue;
    }

    const agent = parseAgent(markdown);
    const destination = join(agentsDir, `${agent.name}.toml`);
    const toml = [
      `name = ${JSON.stringify(agent.name)}`,
      `description = ${JSON.stringify(agent.description)}`,
      `developer_instructions = ${JSON.stringify(agent.body)}`,
      "",
    ].join("\n");
    writeFileSync(destination, toml);
    installed.push(destination);
  }
  return installed;
}

function installInstructions(pluginDir, plugin, target, tool, assets) {
  const source = join(pluginDir, "AGENTS.md");
  if (!existsSync(source)) return null;
  const destination = join(target, tool === "claude" ? "CLAUDE.md" : "AGENTS.md");
  const current = existsSync(destination) ? readFileSync(destination, "utf8") : "";
  const markers = instructionMarkers(plugin.name);
  const withoutOldBlock = current
    .replace(new RegExp(`${markers.start}[\\s\\S]*?${markers.end}\\s*`, "g"), "")
    .trimEnd();
  const pluginInstructions = rewritePluginReferences(readFileSync(source, "utf8"), assets).trim();
  const parts = [withoutOldBlock, markers.start, pluginInstructions, markers.end, ""].filter(Boolean);
  const temporary = `${destination}.${process.pid}.tmp`;
  writeFileSync(temporary, parts.join("\n\n"));
  renameSync(temporary, destination);
  return destination;
}

function updateInstallRegistry(path, record) {
  let registry = { schemaVersion: 2, plugins: [] };
  if (existsSync(path)) {
    const existing = readJson(path);
    if (existing?.schemaVersion === 2 && Array.isArray(existing.plugins)) registry = existing;
  }
  const index = registry.plugins.findIndex((plugin) => plugin?.plugin === record.plugin);
  if (index === -1) registry.plugins.push(record);
  else registry.plugins[index] = record;
  registry.plugins.sort((left, right) => left.plugin.localeCompare(right.plugin));
  writeJsonAtomic(path, registry);
}

function replaceStrings(value, replacement) {
  if (typeof value === "string") return value.replaceAll("${CLAUDE_PLUGIN_ROOT}", replacement);
  if (Array.isArray(value)) return value.map((entry) => replaceStrings(entry, replacement));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, replaceStrings(entry, replacement)]));
}

function installClaudeHooks(pluginDir, target, tool, assets) {
  const definitionPath = join(pluginDir, "hooks", "hooks.json");
  if (tool !== "claude" || !assets || !existsSync(definitionPath)) return null;

  const configDir = toolConfigDir(target, tool);
  const settingsPath = join(configDir, "settings.json");
  const existing = existsSync(settingsPath) ? readJson(settingsPath) : {};
  const definition = replaceStrings(readJson(definitionPath), assets.destinationRoot);
  existing.hooks ??= {};
  for (const [event, entries] of Object.entries(definition.hooks ?? {})) {
    const current = Array.isArray(existing.hooks[event]) ? existing.hooks[event] : [];
    const known = new Set(current.map((entry) => JSON.stringify(entry)));
    for (const entry of entries) {
      const serialized = JSON.stringify(entry);
      if (!known.has(serialized)) current.push(entry);
      known.add(serialized);
    }
    existing.hooks[event] = current;
  }
  writeJsonAtomic(settingsPath, existing);
  return settingsPath;
}

function pathExists(path) {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

function repositoryIdentity(url) {
  return url.replace(/^git@gitcode\.com:/, "https://gitcode.com/").replace(/\.git$/, "").replace(/\/$/, "");
}

function exposeDependency(source, destination) {
  if (pathExists(destination)) {
    if (lstatSync(destination).isSymbolicLink()) {
      rmSync(destination, { force: true });
    } else {
      console.warn(`cannbot: dependency path already exists, keeping it unchanged: ${destination}`);
      return false;
    }
  }
  symlinkSync(relative(dirname(destination), source) || ".", destination, "dir");
  return true;
}

function provisionDependencies(pluginDir, plugin, target, skills) {
  const definitionPath = join(pluginDir, "plugin-install.json");
  if (!existsSync(definitionPath)) return [];
  const definition = readJson(definitionPath);
  const dependencies = Array.isArray(definition.dependencies) ? definition.dependencies : [];
  if (process.env.CANNBOT_SKIP_DEPENDENCY_REPOS === "1") {
    if (dependencies.length) console.log("Skipping dependency repositories (CANNBOT_SKIP_DEPENDENCY_REPOS=1)");
    return [];
  }

  const dependencyRoot = join(target, ".cannbot", "dependencies", plugin.name);
  mkdirSync(dependencyRoot, { recursive: true });
  const installed = [];
  for (const dependency of dependencies) {
    if (!dependency?.name || !dependency?.repository || /[\\/]/.test(dependency.name)) {
      fail(`invalid dependency in ${definitionPath}`);
    }
    const destination = join(dependencyRoot, dependency.name);
    let available = existsSync(join(destination, ".git"));
    if (available) {
      const remote = spawnSync("git", ["-C", destination, "remote", "get-url", "origin"], { encoding: "utf8" });
      if (remote.status !== 0 || repositoryIdentity(remote.stdout.trim()) !== repositoryIdentity(dependency.repository)) {
        console.warn(`cannbot: ${dependency.name} has an unexpected origin; update skipped`);
        available = false;
      } else {
        const pulled = tryRun("git", ["-C", destination, "pull", "--ff-only"], target);
        if (!pulled) console.warn(`cannbot: failed to update ${dependency.name}; using the existing checkout`);
      }
    } else if (pathExists(destination)) {
      console.warn(`cannbot: ${dependency.name} exists but is not a Git checkout; clone skipped`);
    } else {
      const args = ["clone", "--depth", "1"];
      if (dependency.ref) args.push("--branch", dependency.ref);
      if (dependency.recursive) args.push("--recurse-submodules", "--shallow-submodules");
      args.push(dependency.repository, destination);
      available = tryRun("git", args, target);
      if (!available) console.warn(`cannbot: failed to clone ${dependency.name}; continuing without it`);
    }
    if (!available) continue;
    if (dependency.recursive) {
      const updated = tryRun("git", ["-C", destination, "submodule", "update", "--init", "--recursive", "--depth", "1"], target);
      if (!updated) console.warn(`cannbot: ${dependency.name} submodule update was incomplete`);
    }
    if (dependency.cleanMarkdownWithSkill) {
      const cleanerSkill = skills.find((skill) => skill.name === dependency.cleanMarkdownWithSkill);
      const cleaner = cleanerSkill
        ? join(cleanerSkill.source, "scripts", "clean_markdown.py")
        : null;
      if (cleaner && existsSync(cleaner)) {
        const cleaned = tryRun("python3", [cleaner, "--dir", destination, "--no-backup", "--quiet"], target);
        if (!cleaned) console.warn(`cannbot: markdown cleanup failed for ${dependency.name}`);
      } else {
        console.warn(`cannbot: cleanup Skill is unavailable: ${dependency.cleanMarkdownWithSkill}`);
      }
    }
    if (dependency.expose) exposeDependency(destination, join(target, dependency.expose));
    installed.push(join(".cannbot", "dependencies", plugin.name, dependency.name));
  }
  return installed;
}

function installCodexPlugin(plugin, skills, target, skillInstallMode) {
  const userHome = resolve(process.env.HOME || homedir());
  const pluginRoot = join(userHome, "plugins", plugin.name);
  const pluginSkills = join(pluginRoot, "skills");
  rmSync(pluginRoot, { recursive: true, force: true });
  mkdirSync(pluginSkills, { recursive: true });
  for (const skill of skills) {
    installSkill(skill.source, join(pluginSkills, skill.name), skillInstallMode);
  }

  const developerName = plugin.author?.name || "CANNBot";
  const displayName = `CANNBot ${plugin.name
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")}`;
  const manifest = {
    name: plugin.name,
    version: `${plugin.version}+codex.${PACKAGE_CACHEBUSTER}`,
    description: plugin.description,
    author: { name: developerName },
    homepage: plugin.homepage,
    repository: plugin.repository,
    license: plugin.license,
    keywords: [...new Set(["cannbot", ...(plugin.keywords ?? [])])],
    skills: "./skills/",
    interface: {
      displayName,
      shortDescription: plugin.description.slice(0, 120),
      longDescription: plugin.description,
      developerName,
      category: "Productivity",
      capabilities: ["Skills", "Agents"],
      defaultPrompt: [`Use ${plugin.name} for this task.`],
    },
  };
  writeJsonAtomic(join(pluginRoot, ".codex-plugin", "plugin.json"), manifest);

  const marketplacePath = join(userHome, ".agents", "plugins", "marketplace.json");
  const marketplace = existsSync(marketplacePath)
    ? readJson(marketplacePath)
    : { name: "personal", interface: { displayName: "Personal" }, plugins: [] };
  if (!marketplace || typeof marketplace !== "object" || Array.isArray(marketplace)) {
    fail(`invalid Codex marketplace: ${marketplacePath}`);
  }
  if (typeof marketplace.name !== "string" || !marketplace.name) {
    fail(`Codex marketplace is missing a name: ${marketplacePath}`);
  }
  if (!Array.isArray(marketplace.plugins)) {
    fail(`Codex marketplace plugins must be an array: ${marketplacePath}`);
  }
  marketplace.interface ??= { displayName: "Personal" };
  const entry = {
    name: plugin.name,
    source: { source: "local", path: `./plugins/${plugin.name}` },
    policy: { installation: "AVAILABLE", authentication: "ON_INSTALL" },
    category: "Productivity",
  };
  const existingIndex = marketplace.plugins.findIndex((candidate) => candidate?.name === plugin.name);
  if (existingIndex === -1) marketplace.plugins.push(entry);
  else marketplace.plugins[existingIndex] = entry;
  writeJsonAtomic(marketplacePath, marketplace);

  if (process.env.CANNBOT_SKIP_CODEX_PLUGIN_ADD !== "1") {
    run("codex", ["plugin", "add", `${plugin.name}@${marketplace.name}`, "--json"], target);
  }
  return { pluginRoot, marketplacePath, marketplaceName: marketplace.name };
}

function installOpenCodePlugin(target) {
  if (process.env.CANNBOT_SKIP_OPENCODE_PLUGIN_ADD !== "1") {
    run("opencode", ["plugin", OPENCODE_PLUGIN_SPEC], target);
  }
  return { package: OPENCODE_PLUGIN_SPEC };
}

function install(options) {
  const sourceRoot = options.source ?? process.env.CANNBOT_SOURCE_ROOT ?? process.env.CANNBOT_SKILLS_PATH;
  const sourceRepositoryRoot = sourceRoot ? resolve(sourceRoot) : null;
  const sourceDefinition = sourceRepositoryRoot
    ? pluginSourceDefinition(sourceRepositoryRoot, options.pluginId)
    : null;
  const pluginDir = resolveBundle(sourceRepositoryRoot, options.pluginId);
  const manifestPath = join(pluginDir, ".claude-plugin", "plugin.json");
  if (!existsSync(manifestPath)) {
    fail(`plugin not found: ${options.pluginId}`);
  }
  mkdirSync(options.target, { recursive: true });

  const plugin = readJson(manifestPath);
  const skillInstallMode = sourceDefinition?.skillInstallMode ?? "copy";
  const resolvedSkills = sourceDefinition
    ? resolveSourceSkills(sourceRepositoryRoot, sourceDefinition)
    : resolveSkills(plugin, pluginDir);
  const skillsDir = toolSkillsDir(options.target, options.tool);
  mkdirSync(skillsDir, { recursive: true });
  const installedSkills = [];
  for (const skill of resolvedSkills) {
    const destination = join(skillsDir, skill.name);
    installSkill(skill.source, destination, skillInstallMode);
    installedSkills.push(destination);
  }

  const assets = installPluginAssets(pluginDir, plugin, options.target, sourceDefinition);
  const installedAgents = installAgents(pluginDir, plugin, options.tool, options.target, assets);
  const instructions = installInstructions(pluginDir, plugin, options.target, options.tool, assets);
  const hookSettings = installClaudeHooks(pluginDir, options.target, options.tool, assets);
  const dependencies = provisionDependencies(pluginDir, plugin, options.target, resolvedSkills);
  const nativePlugin = options.tool === "codex"
    ? installCodexPlugin(plugin, resolvedSkills, options.target, skillInstallMode)
    : options.tool === "opencode"
      ? installOpenCodePlugin(options.target)
      : { initializer: null, discovery: `${toolConfigDir("", options.tool)}/skills` };
  const configDir = toolConfigDir(options.target, options.tool);
  mkdirSync(configDir, { recursive: true });
  const record = {
    plugin: plugin.name,
    pluginVersion: plugin.version,
    sourcePackage: OPENCODE_PLUGIN_SPEC,
    source: sourceRoot ? { kind: "repository" } : { kind: "package", package: OPENCODE_PLUGIN_SPEC },
    tool: options.tool,
    skillInstallMode,
    skills: installedSkills.map((path) => path.slice(options.target.length + 1)),
    agents: installedAgents.map((path) => path.slice(options.target.length + 1)),
    instructions: instructions?.slice(options.target.length + 1) ?? null,
    assets: assets?.relativeRoot ?? null,
    hookSettings: hookSettings?.slice(options.target.length + 1) ?? null,
    dependencies,
    nativePlugin,
    unsupported: existsSync(join(pluginDir, "hooks")) && options.tool !== "claude" ? ["hooks"] : [],
  };
  updateInstallRegistry(join(configDir, "cannbot-plugin.json"), record);

  console.log(`Installed ${plugin.name}@${plugin.version} for ${options.tool}`);
  console.log(`  skills: ${installedSkills.length}`);
  console.log(`  agents: ${installedAgents.length}`);
  console.log(`  target: ${options.target}`);
  if (record.unsupported.length) {
    console.log("  note: this client uses its native project configuration instead of Claude Code hooks");
  }
  if (options.tool === "codex") {
    console.log(`  codex plugin: ${plugin.name}@${nativePlugin.marketplaceName}`);
  } else if (options.tool === "opencode") {
    console.log(`  opencode plugin: ${nativePlugin.package}`);
  } else {
    console.log(`  ${options.tool} skills: ${nativePlugin.discovery}`);
  }
}

install(parseArgs(process.argv.slice(2)));
