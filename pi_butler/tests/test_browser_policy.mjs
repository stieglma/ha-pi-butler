import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanPolicy, matchingEntities, policyYaml, validateDraft} from '../src/butler/web/policy-model.mjs';
const entities = [
  {id:'light.office', label_ids:['writable']},
  {id:'light.nursery', label_ids:['writable']},
  {id:'switch.fan', label_ids:[]},
  {id:'automation.evening', label_ids:['writable']},
];
test('rule preview ANDs selectors and exclusions override matches',()=>{
  const rule={capability:'control',entity_ids:[],domains:['light'],label_ids:['writable']};
  assert.deepEqual(matchingEntities(rule, entities, ['light.nursery']).map(e=>e.id),['light.office']);
  rule.entity_ids=['switch.fan'];
  assert.deepEqual(matchingEntities(rule,entities),[]);
});
test('empty rules cannot export or preview an accidental allow-all grant',()=>{
  const rule={capability:'control',entity_ids:[],domains:[],label_ids:[]};
  assert.equal(matchingEntities(rule,entities).length,0);
  assert.throws(()=>policyYaml({enabled:true,allow:[rule],deny_entity_ids:[]}));
});
test('trigger preview does not turn other controls into automation permission',()=>{
  const rule={capability:'trigger_automation',entity_ids:[],domains:[],label_ids:['writable']};
  assert.deepEqual(matchingEntities(rule,entities).map(e=>e.id),['automation.evening']);
});
test('draft cloning preserves the active policy and unknown configured IDs',()=>{
  const active={enabled:false,allow:[{capability:'control',entity_ids:['light.removed']}],deny_entity_ids:[]};
  const draft=cleanPolicy(active);draft.enabled=true;draft.allow[0].domains.push('light');
  assert.equal(active.enabled,false);
  assert.equal(active.allow[0].domains,undefined);
  assert.deepEqual(draft.allow[0].entity_ids,['light.removed']);
  assert.match(policyYaml(draft),/enabled: true/);
});
test('default-deny export is explicit and stable',()=>{
  assert.equal(policyYaml(cleanPolicy({enabled:false,allow:[]})), 'ha_access:\n  enabled: false\n  allow: []\n  deny_entity_ids: []\n');
});
