// Load every bundled extension through the pinned Pi SDK without model/API calls.
import assert from 'node:assert/strict';
import { mkdtemp, readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const runtime = resolve(process.argv[2] ?? '/opt/runtime');
const manifest = JSON.parse(await readFile(join(runtime, 'bundled-packages.json'), 'utf8'));
const temporary = await mkdtemp(join(tmpdir(), 'butler-plugins-'));
process.env.HOME = temporary;
process.env.XDG_CONFIG_HOME = join(temporary, 'config');
process.env.PI_CODING_AGENT_DIR = join(temporary, 'agent');
process.env.PI_OFFLINE = 'true';
process.env.PI_SKIP_VERSION_CHECK = 'true';
try {
  const agentDir = process.env.PI_CODING_AGENT_DIR;
  await mkdir(agentDir);
  const packages = manifest.packages.map((name) => join(runtime, 'node_modules', name));
  await writeFile(join(agentDir, 'settings.json'), JSON.stringify({ packages }));
  const sdkRoot = join(runtime, 'node_modules/@earendil-works/pi-coding-agent');
  const sdkManifest = JSON.parse(await readFile(join(sdkRoot, 'package.json'), 'utf8'));
  const sdk = await import(pathToFileURL(join(sdkRoot, sdkManifest.exports['.'].import)));
  const settingsManager = sdk.SettingsManager.create(temporary, agentDir);
  const loader = new sdk.DefaultResourceLoader({ cwd: temporary, agentDir, settingsManager, noContextFiles: true });
  await loader.reload();
  const result = loader.getExtensions();
  assert.deepEqual(result.errors, [], 'Every bundled extension must load without errors');
  for (const name of manifest.packages) {
    const packagePath = join(runtime, 'node_modules', name);
    assert(result.extensions.some((extension) => extension.path.startsWith(packagePath + '/')),
      `Extension not loaded: ${name}`);
  }
  const tools = result.extensions.flatMap((extension) => [...extension.tools.keys()]);
  const commands = result.extensions.flatMap((extension) => [...extension.commands.keys()]);
  assert(tools.includes('ask_user_question'), 'Structured question tool not registered');
  assert(commands.includes('claude:plugin'), 'Marketplace command not registered');
  assert(loader.getSkills().skills.length > 0, 'Bundled workflow/subagent skills not discovered');
  console.log(`Loaded all ${manifest.packages.length} bundled Pi packages; ${tools.length} tools, ${commands.length} commands, ${loader.getSkills().skills.length} skills.`);
} finally {
  await rm(temporary, { recursive: true, force: true });
}
