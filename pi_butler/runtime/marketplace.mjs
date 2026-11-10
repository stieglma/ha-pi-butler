// Use the pinned marketplace's command handlers; never write its managed state.
import { readFile, writeFile, rename } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const runtime = resolve(process.argv[2] ?? '/opt/runtime');
const source = resolve(process.argv[3] ?? '/opt/butler-marketplace');
const agentDir = process.env.PI_CODING_AGENT_DIR ?? '/data/pi';
const historyPath = join(agentDir, 'butler-marketplace.json');
const readJson = async (path, fallback) => {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
};
const history = await readJson(historyPath, { offered: false });
const config = await readJson(join(agentDir, 'claude-plugins.json'), {});
const overrides = await readJson(join(agentDir, 'claude-plugins.local.json'), {});
const marketplaces = { ...config.marketplaces, ...overrides.marketplaces };
const plugins = { ...config.plugins, ...overrides.plugins };
const name = 'pi-butler';
const plugin = 'house@pi-butler';
// Never replace a user's source, reinstall a removed default, or re-enable it.
if (marketplaces[name] && marketplaces[name].source !== source) process.exit(0);
if (history.offered && (!marketplaces[name] || !plugins[plugin] || plugins[plugin].enabled === false)) process.exit(0);

const sdkPath = join(runtime, 'node_modules/@earendil-works/pi-coding-agent');
const manifest = await readJson(join(sdkPath, 'package.json'));
const sdk = await import(pathToFileURL(join(sdkPath, manifest.exports['.'].import)));
const extension = join(runtime, 'node_modules/pi-claude-marketplace/extensions/pi-claude-marketplace/index.ts');
const loader = new sdk.DefaultResourceLoader({
  cwd: process.cwd(), agentDir, settingsManager: sdk.SettingsManager.inMemory({ packages: [] }),
  noExtensions: true, additionalExtensionPaths: [extension],
  noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
});
await loader.reload();
const loaded = loader.getExtensions();
if (loaded.errors.length) throw new Error('Bundled marketplace extension could not load');
const command = loaded.extensions.flatMap((entry) => [...entry.commands.entries()])
  .find(([key]) => key === 'claude:plugin')?.[1];
if (!command) throw new Error('Marketplace command unavailable');
let outcomes = [];
loaded.runtime.getAllTools = () => [];
loaded.runtime.getCommands = () => [];
loaded.runtime.appendEntry = (_type, payload) => outcomes.push(payload);
const failed = (value) => value && typeof value === 'object' &&
  (value.status === 'failed' || value.kind === 'command-error' || Object.values(value).some(failed));
const ctx = { cwd: process.cwd(), mode: 'rpc', hasUI: false, isProjectTrusted: () => false,
  ui: { notify() {}, confirm: async () => false } };
async function run(args) {
  outcomes = [];
  await command.handler(args, ctx);
  if (!outcomes.length || outcomes.some(failed)) throw new Error('Local marketplace setup failed; use /claude:plugin list to inspect it.');
}
if (!marketplaces[name]) await run(`marketplace add ${source} --scope user`);
if (!history.offered && !plugins[plugin]) await run(`install ${plugin} --scope user`);
else if (plugins[plugin]?.enabled !== false) await run(`update ${plugin} --scope user`);
await writeFile(historyPath + '.tmp', JSON.stringify({ offered: true }) + '\n', { mode: 0o600 });
await rename(historyPath + '.tmp', historyPath);
console.log('Local Pi Butler marketplace ready.');
