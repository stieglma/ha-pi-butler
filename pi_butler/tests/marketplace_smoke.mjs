// Pinned SDK + actual marketplace lifecycle, no model/API calls or downloads.
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const runtime = resolve(process.argv[2] ?? '/opt/runtime');
const bundled = resolve(process.argv[3] ?? '/opt/butler-marketplace');
const bootstrap = resolve(process.argv[4] ?? join(runtime, 'butler/marketplace.mjs'));
const temporary = await mkdtemp(join(tmpdir(), 'butler-marketplace-'));
const agent = join(temporary, 'agent');
const source = join(temporary, 'marketplace');
const json = async (path) => JSON.parse(await readFile(path, 'utf8'));
try {
  await cp(bundled, source, { recursive: true });
  const { mkdir } = await import('node:fs/promises');
  await mkdir(agent);
  process.env.HOME = temporary;
  process.env.PI_CODING_AGENT_DIR = agent;
  process.env.PI_OFFLINE = 'true';
  process.env.PI_SKIP_VERSION_CHECK = 'true';
  const configPath = join(agent, 'claude-plugins.json');
  // Existing user configuration must survive; never turn on global autoapply.
  await writeFile(configPath, JSON.stringify({ autoapply: false, marketplaces: {}, plugins: {}, custom: 'keep' }));
  const run = () => {
    const result = spawnSync(process.execPath, [bootstrap, runtime, source], {
      cwd: temporary, env: process.env, encoding: 'utf8', timeout: 60000,
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
  };
  run();
  run();
  const config = await json(configPath);
  assert.equal(config.custom, 'keep');
  assert.equal(config.autoapply, false);
  assert.equal(config.marketplaces['pi-butler'].source, source);
  assert(config.plugins['house@pi-butler']);
  const sdkRoot = join(runtime, 'node_modules/@earendil-works/pi-coding-agent');
  const pkg = await json(join(sdkRoot, 'package.json'));
  const sdk = await import(pathToFileURL(join(sdkRoot, pkg.exports['.'].import)));
  const loader = new sdk.DefaultResourceLoader({ cwd: temporary, agentDir: agent,
    settingsManager: sdk.SettingsManager.inMemory({ packages: [] }), noExtensions: true,
    additionalExtensionPaths: [join(runtime, 'node_modules/pi-claude-marketplace/extensions/pi-claude-marketplace/index.ts')],
    noContextFiles: true,
  });
  await loader.reload();
  const loaded = loader.getExtensions();
  assert.deepEqual(loaded.errors, []);
  loaded.runtime.getAllTools = () => [];
  loaded.runtime.getCommands = () => [];
  loaded.runtime.appendEntry = () => {};
  const skillPaths = [];
  for (const extension of loaded.extensions) {
    for (const handler of extension.handlers.get('resources_discover') ?? []) {
      const result = await handler({ type: 'resources_discover', cwd: temporary, reason: 'startup' }, {
        cwd: temporary, mode: 'rpc', hasUI: false, isProjectTrusted: () => false, ui: { notify() {} },
      });
      skillPaths.push(...result.skillPaths);
    }
  }
  assert.equal(skillPaths.length, 6, 'All six house skills must be discoverable through the marketplace');
  loader.extendResources({ skillPaths: skillPaths.map((path) => ({ path, metadata: { source: 'extension:marketplace', scope: 'temporary', origin: 'top-level' } })) });
  const names = loader.getSkills().skills.map((skill) => skill.name).sort();
  assert.deepEqual(names, ['house-debug-automation', 'house-explain-automation', 'house-health-check', 'house-memory', 'house-why-did-it-happen', 'house-why-didnt-it-happen']);

  // An image upgrade changes local plugin versions and refreshes installed skills.
  const pluginPath = join(source, 'plugins/house/.claude-plugin/plugin.json');
  const plugin = await json(pluginPath);
  plugin.version = '0.1.2';
  await writeFile(pluginPath, JSON.stringify(plugin));
  const marketplacePath = join(source, '.claude-plugin/marketplace.json');
  const marketplace = await json(marketplacePath);
  marketplace.plugins[0].version = '0.1.2';
  await writeFile(marketplacePath, JSON.stringify(marketplace));
  run();
  const statePath = join(agent, 'pi-claude-marketplace/state.json');
  assert.equal((await json(statePath)).marketplaces['pi-butler'].plugins.house.version, '0.1.2');

  // User disable/removal is respected at the next startup.
  config.plugins['house@pi-butler'].enabled = false;
  await writeFile(configPath, JSON.stringify(config));
  const before = await readFile(statePath, 'utf8');
  run();
  assert.equal(await readFile(statePath, 'utf8'), before);
  assert.equal((await json(configPath)).plugins['house@pi-butler'].enabled, false);
  delete config.plugins['house@pi-butler'];
  await writeFile(configPath, JSON.stringify(config));
  run();
  assert.equal((await json(configPath)).plugins['house@pi-butler'], undefined);
  assert.equal(await readFile(statePath, 'utf8'), before);
  console.log('Local marketplace install, restart, discovery, upgrade, user disable/removal and config preservation passed.');
} finally { await rm(temporary, { recursive: true, force: true }); }
