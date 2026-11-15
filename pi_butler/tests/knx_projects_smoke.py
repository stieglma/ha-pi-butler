"""Real pinned editor services: synthetic project only, no GUI or bus."""
import json
import shutil
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from butler.knx_runtime import Runtime
from butler.knx_projects import remembered_project
from butler.knx_repository import unpack_checkpoint
from butler.policy import Rejected


def main():
    from editor_gui.plugins.base import Logger
    from editor_gui.plugins.logger.service import LogService
    from editor_gui.plugins.catalog.service import CatalogService
    from editor_gui.plugins.project.service import ProjectService
    from editor_gui.plugins.mcp.context import McpContext
    from editor_gui import settings
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'projects').mkdir()
        (root / 'config').mkdir()
        catalog = CatalogService(root / 'catalog.xknxcatalog')
        project = ProjectService(catalog)
        log = LogService()
        project.set_logger(Logger(log, 'project'))
        ctx = McpContext(api=SimpleNamespace(project=project, catalog=catalog),
            run_on_ui=lambda fn, **kw: fn(), connection_plugin=Mock(), monitor=Mock(),
            keyring=Mock(), log=Logger(log, 'mcp'))
        runtime = Runtime(root)
        with patch.object(settings, 'config_dir', lambda: root / 'config'):
            runtime.attach(ctx, monitor=False)
            project.new(root / 'projects/manual.xknx', name='Synthetic House')
            # Public upstream synthetic product fixture, never the user's project.
            import editor_gui
            source = Path('/opt/knx/source')
            if not source.is_dir():
                source = Path(editor_gui.__file__).resolve().parents[4]
            fixture = source / 'packages/prod/tests/fixtures/gira_2gang_button_interface.knxprod'
            assert fixture.is_file(), fixture
            products = catalog.import_knxprod(fixture)
            runtime.tools['project_add_device'](product_ref_id=products[0].product_ref_id, name='Synthetic Button')
            first = runtime.execute('checkpoint', {'comment': 'Initial'})
            # Verify a native checkpoint carries product data without the live catalog.
            native = root / 'standalone.xknx'
            shutil.copyfile(runtime.projects.folder / first['id'] / 'project.xknx', native)
            independent = ProjectService(CatalogService(root / 'fresh-catalog.xknxcatalog'))
            independent.set_logger(Logger(log, 'independent'))
            independent.open(native)
            assert len(independent.devices) == 1
            independent.close()
            assert runtime.projects.status()['dirty'] is False
            assert remembered_project(root) == str(root / 'projects/manual.xknx')
            request = {'tool': 'project_create_group_address', 'arguments': {'name': 'Light', 'address': '1/2/3'}}
            try:
                runtime.execute('assistant', request)
            except Rejected:
                pass
            else:
                raise AssertionError('Writes allowed by default')
            guid = runtime.projects.active()['guid']
            runtime.execute('policy', {'version': runtime.policy_version(), 'grants': [{'project_guid': guid, 'capabilities': ['add'], 'node_ids': []}]})
            stale = runtime.policy_version()
            runtime.execute('policy', {'version': stale, 'grants': []})
            try:
                runtime.execute('policy', {'version': stale, 'grants': []})
            except ValueError:
                pass
            else:
                raise AssertionError('Stale permission update was accepted')
            runtime.execute('policy', {'version': runtime.policy_version(), 'grants': [{'project_guid': guid, 'capabilities': ['add'], 'node_ids': []}]})
            result = runtime.execute('assistant', request)
            assert result['result']['address'] == '1/2/3', result
            assert len(runtime.projects.entries()) == 2
            active = runtime.projects.active()
            runtime.execute('restore', {'id': first['id'], 'state': active['state']})
            assert not project.group_addresses
            assert len(runtime.tools['project_list_devices']()['items']) == 1
            assert len(runtime.projects.entries()) == 4
            folder, meta = runtime.projects.find(first['id'])
            download = root / 'download.zip'
            runtime.projects.download(first['id'], 'zip', download)
            files, _ = unpack_checkpoint(download.read_bytes())
            assert files['project.xknx']
            # Exercise the real closing callback at the retention boundary: it
            # prunes the original restore source before replace_with copies it.
            runtime.execute('assistant', request)
            runtime.projects.max_checkpoints = 1
            runtime.execute('restore', {'id': first['id'], 'state': runtime.projects.active()['state']})
            assert not project.group_addresses
            assert len(runtime.projects.entries()) == 1
            assert not folder.exists()
            # Matching state keys must not permit reuse of a damaged export.
            latest = runtime.projects.entries()[0]
            (runtime.projects.folder / latest['id'] / 'project.knxproj').unlink()
            repaired = runtime.projects.checkpoint(force=False)
            assert repaired['id'] != latest['id']
            runtime.projects.find(repaired['id'])
            runtime.projects.max_checkpoints = 10
            queue = SimpleNamespace(_start=Mock(return_value='would-start'))
            runtime.guard_program_queue(queue)
            item = SimpleNamespace(scope='PARAMETERS', test=False, node_id=1)
            with patch.object(runtime.projects, 'checkpoint', side_effect=ValueError('export failed')):
                refused = queue._start(item)
                assert isinstance(refused.exception(), ValueError)
            assert queue._start(item) == 'would-start'
            original = root / 'projects/manual.xknx'
            exchange = root / 'import.knxproj'
            exchange.write_bytes(files['project.knxproj'])
            imported = runtime.import_source(exchange)
            assert imported['imported'].startswith('repository-'), imported
            assert original.is_file()
            assert project.path != original
            assert runtime.projects.active()['name'] == 'Synthetic House'
            project.close()

    print('Pinned editor: manual-project adoption, paired export, denied/granted write, restore and repository reimport passed')


if __name__ == '__main__':
    main()
