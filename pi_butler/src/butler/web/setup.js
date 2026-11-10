'use strict';
const byId = (id) => document.getElementById(id);
const labels = { model: 'Model configuration', ha: 'Home Assistant connection', scratch: 'Investigation project', repository: 'Repository setup', git: 'Git authentication', repository_project: 'Repository project' };
const states = { ready: 'Ready', pending: 'Needs attention', not_configured: 'Optional', optional: 'Optional', unknown: 'Check manually' };
let version;
let savedText = '';
let saving = false;
async function api(path, options) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Request failed. Please retry.');
  return value;
}
async function refresh() {
  byId('refresh').disabled = true;
  try {
    const result = await api('status');
    byId('checks').replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const check = result.checks?.[key] || { state: 'pending', help: 'Waiting for the first setup check.' };
      const item = document.createElement('li');
      item.dataset.state = check.state;
      const title = document.createElement('strong');
      title.textContent = `${label} · ${states[check.state] || 'Needs attention'}`;
      const detail = document.createElement('p');
      detail.textContent = check.help;
      item.append(title, detail);
      byId('checks').append(item);
    }
    byId('check-status').textContent = result.error || (result.checked_at ? `Last checked ${new Date(result.checked_at).toLocaleString()}` : 'Checks are starting. Refresh shortly.');
  } catch (error) { byId('check-status').textContent = error.message; }
  finally { byId('refresh').disabled = false; }
}
async function loadMemory() {
  if (byId('memory').value !== savedText && version && !window.confirm('Discard your unsaved note changes?')) return;
  byId('reload').disabled = true;
  try {
    const result = await api('memory');
    byId('memory').value = result.text;
    version = result.version;
    savedText = result.text;
    byId('memory').disabled = false;
    byId('memory-status').textContent = 'Notes loaded.';
    byId('save').disabled = true;
  } catch (error) { byId('memory-status').textContent = error.message; }
  finally { byId('reload').disabled = false; }
}
byId('memory').addEventListener('input', () => {
  byId('save').disabled = saving || byId('memory').value === savedText;
  byId('memory-status').textContent = 'Unsaved changes.';
});
byId('save').addEventListener('click', async () => {
  saving = true;
  byId('save').disabled = true;
  byId('reload').disabled = true;
  const text = byId('memory').value;
  try {
    const result = await api('memory', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Butler-Settings': '1' }, body: JSON.stringify({ text, version }) });
    version = result.version;
    savedText = result.text;
    byId('memory-status').textContent = byId('memory').value === savedText ? 'Notes saved.' : 'Notes saved. You have newer unsaved edits.';
  } catch (error) { byId('memory-status').textContent = error.message; }
  finally { saving = false; byId('save').disabled = byId('memory').value === savedText; byId('reload').disabled = false; }
});
window.addEventListener('beforeunload', (event) => {
  if (version && byId('memory').value !== savedText) { event.preventDefault(); event.returnValue = ''; }
});
byId('refresh').addEventListener('click', refresh);
byId('reload').addEventListener('click', loadMemory);
refresh();
loadMemory();
