// Run the readiness probe against the pinned SDK with synthetic credentials only.
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
const runtime = resolve(process.argv[2] ?? '/opt/runtime');
const probe = resolve(process.argv[3] ?? join(runtime, 'butler/model-status.mjs'));
const temporary = await mkdtemp(join(tmpdir(), 'butler-model-status-'));
const secret = 'synthetic-model-status-test-secret';
try {
  // Fail closed if the probe tries any HTTP request, including OAuth refresh.
  const guard = join(temporary, 'no-network.mjs');
  await writeFile(guard, `import http from 'node:http'; import https from 'node:https';
const denied = () => { throw new Error('Network forbidden in readiness check'); };
globalThis.fetch = denied; http.request = denied; http.get = denied; https.request = denied; https.get = denied;`);
  const run = async (credentials) => {
    await writeFile(join(temporary, 'auth.json'), JSON.stringify(credentials), { mode: 0o600 });
    const result = spawnSync(process.execPath, ['--import', guard, probe, runtime], {
      cwd: temporary, timeout: 15000, encoding: 'utf8',
      env: { PATH: process.env.PATH, HOME: temporary, PI_CODING_AGENT_DIR: temporary,
        PI_OFFLINE: 'true', PI_SKIP_VERSION_CHECK: 'true' },
    });
    assert.equal(result.status, 0, 'Readiness probe must finish successfully');
    assert.equal(result.stderr, '', 'Probe must not expose SDK diagnostics');
    assert.ok(!result.stdout.includes(secret), 'Probe must not expose credentials');
    return JSON.parse(result.stdout);
  };
  assert.equal((await run({})).state, 'pending');
  for (const provider of ['anthropic', 'openai-codex']) {
    // An expired access token is still configured; readiness must not refresh it.
    const subscription = await run({ [provider]: { type: 'oauth', access: secret,
      refresh: secret, expires: 1 } });
    assert.equal(subscription.state, 'ready', `${provider} subscription must be detected`);
    assert.ok(subscription.count > 0);
  }
  assert.equal((await run({ anthropic: { type: 'api_key', key: secret } })).state, 'ready');
  console.log('Model readiness detects subscriptions and API keys locally without leaking credentials.');
} finally {
  await rm(temporary, { recursive: true, force: true });
}
