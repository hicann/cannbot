import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, isAbsolute, join, relative, resolve } from "node:path";

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function assertInside(root, candidate, label) {
  const pathFromRoot = relative(root, candidate);
  if (pathFromRoot === "" || (!pathFromRoot.startsWith("..") && !isAbsolute(pathFromRoot))) return;
  throw new Error(`${label} escapes its repository root: ${candidate}`);
}

export function pluginSourceDefinition(repositoryRoot, pluginId) {
  const pluginRoot = join(repositoryRoot, "plugins", pluginId);
  const definitionPath = join(pluginRoot, "plugin-sources.json");
  if (!existsSync(definitionPath)) return null;
  const definition = readJson(definitionPath);
  if (!definition || typeof definition.skillsRepository !== "string" || !Array.isArray(definition.skills)) {
    throw new Error(`invalid plugin source definition: ${definitionPath}`);
  }
  if (definition.skillInstallMode !== undefined && definition.skillInstallMode !== "symlink") {
    throw new Error(`invalid Skill install mode in ${definitionPath}`);
  }
  return { pluginRoot, definitionPath, ...definition };
}

export function assemblePlugins(repositoryRoot, outputRoot, selectedPluginIds) {
  const sourcePluginRoot = join(repositoryRoot, "plugins");
  const pluginIds = selectedPluginIds ?? readdirSync(sourcePluginRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(sourcePluginRoot, entry.name, "plugin-sources.json")))
    .map((entry) => entry.name)
    .sort();

  mkdirSync(join(outputRoot, "plugins"), { recursive: true });
  const pluginLicense = join(sourcePluginRoot, "LICENSE");
  if (!existsSync(pluginLicense)) throw new Error(`plugin license is missing: ${pluginLicense}`);
  cpSync(pluginLicense, join(outputRoot, "plugins", "LICENSE"));
  const assembled = [];

  for (const pluginId of pluginIds) {
    const source = pluginSourceDefinition(repositoryRoot, pluginId);
    if (!source) throw new Error(`plugin has no source definition: ${pluginId}`);
    const manifestPath = join(source.pluginRoot, ".claude-plugin", "plugin.json");
    const manifest = readJson(manifestPath);
    if (manifest.name !== pluginId) throw new Error(`plugin manifest name disagrees with directory: ${manifestPath}`);
    const destination = join(outputRoot, "plugins", pluginId);
    rmSync(destination, { recursive: true, force: true });
    mkdirSync(destination, { recursive: true });
    cpSync(pluginLicense, join(destination, "LICENSE"));

    for (const entry of readdirSync(source.pluginRoot, { withFileTypes: true })) {
      if (entry.name === "skills" || entry.name === "plugin-sources.json") continue;
      cpSync(join(source.pluginRoot, entry.name), join(destination, entry.name), {
        recursive: true,
        dereference: true,
      });
    }

    const skillsRepository = resolve(repositoryRoot, source.skillsRepository);
    if (!existsSync(join(skillsRepository, ".git"))) {
      throw new Error(`Skill submodule is not initialized: ${source.skillsRepository}`);
    }
    const skillsLicense = join(skillsRepository, "LICENSE");
    if (!existsSync(skillsLicense)) throw new Error(`Skill repository license is missing: ${skillsLicense}`);
    cpSync(skillsLicense, join(destination, "SKILLS_LICENSE"));
    const names = new Set();
    for (const relativeSkill of source.skills) {
      if (typeof relativeSkill !== "string" || !relativeSkill) {
        throw new Error(`invalid Skill path in ${source.definitionPath}`);
      }
      const skillSource = resolve(skillsRepository, relativeSkill);
      assertInside(skillsRepository, skillSource, "Skill path");
      if (!existsSync(join(skillSource, "SKILL.md"))) {
        throw new Error(`Skill is missing SKILL.md: ${relativeSkill}`);
      }
      const name = basename(skillSource);
      if (names.has(name)) throw new Error(`duplicate Skill name in ${pluginId}: ${name}`);
      names.add(name);
      const skillDestination = join(destination, "skills", name);
      cpSync(skillSource, skillDestination, { recursive: true, dereference: true });
      const skillManifest = join(skillDestination, "SKILL.md");
      const manifest = readFileSync(skillManifest, "utf8")
        .replace(/^disable-model-invocation:\s*true\s*$/m, "disable-model-invocation: false");
      writeFileSync(skillManifest, manifest);
    }
    manifest.skills = [...names].map((name) => `./skills/${name}`);
    delete manifest.dependencies;
    writeFileSync(
      join(destination, ".claude-plugin", "plugin.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    assembled.push({ pluginId, destination, skills: names.size });
  }

  return assembled;
}
