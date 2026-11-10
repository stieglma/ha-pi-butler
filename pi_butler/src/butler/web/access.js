import { categories, cleanPolicy, matchingEntities, policyYaml, validateDraft } from './policy-model.mjs';
const $ = id => document.getElementById(id);
let catalog, draft;
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function picker(title, options, selected, changed) {
  const box = node('div', undefined, 'picker');
  box.append(node('label', title));
  const details = node('details');
  const summary = node('summary');
  const body = node('div', undefined, 'picker-body');
  const search = node('input'); search.type = 'search'; search.placeholder = `Search ${title.toLowerCase()}…`; search.setAttribute('aria-label', `Search ${title}`);
  const choices = node('div', undefined, 'choices');
  const count = node('p', undefined, 'picker-count');
  const selectedValues = new Set(selected);
  const known = new Set(options.map(option => option.id));
  const all = [...options, ...selected.filter(id => !known.has(id)).map(id => ({id, name: 'Currently configured; not found in HA'}))];
  function render() {
    summary.textContent = selectedValues.size ? `${selectedValues.size} selected · change` : `Choose ${title.toLowerCase()}`;
    const term = search.value.trim().toLowerCase();
    const filtered = all.filter(option => `${option.id} ${option.name}`.toLowerCase().includes(term));
    const sorted = [...filtered].sort((a,b) => Number(selectedValues.has(b.id))-Number(selectedValues.has(a.id)));
    choices.replaceChildren();
    for (const option of sorted.slice(0,100)) {
      const row = node('label', undefined, 'choice');
      const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = selectedValues.has(option.id);
      const label = node('span', option.name || option.id);
      if (option.name && option.name !== option.id) label.append(node('small', option.id));
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) selectedValues.add(option.id); else selectedValues.delete(option.id);
        summary.textContent = selectedValues.size ? `${selectedValues.size} selected · change` : `Choose ${title.toLowerCase()}`;
        changed([...selectedValues]);
      });
      row.append(checkbox,label); choices.append(row);
    }
    count.textContent = filtered.length > 100 ? `Showing 100 of ${filtered.length}. Search to narrow the list.` : `${filtered.length} available`;
  }
  search.addEventListener('input',render);
  body.append(search,choices,count); details.append(summary,body); box.append(details);render();return box;
}
function optionLists() {
  return {entity_ids: catalog.entities, domains: catalog.domains.map(id => ({id,name:id})), label_ids: catalog.labels};
}
function renderRules() {
  $('rules').replaceChildren();
  $('no-rules').hidden = draft.allow.length > 0;
  const options = optionLists();
  draft.allow.forEach((rule,index) => {
    const card=node('article',undefined,'rule'), heading=node('div',undefined,'rule-heading');
    const title=node('div'); title.append(node('h3',`Rule ${index+1}`));
    const capability=node('select'); capability.setAttribute('aria-label',`Rule ${index+1} capability`);
    for (const [value,label] of [['control','Control entities'],['trigger_automation','Manually trigger automations']]) {
      const option=node('option',label);option.value=value;capability.append(option);
    }
    capability.value=rule.capability;capability.addEventListener('change',()=>{rule.capability=capability.value;updateOutput();});
    title.append(capability);const remove=node('button','Remove','remove');remove.type='button';remove.setAttribute('aria-label',`Remove rule ${index+1}`);
    remove.addEventListener('click',()=>{draft.allow.splice(index,1);renderRules();updateOutput();});heading.append(title,remove);
    const picks=node('div',undefined,'pickers');
    for (const [key,label] of [['entity_ids','Entities'],['domains','Domains'],['label_ids','Direct labels']]) {
      picks.append(picker(`Rule ${index+1} · ${label}`,options[key],rule[key],values=>{rule[key]=values;updateOutput();}));
    }
    const preview=node('p',undefined,'preview');preview.id=`preview-${index}`;
    card.append(heading,picks,preview);$('rules').append(card);
  });
}
function updateOutput() {
  const errors=validateDraft(draft);
  const granted=new Set();
  draft.allow.forEach((rule,index)=>{
    const matches=matchingEntities(rule,catalog.entities,draft.deny_entity_ids);
    matches.forEach(entity=>granted.add(entity.id));
    const preview=$(`preview-${index}`);
    if(preview) preview.textContent=categories.some(key=>rule[key].length) ? `${matches.length} currently matching entities after exclusions: ${matches.slice(0,8).map(entity=>entity.id).join(', ')}${matches.length>8?'…':''}` : 'Choose at least one filter. An empty rule cannot be applied.';
  });
  $('effective').textContent=draft.enabled ? `Draft: granted writes enabled. ${granted.size} currently matching entities; only supported actions and the selected capabilities are allowed.` : 'Draft: writes disabled. No entities can be controlled, even if a rule matches. Reads remain available.';
  $('draft-errors').hidden=errors.length===0;$('draft-errors').textContent=errors.join('\n');
  $('copy').disabled=errors.length>0;$('yaml').value=errors.length?'':policyYaml(draft);$('copied').textContent='';
}
async function load() {
  $('loading').hidden=false;$('load-error').hidden=true;$('retry').hidden=true;$('editor').hidden=true;
  try {
    const reply=await fetch('catalog',{cache:'no-store'});const data=await reply.json();
    if(!reply.ok)throw new Error(data.error||'Unable to load Home Assistant choices.');
    catalog=data;draft=cleanPolicy(catalog.policy);$('enabled').checked=draft.enabled;
    $('version').textContent=`Active policy version: ${catalog.version}.`;
    $('exclusions').replaceChildren(picker('Excluded entities',catalog.entities,draft.deny_entity_ids,values=>{draft.deny_entity_ids=values;updateOutput();}));
    renderRules();updateOutput();$('editor').hidden=false;
  } catch(error) {$('load-error').textContent=error.message;$('load-error').hidden=false;$('retry').hidden=false;}
  finally {$('loading').hidden=true;}
}
$('enabled').addEventListener('change',()=>{draft.enabled=$('enabled').checked;updateOutput();});
$('add-rule').addEventListener('click',()=>{draft.allow.push({capability:'control',entity_ids:[],domains:[],label_ids:[]});renderRules();updateOutput();});
$('copy').addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText($('yaml').value);$('copied').textContent='Copied. Save the section in HA and restart to apply.';}
  catch { $('yaml').focus();$('yaml').select();$('copied').textContent='Select and copy this YAML, then save it in HA.'; }
});
$('retry').addEventListener('click',load);load();
