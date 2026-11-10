import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { workflows, makePrompt, sessionUrl } from '../src/butler/web/starter-model.mjs';

const source = (await readFile(new URL('../src/butler/web/starters.js', import.meta.url), 'utf8')).replace(/^import .*;\n/, '');
const prefix = 'https://ha.example/api/hassio_ingress/example/';
const entities = [{ id: 'automation.evening', name: 'Evening' }, { id: 'sensor.motion', name: '<img src=x onerror=alert(1)>' }];
async function browser({ kind = 'debug', failCatalog = false, failPrompt = false, missingSkill = false, missingProject = false } = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, { value: '', hidden: false, disabled: false, textContent: '', listeners: {}, children: [],
      addEventListener(event, fn) { this.listeners[event] = fn; },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}, after(child) { this.children.push(child); },
    });
    return elements.get(id);
  }
  element('workflow').value = kind;
  const requests = [];
  const navigations = [];
  let creates = 0;
  const fetch = async (url, options) => {
    const path = url.href.slice(prefix.length);
    assert.ok(url.href.startsWith(prefix), 'every request retains the HA ingress prefix');
    const body = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ path, body });
    let result;
    let status = 200;
    if (path === 'butler/starters/catalog') {
      result = failCatalog ? { error: 'HA unavailable' } : { entities };
      if (failCatalog) status = 502;
    } else if (path === 'api/projects') result = missingProject ? [] : [{ id: 'home', path: '/data/workspaces/scratch' }];
    else if (path === 'api/projects/home/workspaces') result = { workspaces: [{ id: 'main', path: '/data/workspaces/scratch' }] };
    else if (path === 'api/machines/local/sessions') { creates++; result = { id: 'new-session' }; }
    else if (path.startsWith('api/machines/local/sessions/new-session/commands?')) {
      assert.equal(new URL(url).searchParams.get('cwd'), '/data/workspaces/scratch');
      result = missingSkill ? [] : Object.values(workflows).map((workflow) => ({ name: `skill:${workflow.skill}` }));
    } else if (path === 'api/machines/local/sessions/new-session/prompt') {
      result = failPrompt ? { error: 'Submission interrupted' } : { accepted: true };
      if (failPrompt) status = 502;
    } else throw new Error(`Unexpected request: ${path}`);
    return { ok: status === 200, json: async () => result };
  };
  runInNewContext(source, { workflows, makePrompt, sessionUrl, URL, URLSearchParams, fetch,
    document: { getElementById: element, querySelector: element, createElement: () => element(`created-${elements.size}`) },
    window: { location: { href: `${prefix}butler/starters/`, assign: (url) => navigations.push(url) } },
  });
  await new Promise(setImmediate);
  return { element, requests, navigations, creates: () => creates,
    submit: () => element('starter-form').listeners.submit({ preventDefault() {} }) };
}

test('all starters launch their existing skill in a new scratch conversation under the ingress prefix', async () => {
  for (const [kind, workflow] of Object.entries(workflows)) {
    const page = await browser({ kind });
    page.element('target').value = kind === 'unexpected' ? `${entities[1].name} (${entities[1].id})` : 'automation.evening';
    page.element('behavior').value = 'The light should turn on.';
    page.element('when').value = '2026-11-10T18:30';
    await page.submit();
    assert.equal(page.creates(), 1);
    const sent = page.requests.find((request) => request.path.endsWith('/prompt')).body;
    assert.equal(sent.cwd, '/data/workspaces/scratch');
    // A literal space separates skill name and args in the pinned SDK.
    assert.equal(sent.text.split(' ')[0], `/skill:${workflow.skill}`);
    assert.equal(page.navigations.length, 1);
    const url = new URL(page.navigations[0]);
    assert.equal(url.pathname, '/api/hassio_ingress/example/');
    assert.equal(url.searchParams.get('project'), 'home');
    assert.equal(url.searchParams.get('workspace'), 'main');
    assert.equal(url.searchParams.get('session'), 'new-session');
    if (workflow.incident) {
      const context = JSON.parse(sent.text.slice(sent.text.indexOf('{')));
      assert.ok(context.approximate_incident_time.endsWith('Z'));
      assert.ok(context.browser_timezone);
    }
    await page.submit();
    assert.equal(page.creates(), 1, 'repeat submits do not create another conversation');
  }
});
test('failed submission retains session and prepared request without sending again', async () => {
  const page = await browser({ failPrompt: true });
  page.element('target').value = 'automation.evening';
  await page.submit();
  assert.equal(page.navigations.length, 0);
  assert.equal(page.element('session-link').hidden, false);
  assert.match(page.element('launch-status').textContent, /Submission interrupted/);
  assert.match(page.element('launch-status').children[0].value, /^\/skill:house-debug-automation /);
  await page.submit();
  assert.equal(page.creates(), 1);
  assert.equal(page.requests.filter((request) => request.path.endsWith('/prompt')).length, 1);
});
test('disabled skills are reported without sending an unexpanded request', async () => {
  const page = await browser({ missingSkill: true });
  page.element('target').value = 'automation.evening';
  await page.submit();
  assert.match(page.element('launch-status').textContent, /skill is unavailable/);
  assert.equal(page.requests.some((request) => request.path.endsWith('/prompt')), false);
  assert.equal(page.element('session-link').hidden, false);
});
test('catalog failure permits explicit IDs and health checks', async () => {
  for (const kind of ['health', 'debug']) {
    const page = await browser({ kind, failCatalog: true });
    page.element('target').value = 'automation.evening';
    assert.match(page.element('catalog-status').textContent, /enter an entity ID/);
    await page.submit();
    assert.equal(page.navigations.length, 1);
  }
});
test('missing project and invalid inputs do not start conversations', async () => {
  const page = await browser({ missingProject: true });
  page.element('target').value = 'automation.evening';
  await page.submit();
  assert.equal(page.creates(), 0);
  assert.equal(page.element('launch').disabled, false);
  assert.throws(() => makePrompt('debug', { target: 'sensor.motion' }), /automation/);
  assert.throws(() => makePrompt('unexpected', { target: 'light.kitchen' }), /Describe/);
  assert.throws(() => makePrompt('explain', { target: 'unknown name' }), /entity/);
});
