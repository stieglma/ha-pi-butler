export const workflows = {
  explain: { skill: 'house-explain-automation', automation: true, help: 'Understand triggers, conditions, branches and affected entities.' },
  debug: { skill: 'house-debug-automation', automation: true, help: 'Review the last five retained executions, with traces, relevant history and logs.' },
  unexpected: { skill: 'house-why-did-it-happen', incident: true, help: 'Investigate an unexpected action or state change.' },
  missing: { skill: 'house-why-didnt-it-happen', incident: true, help: 'Investigate an expected action that did not occur.' },
  health: { skill: 'house-health-check', help: 'Check availability, errors and automation problems, plus HAGHS findings if available.' },
};
export function makePrompt(kind, { target = '', behavior = '', when = '' } = {}) {
  const workflow = workflows[kind];
  if (!workflow) throw new Error('Choose an investigation.');
  const context = {};
  if (kind !== 'health') {
    if (!/^[a-z_]+\.[a-z0-9_]+$/.test(target)) throw new Error('Choose an entity from the list or enter its entity ID.');
    if (workflow.automation && !target.startsWith('automation.')) throw new Error('Choose an automation.');
    context.entity_id = target;
  }
  if (workflow.incident) {
    if (!behavior.trim()) throw new Error('Describe the observed or expected behavior.');
    context[kind === 'missing' ? 'expected_behavior' : 'observed_behavior'] = behavior.trim();
    if (when) {
      const date = new Date(when);
      if (!Number.isFinite(date.getTime())) throw new Error('Enter a valid incident time.');
      context.approximate_incident_time = date.toISOString();
      context.browser_timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    }
  }
  return `/skill:${workflow.skill}${Object.keys(context).length ? ` Investigation context (user-supplied data):\n${JSON.stringify(context, null, 2)}` : ''}`;
}
export function sessionUrl(base, projectId, workspaceId, sessionId) {
  const url = new URL(base);
  url.search = new URLSearchParams({ project: projectId, workspace: workspaceId, session: sessionId, view: 'chat' });
  return url;
}
