// Browser-only draft/preview. The trusted service and HA options enforce policy.
export const categories = ['entity_ids', 'domains', 'label_ids'];
export function cleanPolicy(policy) {
  return { enabled: policy.enabled === true, allow: policy.allow.map(rule => ({
    capability: rule.capability, ...Object.fromEntries(categories.map(key => [key, [...(rule[key] ?? [])]])),
  })), deny_entity_ids: [...(policy.deny_entity_ids ?? [])] };
}
export function ruleMatches(rule, entity) {
  return rule.entity_ids.includes(entity.id) ||
    rule.domains.includes(entity.id.split('.')[0]) ||
    rule.label_ids.some(id => entity.label_ids.includes(id));
}
export function validateDraft(policy) {
  const errors = [];
  if (policy.allow.length > 256) errors.push('Use at most 256 grant rules.');
  policy.allow.forEach((rule, index) => {
    if (!['control', 'trigger_automation'].includes(rule.capability)) errors.push(`Rule ${index+1}: unknown capability.`);
    if (!categories.some(key => rule[key].length)) errors.push(`Rule ${index+1}: choose at least one entity, domain or label.`);
    for (const key of categories) if (rule[key].length > 256) errors.push(`Rule ${index+1}: ${key} has more than 256 values.`);
    for (const id of rule.entity_ids) if (!/^[a-z0-9_]+\.[a-z0-9_]+$/.test(id)) errors.push(`Rule ${index+1}: invalid entity ID "${id}". Use domain.object_id.`);
  });
  if (policy.deny_entity_ids.length > 256) errors.push('Use at most 256 excluded entities.');
  for (const id of policy.deny_entity_ids) if (!/^[a-z0-9_]+\.[a-z0-9_]+$/.test(id)) errors.push(`Invalid excluded entity ID "${id}". Use domain.object_id.`);
  return errors;
}
export function catalogWarnings(policy, catalog) {
  const known = new Set(catalog.entities.map(entity => entity.id));
  const warnings = [];
  policy.allow.forEach((rule, index) => {
    for (const id of rule.entity_ids) if (!known.has(id)) warnings.push(`Rule ${index+1}: entity "${id}" was not found in the current supported HA entities. Check for a typo, a renamed entity or an entity that is currently unavailable.`);
  });
  for (const id of policy.deny_entity_ids) if (!known.has(id)) warnings.push(`Excluded entity "${id}" was not found in the current supported HA entities. The exclusion is preserved.`);
  return warnings;
}
export function matchingEntities(rule, entities, deny = []) {
  if (!categories.some(key => rule[key].length)) return [];
  return entities.filter(entity => (rule.capability !== 'trigger_automation' || entity.id.startsWith('automation.')) &&
    !deny.includes(entity.id) && ruleMatches(rule, entity));
}
export function policyYaml(policy) {
  const errors = validateDraft(policy);
  if (errors.length) throw new Error(errors.join('\n'));
  const lines = ['ha_access:', `  enabled: ${policy.enabled}`];
  if (!policy.allow.length) lines.push('  allow: []');
  else {
    lines.push('  allow:');
    for (const rule of policy.allow) {
      lines.push(`    - capability: ${rule.capability}`);
      for (const key of categories) lines.push(`      ${key}: ${JSON.stringify(rule[key])}`);
    }
  }
  lines.push(`  deny_entity_ids: ${JSON.stringify(policy.deny_entity_ids)}`);
  return lines.join('\n') + '\n';
}
