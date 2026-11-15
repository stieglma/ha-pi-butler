import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const turn = () => new Promise(setImmediate);
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const reply = (value, ok = true) => ({ok, json: async () => structuredClone(value)});
async function page(script, fetch, confirm = () => true) {
  const elements = new Map();
  const buttons = new Set(['refresh','import','checkpoint','add-grant','save-policy','reload-policy','reload','save']);
  const create = tag => ({tag, value:'', disabled:false, textContent:'', children:[], listeners:{}, dataset:{},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; }, setAttribute() {},
  });
  const element = id => {
    if (!elements.has(id)) elements.set(id, create(buttons.has(id) ? 'button' : id === 'memory' ? 'textarea' : 'div'));
    return elements.get(id);
  };
  const descendants = item => [item, ...item.children.flatMap(descendants)];
  const window = {listeners:{}, confirm, addEventListener(event, fn) { this.listeners[event] = fn; }};
  const document = {getElementById:element, createElement:create, createTextNode: text => ({text, children:[]}),
    querySelectorAll(selector) {
      const nodes = selector === '#grants input' ? descendants(element('grants')) : [...elements.values()].flatMap(descendants);
      return nodes.filter(n => n.tag === (selector === 'button' ? 'button' : 'input'));
    }};
  const source = await readFile(new URL(`../src/butler/web/${script}`, import.meta.url), 'utf8');
  runInNewContext(source, {document, window, fetch, confirm, structuredClone});
  await turn();
  return {element, window, descendants, click: id => element(id).listeners.click()};
}

const grant = {project_guid:'guid', capabilities:['change'], node_ids:[]};
const initial = () => ({policy:{grants:[structuredClone(grant)]}, policy_version:'v1',
  active:{guid:'guid', name:'House', state:'state'}, checkpoints:[], dirty:false});

test('KNX checkpoint refresh preserves an unsaved revocation and saves it with its draft version', async () => {
  let status = initial();
  let saved;
  const ui = await page('knx-projects.js', async (url, options) => {
    const action = url.split('/').at(-1);
    if (action === 'status') return reply(status);
    if (action === 'checkpoint') return reply({});
    if (action === 'policy') {
      saved = JSON.parse(options.body);
      status = {...status, policy:{grants:saved.grants}, policy_version:'v2'};
      return reply({policy:status.policy, policy_version:'v2'});
    }
    throw new Error(action);
  });
  ui.descendants(ui.element('grants')).find(n => n.tag === 'button').listeners.click();
  await ui.click('checkpoint');
  assert.equal(ui.element('grants').children.length, 0);
  assert.match(ui.element('policy-status').textContent, /Unsaved/);
  await ui.click('save-policy');
  assert.deepEqual(saved, {grants:[], version:'v1'});
  assert.equal(ui.element('policy-status').textContent, '');
});

test('KNX edits entered during an unrelated operation survive its completion', async () => {
  const pending = deferred();
  const ui = await page('knx-projects.js', async url => url.endsWith('/status') ? reply(initial()) : pending.promise);
  const operation = ui.click('checkpoint');
  const input = ui.descendants(ui.element('grants')).find(n => n.tag === 'input' && n.type !== 'checkbox');
  input.value = '7'; input.listeners.input();
  pending.resolve(reply({}));
  await operation;
  assert.equal(ui.descendants(ui.element('grants')).find(n => n.tag === 'input' && n.type !== 'checkbox').value, '7');
  assert.match(ui.element('policy-status').textContent, /Unsaved/);
});

test('KNX external policy changes keep the draft stale until explicit confirmed reload', async () => {
  let status = initial();
  let saved;
  let allowDiscard = false;
  const ui = await page('knx-projects.js', async (url, options) => {
    if (url.endsWith('/status')) return reply(status);
    saved = JSON.parse(options.body);
    return reply({error:'KNX permissions changed. Refresh before saving.'}, false);
  }, () => allowDiscard);
  ui.descendants(ui.element('grants')).find(n => n.tag === 'button').listeners.click();
  status = {...status, policy_version:'external'};
  await ui.click('refresh');
  assert.match(ui.element('policy-status').textContent, /changed elsewhere/);
  await ui.click('save-policy');
  assert.equal(saved.version, 'v1');
  assert.equal(ui.element('grants').children.length, 0);
  await ui.click('reload-policy');
  assert.equal(ui.element('grants').children.length, 0);
  allowDiscard = true;
  await ui.click('reload-policy');
  assert.equal(ui.element('grants').children.length, 1);
});

test('KNX permission inputs are disabled while a policy save is pending and recover on failure', async () => {
  const pending = deferred();
  const ui = await page('knx-projects.js', async url => url.endsWith('/status') ? reply(initial()) : pending.promise);
  const inputs = ui.descendants(ui.element('grants')).filter(n => n.tag === 'input');
  const operation = ui.click('save-policy');
  assert.ok(inputs.every(input => input.disabled));
  pending.resolve(reply({error:'Save failed'}, false));
  await operation;
  assert.ok(inputs.every(input => !input.disabled));
  assert.match(ui.element('message').textContent, /Save failed/);
});

test('KNX permission reload disables inputs through completion and restores them on failure', async () => {
  for (const ok of [true, false]) {
    const pending = deferred();
    let loads = 0;
    const ui = await page('knx-projects.js', async () => ++loads === 1 ? reply(initial()) : pending.promise);
    const inputs = ui.descendants(ui.element('grants')).filter(n => n.tag === 'input');
    const scope = inputs.find(n => n.type !== 'checkbox');
    scope.value = '7'; scope.listeners.input();
    const operation = ui.click('reload-policy');
    assert.ok(inputs.every(input => input.disabled));
    pending.resolve(ok ? reply(initial()) : reply({error:'Reload failed'}, false));
    await operation;
    const currentInputs = ui.descendants(ui.element('grants')).filter(n => n.tag === 'input');
    assert.ok(currentInputs.every(input => !input.disabled));
    assert.equal(currentInputs.find(n => n.type !== 'checkbox').value, ok ? '' : '7');
  }
});

test('notes typed before initial load keep the server version and baseline for saving and unload warning', async () => {
  const pending = deferred();
  let saved;
  const ui = await page('setup.js', async (url, options) => {
    if (url === 'status') return reply({checks:{}});
    if (options.method === 'POST') {
      saved = JSON.parse(options.body);
      return reply({text:saved.text, version:'v2'});
    }
    return pending.promise;
  });
  ui.element('memory').value = 'Draft before first load';
  ui.element('memory').listeners.input();
  pending.resolve(reply({text:'Server baseline', version:'v1'}));
  await turn();
  assert.equal(ui.element('memory').value, 'Draft before first load');
  assert.equal(ui.element('memory').disabled, false);
  assert.equal(ui.element('save').disabled, false);
  let prevented = false;
  ui.window.listeners.beforeunload({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  await ui.click('save');
  assert.deepEqual(saved, {text:'Draft before first load', version:'v1'});
});

test('notes typed while Reload is pending are preserved and remain saveable', async () => {
  const pending = deferred();
  let loads = 0, saved;
  const ui = await page('setup.js', async (url, options) => {
    if (url === 'status') return reply({checks:{}});
    if (options.method === 'POST') { saved = JSON.parse(options.body); return reply({text:saved.text, version:'v2'}); }
    if (++loads === 1) return reply({text:'Old notes', version:'v1'});
    return pending.promise;
  });
  const operation = ui.click('reload');
  ui.element('memory').value = 'Newly typed notes';
  ui.element('memory').listeners.input();
  assert.equal(ui.element('save').disabled, true, 'Save waits for the in-flight reload');
  pending.resolve(reply({text:'Old notes', version:'v1'}));
  await operation;
  assert.equal(ui.element('memory').value, 'Newly typed notes');
  assert.equal(ui.element('save').disabled, false);
  await ui.click('save');
  assert.deepEqual(saved, {text:'Newly typed notes', version:'v1'});
});

test('confirmed notes reload replaces preexisting edits when no new edits arrive', async () => {
  const ui = await page('setup.js', async url => url === 'status' ? reply({checks:{}}) : reply({text:'Server notes', version:'v1'}));
  ui.element('memory').value = 'Discard me';
  ui.element('memory').listeners.input();
  await ui.click('reload');
  assert.equal(ui.element('memory').value, 'Server notes');
  assert.equal(ui.element('save').disabled, true);
});
