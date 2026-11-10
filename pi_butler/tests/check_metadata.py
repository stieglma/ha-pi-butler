"""Standalone HA metadata consistency check (not a replacement for Supervisor)."""
from pathlib import Path
import yaml

root = Path(__file__).resolve().parents[1]
config = yaml.safe_load((root / 'config.yaml').read_text())
assert config['arch'] == ['amd64']
assert config['slug'] == 'pi_butler'
assert config['ingress'] and config['homeassistant_api']
assert config['hassio_role'] == 'homeassistant'
assert not config.get('host_network') and not config.get('privileged') and not config.get('map')
assert not config.get('ports')
assert config['options']['ha_access'] == {'enabled': False, 'allow': [], 'deny_entity_ids': []}
assert set(config['options']) == set(config['schema'])
for key in config['options']:
    assert set(config['options'][key]) == set(config['schema'][key])
print('HA metadata checks passed')
