"""Standalone HA metadata consistency check (not a replacement for Supervisor)."""
from pathlib import Path
import yaml
import json

root = Path(__file__).resolve().parents[1]
config = yaml.safe_load((root / 'config.yaml').read_text())
assert config['arch'] == ['amd64']
assert config['slug'] == 'pi_butler'
assert config['ingress'] and config['homeassistant_api']
assert config['hassio_role'] == 'homeassistant'
assert not config.get('host_network') and not config.get('privileged') and not config.get('map')
assert not config.get('ports')
assert 'ha_access' not in config['options'] and 'ha_access' not in config['schema']
assert set(config['options']) == set(config['schema'])
for key in config['options']:
    assert set(config['options'][key]) == set(config['schema'][key])
manifest = json.loads((root / 'package.json').read_text())
lock = json.loads((root / 'package-lock.json').read_text())
assert len(manifest['piButler']['packages']) == len(set(manifest['piButler']['packages']))
for name in manifest['piButler']['packages']:
    assert manifest['dependencies'][name] == lock['packages']['node_modules/' + name]['version']
assert 'node_modules/pi-mcp-adapter' not in lock['packages']
for language in ('en', 'de'):
    translated = yaml.safe_load((root / 'translations' / (language + '.yaml')).read_text())['configuration']
    for section, definition in config['schema'].items():
        fields = translated[section]['fields']
        assert set(fields) == set(definition)
assert config['ingress_entry'] == '/'
print('HA metadata, translations and bundled package pins passed')
