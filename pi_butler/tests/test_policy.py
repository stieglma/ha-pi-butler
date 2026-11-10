import copy
import unittest
from butler.policy import Policy, Rejected, operation


def policy(rules=None, deny=None, enabled=True):
    return Policy({'enabled': enabled, 'allow': rules or [], 'deny_entity_ids': deny or []})


def rule(capability='control', **selectors):
    return {'capability': capability, **selectors}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.states = [{'entity_id': e} for e in ['light.office', 'light.nursery', 'switch.fan', 'automation.evening']]
        self.registry = {'light.office': {'labels': ['writable']}, 'light.nursery': {'labels': []}}

    def authorize(self, p, target, domain='light', action='turn_on', data=None):
        return p.authorize(domain, action, target, data or {}, self.states, self.registry)

    def test_default_deny(self):
        for p in [policy(), policy([rule(domains=['light'])], enabled=False)]:
            with self.assertRaises(Rejected):
                self.authorize(p, {'entity_ids': ['light.office']})

    def test_rule_or_categories_or_values_or_rules(self):
        p = policy([rule(domains=['light', 'switch'], label_ids=['writable', 'other']), rule(entity_ids=['switch.fan'])])
        self.assertTrue(p.permits('light.office', 'control', self.registry))
        self.assertTrue(p.permits('light.nursery', 'control', self.registry))
        self.assertTrue(p.permits('switch.fan', 'control', self.registry))

    def test_all_three_selectors_independently_grant(self):
        p = policy([rule(entity_ids=['light.nursery'], domains=['light'], label_ids=['writable'])])
        self.assertTrue(p.permits('light.office', 'control', self.registry))
        self.assertTrue(p.permits('light.nursery', 'control', self.registry))

    def test_each_selector_alone_matches_with_other_selectors_configured(self):
        p = policy([rule(entity_ids=['switch.fan'], domains=['calendar'], label_ids=['writable'])])
        for entity in ('switch.fan', 'calendar.thomas', 'light.office', 'light.nursery'):
            with self.subTest(entity=entity):
                expected = entity != 'light.nursery'
                self.assertEqual(p.permits(entity, 'control', self.registry), expected)
                explanation = p.explain(entity, 'control', self.registry)
                self.assertEqual(explanation['rules'][0]['matches'], expected)
                self.assertEqual(explanation['permitted'], expected)
                self.assertFalse(p.permits(entity, 'trigger_automation', self.registry))
        for p in (policy(p.config['allow'], enabled=False),
                  policy(p.config['allow'], deny=['switch.fan'])):
            self.assertFalse(p.permits('switch.fan', 'control', self.registry))

    def test_calendar_label_grant_without_entity_selector(self):
        registry = {'calendar.family': {'labels': ['ai_controllable']},
                    'calendar.work': {'labels': []},
                    'light.office': {'labels': ['ai_controllable']}}
        for entities in ({}, {'entity_ids': []}):
            with self.subTest(entities=entities):
                p = policy([rule(domains=['calendar'], label_ids=['ai_controllable'], **entities)])
                self.assertTrue(p.permits('calendar.family', 'control', registry))
                self.assertTrue(p.permits('calendar.work', 'control', registry))
                self.assertTrue(p.permits('light.office', 'control', registry))

    def test_grant_requires_at_least_one_nonempty_selector(self):
        for selectors in ({}, {'entity_ids': [], 'domains': [], 'label_ids': []}):
            with self.subTest(selectors=selectors), self.assertRaises(Rejected):
                policy([rule(**selectors)])

    def test_denial_prevents_entire_batch(self):
        p = policy([rule(domains=['light'])], deny=['light.nursery'])
        with self.assertRaises(Rejected):
            self.authorize(p, {'domains': ['light']})

    def test_labels_resolve_current_direct_membership(self):
        p = policy([rule(label_ids=['writable'])])
        self.authorize(p, {'label_ids': ['writable']})
        self.registry['light.office']['labels'] = []
        with self.assertRaises(Rejected):
            self.authorize(p, {'label_ids': ['writable']})

    def test_new_matching_entities_inherit(self):
        p = policy([rule(domains=['light'])])
        self.states.append({'entity_id': 'light.new'})
        targets, _ = self.authorize(p, {'domains': ['light']})
        self.assertIn('light.new', targets)

    def test_automation_trigger_is_distinct(self):
        p = policy([rule(domains=['automation'])])
        self.authorize(p, {'entity_ids': ['automation.evening']}, 'automation', 'turn_off')
        with self.assertRaises(Rejected):
            self.authorize(p, {'entity_ids': ['automation.evening']}, 'automation', 'trigger')
        p = policy([rule('trigger_automation', entity_ids=['automation.evening'])])
        self.authorize(p, {'entity_ids': ['automation.evening']}, 'automation', 'trigger', {'skip_condition': True})
        with self.assertRaises(Rejected):
            self.authorize(p, {'entity_ids': ['automation.evening']}, 'automation', 'turn_on')

    def test_unknown_ambiguous_embedded_targets_fail(self):
        p = policy([rule(domains=['light'])])
        for target in [{}, {'entity_ids': []}, {'entity_ids': ['all']}, {'entity_ids': ['light.missing']},
                       {'area_id': ['office']}, {'entity_ids': ['light.office', 'light.missing']},
                       {'domains': ['light', 'missing']}, {'entity_ids': 'light.office'}, {'entity_ids': ['switch.fan']}]:
            with self.subTest(target=target), self.assertRaises(Rejected):
                self.authorize(p, target)
        for data in [{'entity_id': 'light.nursery'}, {'target': {'entity_id': 'light.nursery'}}, {'variables': {'entity_id': 'light.nursery'}}]:
            with self.assertRaises(Rejected):
                self.authorize(p, {'entity_ids': ['light.office']}, data=data)

    def test_light_controls_share_grant(self):
        p = policy([rule(entity_ids=['light.office'])])
        for action in ('turn_on', 'turn_off', 'toggle'):
            self.authorize(p, {'entity_ids': ['light.office']}, action=action, data={'transition': 1})

    def test_unknown_global_operations(self):
        for domain, action in [('homeassistant', 'turn_on'), ('script', 'turn_on'), ('scene', 'turn_on'), ('automation', 'reload'), ('light', 'surprise')]:
            with self.assertRaises(Rejected):
                operation(domain, action, {})

    def test_invalid_action_data(self):
        for data in [{'brightness': True}, {'brightness_pct': 101}, {'transition': float('nan')}, {'rgb_color': [1, 2]},
                     {'hs_color': [400, 50]}, {'flash': 'forever'}, {'effect': {'entity_id': 'light.other'}}]:
            with self.subTest(data=data), self.assertRaises(Rejected):
                operation('light', 'turn_on', data)

    def test_calendar_features_and_interval(self):
        self.states.append({'entity_id': 'calendar.family', 'attributes': {'supported_features': 1}})
        p = policy([rule(domains=['calendar'])])
        data = {'summary': 'Test', 'start_date': '2026-11-10', 'end_date': '2026-11-11'}
        self.authorize(p, {'entity_ids': ['calendar.family']}, 'calendar', 'create_event', data)
        for bad in [dict(data, end_date='2026-11-09'), dict(data, start_date_time='2026-11-10T10:00:00'), dict(data, summary=None)]:
            with self.assertRaises(Rejected):
                operation('calendar', 'create_event', bad)
        self.states[-1]['attributes']['supported_features'] = 0
        with self.assertRaises(Rejected):
            self.authorize(p, {'entity_ids': ['calendar.family']}, 'calendar', 'create_event', data)

    def test_invalid_policy_and_stable_version(self):
        for bad in [{'enabled': True, 'allow': [rule()]}, {'enabled': 1, 'allow': []},
                    {'enabled': True, 'allow': [rule(domains='light')]}, {'enabled': True, 'allow': [rule('execute', domains=['script'])]}]:
            with self.assertRaises(Rejected):
                Policy(bad)
        self.assertEqual(policy().version, policy().version)
        self.assertNotEqual(policy().version, policy(enabled=False).version)
