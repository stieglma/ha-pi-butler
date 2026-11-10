import { workflows, makePrompt, sessionUrl } from './starter-model.mjs';
const byId = (id) => document.getElementById(id);
const base = new URL('../../', window.location.href);
let entities = [];
let busy = false;
let session;
async function api(path, body) {
  const response = await fetch(new URL(path, base), { cache: 'no-store', ...(body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed. Please retry.');
  return result;
}
function update() {
  const kind = byId('workflow').value;
  const workflow = workflows[kind];
  byId('workflow-help').textContent = workflow.help;
  byId('target-fields').hidden = kind === 'health';
  byId('target').required = kind !== 'health';
  document.querySelector('label[for="target"]').textContent = workflow.automation ? 'Automation' : 'Entity or automation';
  byId('incident-fields').hidden = !workflow.incident;
  byId('behavior').required = !!workflow.incident;
  document.querySelector('label[for="behavior"]').textContent = kind === 'missing' ? 'What did you expect to happen?' : 'What happened?';
  byId('targets').replaceChildren(...entities.filter((entity) => !workflow.automation || entity.id.startsWith('automation.')).map((entity) => {
    const option = document.createElement('option');
    option.value = `${entity.name} (${entity.id})`;
    return option;
  }));
}
async function loadCatalog() {
  byId('reload-catalog').disabled = true;
  try {
    const catalog = await api('butler/starters/catalog');
    entities = catalog.entities;
    update();
    byId('catalog-status').textContent = 'Search by name, or enter an entity ID directly.';
  } catch (error) {
    byId('catalog-status').textContent = `${error.message} You can still enter an entity ID directly.`;
  } finally { byId('reload-catalog').disabled = false; }
}
byId('workflow').addEventListener('change', () => { byId('target').value = ''; update(); });
byId('reload-catalog').addEventListener('click', loadCatalog);
byId('starter-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || session) return;
  let text;
  try {
    const selected = entities.find((entity) => `${entity.name} (${entity.id})` === byId('target').value);
    text = makePrompt(byId('workflow').value, { target: selected?.id || byId('target').value.trim(), behavior: byId('behavior').value, when: byId('when').value });
  } catch (error) { byId('launch-status').textContent = error.message; return; }
  busy = true;
  byId('launch').disabled = true;
  byId('launch-status').textContent = 'Opening a new conversation…';
  try {
    const projects = await api('api/projects');
    const project = projects.find((item) => item.path.replace(/\/$/, '') === '/data/workspaces/scratch');
    if (!project) throw new Error('The Home Assistant project is not ready. Check Setup & house notes, then retry.');
    const resolution = await api(`api/projects/${encodeURIComponent(project.id)}/workspaces`);
    const workspace = resolution.workspaces.find((item) => item.path.replace(/\/$/, '') === project.path.replace(/\/$/, ''));
    if (!workspace) throw new Error('The Home Assistant workspace is not ready. Check Setup & house notes, then retry.');
    const created = await api('api/machines/local/sessions', { cwd: workspace.path });
    if (!created.id) throw new Error('Pi Web did not return a conversation ID. Check Pi Web before retrying.');
    session = created;
    const url = sessionUrl(base, project.id, workspace.id, created.id);
    byId('session-link').href = url.href;
    byId('session-link').hidden = false;
    byId('launch-status').textContent = 'Starting the investigation…';
    const available = await api(`api/machines/local/sessions/${encodeURIComponent(created.id)}/commands?${new URLSearchParams({ cwd: workspace.path })}`);
    if (!available.some((command) => command.name === text.split(' ')[0].slice(1))) {
      throw new Error('The required house skill is unavailable. Inspect the house plugin in Pi Web; it may have been disabled or removed.');
    }
    await api(`api/machines/local/sessions/${encodeURIComponent(created.id)}/prompt`, { cwd: workspace.path, text });
    window.location.assign(url.href);
  } catch (error) {
    byId('launch-status').textContent = session
      ? `${error.message} The conversation was created. Open it to check whether the request arrived; if needed, send the prepared request below.`
      : error.message;
    if (session) {
      const draft = document.createElement('textarea');
      draft.readOnly = true;
      draft.rows = 8;
      draft.value = text;
      draft.setAttribute('aria-label', 'Prepared investigation request');
      byId('launch-status').after(draft);
    }
  } finally {
    busy = false;
    byId('launch').disabled = !!session;
  }
});
update();
loadCatalog();
