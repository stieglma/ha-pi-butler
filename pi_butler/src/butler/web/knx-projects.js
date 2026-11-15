const $ = id => document.getElementById(id);
let state, grants = [], busy = false;
function node(tag, text) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; return e; }
async function api(action, body) {
  const response = await fetch(`../butler-api/${action}`, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Butler-Settings':'1'}, body:JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'KNX request failed');
  return result;
}
async function run(work) {
  if (busy) return;
  busy = true; $('message').textContent = 'Working…';
  document.querySelectorAll('button').forEach(b => {b.disabled = true;});
  try { const result = await work(); await refresh(); $('message').textContent = result || 'Done.'; }
  catch (error) { $('message').textContent = error.message; }
  finally { busy = false; document.querySelectorAll('button').forEach(b => {b.disabled = false;}); }
}
function renderGrants() {
  $('grants').replaceChildren();
  grants.forEach((grant,index) => {
    const row = node('fieldset'); row.append(node('legend', `Project ${grant.project_guid}`));
    for (const capability of ['add','change','delete']) {
      const label = node('label'), box = node('input'); box.type='checkbox'; box.checked=grant.capabilities.includes(capability);
      box.addEventListener('change', () => { grant.capabilities = [...new Set(box.checked ? [...grant.capabilities,capability] : grant.capabilities.filter(c => c!==capability))]; });
      label.append(box, document.createTextNode(` ${capability} `)); row.append(label);
    }
    const label = node('label','Device node IDs (comma separated; empty means whole project)'), input=node('input');
    input.value=grant.node_ids.join(', '); input.setAttribute('aria-label','Device node IDs');
    input.addEventListener('input', () => {grant.node_ids=input.value.trim() ? input.value.split(',').map(v=>Number(v.trim())) : [];});
    const remove=node('button','Remove grant'); remove.addEventListener('click',()=>{grants.splice(index,1);renderGrants();});
    row.append(label,input,remove); $('grants').append(row);
  });
}
async function refresh() {
  state = await api('status'); grants=structuredClone(state.policy.grants); renderGrants();
  $('active').textContent = state.active ? `${state.active.name} · ${state.active.guid}` : 'No project open. Open a saved project in the editor or import from the repository.';
  $('saved').textContent = state.error || (state.dirty ? 'Changes have no complete checkpoint/export yet.' : state.active ? 'Current project state has a complete checkpoint.' : '');
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
$('add-grant').addEventListener('click',()=>{if(!state.active)return;grants.push({project_guid:state.active.guid,capabilities:['change'],node_ids:[]});renderGrants();});
$('save-policy').addEventListener('click',()=>run(async()=>{await api('policy',{grants,version:state.policy_version});return 'Assistant permissions saved.';}));
refresh().then(()=>{$('message').textContent='Ready.';}).catch(error=>{$('message').textContent=error.message;});
