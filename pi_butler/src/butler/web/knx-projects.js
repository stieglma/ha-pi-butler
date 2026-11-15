const $ = id => document.getElementById(id);
let state, grants = [], busy = false;
let savedGrants = '[]', draftVersion;
const policyDirty = () => JSON.stringify(grants) !== savedGrants;
function policyStatus() {
  $('policy-status').textContent = policyDirty() ? (state.policy_version !== draftVersion ? 'Unsaved changes. Permissions changed elsewhere; copy your edits and reload permissions before saving.' : 'Unsaved permission changes.') : '';
}
function node(tag, text) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; return e; }
async function api(action, body) {
  const response = await fetch(`../butler-api/${action}`, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Butler-Settings':'1'}, body:JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'KNX request failed');
  return result;
}
async function run(work, {reloadPolicy = false, savePolicy = false} = {}) {
  if (busy) return;
  busy = true; $('message').textContent = 'Working…';
  document.querySelectorAll('button').forEach(b => {b.disabled = true;});
  if (savePolicy || reloadPolicy) document.querySelectorAll('#grants input').forEach(input => {input.disabled = true;});
  try { const result = await work(); await refresh(reloadPolicy); $('message').textContent = result || 'Done.'; }
  catch (error) { $('message').textContent = error.message; }
  finally {
    busy = false; document.querySelectorAll('button').forEach(b => {b.disabled = false;});
    if (savePolicy || reloadPolicy) document.querySelectorAll('#grants input').forEach(input => {input.disabled = false;});
  }
}
function renderGrants() {
  $('grants').replaceChildren();
  grants.forEach((grant,index) => {
    const row = node('fieldset'); row.append(node('legend', `Project ${grant.project_guid}`));
    for (const capability of ['add','change','delete']) {
      const label = node('label'), box = node('input'); box.type='checkbox'; box.checked=grant.capabilities.includes(capability);
      box.addEventListener('change', () => { grant.capabilities = [...new Set(box.checked ? [...grant.capabilities,capability] : grant.capabilities.filter(c => c!==capability))]; policyStatus(); });
      label.append(box, document.createTextNode(` ${capability} `)); row.append(label);
    }
    const label = node('label','Device node IDs (comma separated; empty means whole project)'), input=node('input');
    input.value=grant.node_ids.join(', '); input.setAttribute('aria-label','Device node IDs');
    input.addEventListener('input', () => {grant.node_ids=input.value.trim() ? input.value.split(',').map(v=>Number(v.trim())) : [];policyStatus();});
    const remove=node('button','Remove grant'); remove.addEventListener('click',()=>{grants.splice(index,1);renderGrants();policyStatus();});
    row.append(label,input,remove); $('grants').append(row);
  });
}
async function refresh(reloadPolicy = false) {
  const next = await api('status');
  if (!state || reloadPolicy || !policyDirty()) {
    grants=structuredClone(next.policy.grants); savedGrants=JSON.stringify(grants);
    draftVersion=next.policy_version; renderGrants();
  }
  state = next; policyStatus();
  $('active').textContent = state.active ? `${state.active.name} · ${state.active.guid}` : 'No project open. Open a saved project in the editor or import from the repository.';
  $('saved').textContent = state.error || (state.dirty ? 'Changes have no complete checkpoint/export yet.' : state.active ? 'Current project state has a complete checkpoint.' : '');
  $('checkpoint-storage').textContent = state.storage ? `Checkpoint storage: ${(state.storage.bytes / 1048576).toFixed(1)} MiB of ${(state.storage.budget_bytes / 1048576).toFixed(0)} MiB. Up to ${state.storage.max_checkpoints} revisions for ${state.storage.retention_days} days; the newest recovery point is kept.` : '';
  $('history').replaceChildren();
  for (const checkpoint of state.checkpoints) {
    const row=node('article'); row.append(node('h3',checkpoint.comment || 'Checkpoint'),node('p',`${checkpoint.created} · ${checkpoint.source}${checkpoint.actor ? ` · ${checkpoint.actor}` : ''}`));
    for (const warning of checkpoint.warnings || []) row.append(node('p',warning));
    for (const kind of ['xknx','knxproj','json']) {const link=node('a',`Download ${kind} `);link.href=`../butler-api/download?id=${encodeURIComponent(checkpoint.id)}&kind=${kind}`;row.append(link);}
    const restore=node('button','Restore this revision'); restore.addEventListener('click',()=>{
      if (confirm('Restore this revision? The current project will be checkpointed first. Devices on the bus are unchanged.')) run(async()=>{await api('restore',{id:checkpoint.id,state:state.active.state});return 'Project restored and checkpointed.';});
    });
    const deliver=node('button','Deliver this checkpoint to Git'); deliver.addEventListener('click',()=>{
      if (confirm('Commit and deliver these three checkpoint files using your configured Git workflow? This may trigger the separate HA Git deployment.')) run(async()=>{const result=await api('deliver',{id:checkpoint.id});return `Delivered ${result.commit}${result.url ? ` · ${result.url}` : ` · ${result.branch}`}`;});
    });
    row.append(restore,deliver); $('history').append(row);
  }
}
$('refresh').addEventListener('click',()=>run(async()=> 'Project status refreshed.'));
$('import').addEventListener('click',()=>{if(confirm('Import the configured repository project as a separate working copy? Your current project will be saved first.')) run(async()=>{const r=await api('import',{});return r.checkpoint_error || 'Repository project imported. Open the editor to inspect it.';});});
$('checkpoint').addEventListener('click',()=>run(async()=>{await api('checkpoint',{comment:$('comment').value});return 'Checkpoint and exchange export saved.';}));
$('add-grant').addEventListener('click',()=>{if(!state?.active)return;grants.push({project_guid:state.active.guid,capabilities:['change'],node_ids:[]});renderGrants();policyStatus();});
$('reload-policy').addEventListener('click',()=>{
  if (policyDirty() && !confirm('Discard your unsaved permission changes?')) return;
  return run(async()=> 'Permissions reloaded.', {reloadPolicy:true});
});
$('save-policy').addEventListener('click',()=>run(async()=>{
  const result=await api('policy',{grants,version:draftVersion});
  savedGrants=JSON.stringify(result.policy.grants); grants=structuredClone(result.policy.grants);
  draftVersion=result.policy_version; return 'Assistant permissions saved.';
}, {savePolicy:true}));
window.addEventListener('beforeunload', event=>{if(policyDirty()){event.preventDefault();event.returnValue='';}});
refresh().then(()=>{$('message').textContent='Ready.';}).catch(error=>{$('message').textContent=error.message;});
