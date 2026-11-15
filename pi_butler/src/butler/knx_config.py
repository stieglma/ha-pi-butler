"""Configured KNX repository location; never opens a project in the editor."""
import os
import ipaddress
from pathlib import PurePosixPath
import stat

DEFAULT = {'enabled': False, 'read_enabled': True,
           'repository_directory': 'knx_editor', 'project_filename': 'project.knxproj',
           'gateway_addresses': []}


def normalize_options(value):
    if not isinstance(value, dict) or set(value) - DEFAULT.keys():
        raise ValueError('Invalid KNX options')
    options = DEFAULT | value
    if any(type(options[key]) is not bool for key in ('enabled', 'read_enabled')):
        raise ValueError('Invalid KNX switches')
    directory = options['repository_directory']
    if (not isinstance(directory, str) or not directory or len(directory) > 240
            or any(ord(c) < 32 or c == '\\' for c in directory)
            or PurePosixPath(directory).is_absolute()
            or any(part in ('', '.', '..', '.git') for part in directory.split('/'))):
        raise ValueError('KNX repository directory must be a relative folder without traversal')
    filename = options['project_filename']
    if (not isinstance(filename, str) or not filename.lower().endswith('.knxproj')
            or len(filename) > 200 or filename.lower() == '.knxproj'
            or any(ord(c) < 32 or c in '/\\' for c in filename)):
        raise ValueError('KNX project filename must be a .knxproj filename without folders')
    values = options['gateway_addresses']
    if not isinstance(values, list) or len(values) > 32:
        raise ValueError('KNX gateway addresses must be a list of at most 32 literal IP addresses')
    addresses = []
    for value in values:
        if not isinstance(value, str) or '%' in value:
            raise ValueError('Use literal KNX gateway IP addresses, without hostnames or scope IDs')
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError('Invalid KNX gateway IP address') from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_unspecified or address.is_loopback or address.is_multicast or str(address) == '255.255.255.255':
            raise ValueError('KNX gateway must be a unicast address, not loopback, multicast or unspecified')
        if str(address) not in addresses:
            addresses.append(str(address))
    if options['enabled'] and not addresses:
        raise ValueError('Configure knx.gateway_addresses before enabling KNX; refusing unprotected gateway access')
    options['gateway_addresses'] = addresses
    return options


def project_source_check(options, repository):
    """Unprivileged presence check using no-follow directory FDs, not file content.

    A ready result means the configured regular file exists, not that it has been
    imported, validated, or synchronized with the editor's private working project.
    """
    options = normalize_options(options)
    relative = options['repository_directory'] + '/' + options['project_filename']
    descriptor = None
    try:
        descriptor = os.open(repository, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in options['repository_directory'].split('/'):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.stat(options['project_filename'], dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Not a regular project file')
        return {'state': 'ready', 'path': relative, 'automatic_import': False,
                'help': f'Found {relative} in the repository. Use KNX projects & access to import a separate working copy; existing editor projects are retained.'}
    except (OSError, ValueError):
        return {'state': 'pending', 'path': relative, 'automatic_import': False,
                'help': f'Expected {relative} in the repository; missing, inaccessible or not a regular file without symlinks. Import is an explicit action in KNX projects & access or the editor.'}
    finally:
        if descriptor is not None:
            os.close(descriptor)
