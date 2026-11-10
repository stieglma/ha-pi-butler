// Return readiness metadata only. Never print provider configuration or credentials.
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
try {
  const runtime = resolve(process.argv[2] ?? '/opt/runtime');
  const agent = process.env.PI_CODING_AGENT_DIR ?? '/data/pi';
  const root = join(runtime, 'node_modules/@earendil-works/pi-coding-agent');
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  const { ModelRuntime } = await import(pathToFileURL(join(root, pkg.exports['.'].import)));
  const models = await ModelRuntime.create({ authPath: join(agent, 'auth.json'),
    modelsPath: join(agent, 'models.json'), allowModelNetwork: false, refreshOnCreate: false });
  const count = models.getModels().filter((model) => models.hasConfiguredAuth(model.provider)).length;
  console.log(JSON.stringify({ state: count ? 'ready' : 'pending', count,
    help: count ? 'Model credentials are configured. A successful chat verifies provider access.' : 'Configure a provider in Pi Web settings/login. Then refresh this checklist.' }));
} catch {
  console.log(JSON.stringify({ state: 'unknown', help: 'Could not inspect model configuration. Check Pi Web settings; custom extension providers may only be visible in a session.' }));
}
