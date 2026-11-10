"""Check browser-generated YAML against the trusted Python policy evaluator."""
import json
from pathlib import Path
import subprocess
import unittest
import yaml
import butler
from butler.policy import Policy

MODEL = (Path(butler.__file__).parent / 'web' / 'policy-model.mjs').resolve().as_uri()


class BrowserPolicyTests(unittest.TestCase):
    def test_generated_yaml_roundtrips_and_preview_matches_service(self):
        policy = {'enabled': True, 'allow': [{'capability': 'control', 'entity_ids': [], 'domains': ['light'], 'label_ids': ['writable']}], 'deny_entity_ids': ['light.nursery']}
        entities = [{'id': 'light.office', 'label_ids': ['writable']}, {'id': 'light.nursery', 'label_ids': ['writable']}, {'id': 'switch.fan', 'label_ids': ['writable']}]
        script = '''const m=await import(process.argv[1]); const input=JSON.parse(process.argv[2]); console.log(JSON.stringify({yaml:m.policyYaml(input.policy), matches:m.matchingEntities(input.policy.allow[0],input.entities,input.policy.deny_entity_ids).map(e=>e.id)}));'''
        output = subprocess.check_output(['node', '--input-type=module', '-e', script, MODEL, json.dumps({'policy': policy, 'entities': entities})], text=True)
        result = json.loads(output)
        self.assertEqual(yaml.safe_load(result['yaml']), {'ha_access': policy})
        trusted = Policy(policy)
        registry = {e['id']: {'labels': e['label_ids']} for e in entities}
        matches = [e['id'] for e in entities if trusted.permits(e['id'], 'control', registry)]
        self.assertEqual(result['matches'], matches)
