import json
import subprocess
import unittest
from unittest.mock import patch
from butler.knx_config import normalize_options
from butler.knx_firewall import FirewallError, TABLE, install


class GatewayConfigTests(unittest.TestCase):
    def test_literal_addresses_are_canonical_deduplicated_and_not_hostnames(self):
        options = normalize_options({'enabled': True, 'gateway_addresses': [
            '192.0.2.10', '::ffff:192.0.2.10', '2001:db8:0:0::10', '2001:db8::10']})
        self.assertEqual(options['gateway_addresses'], ['192.0.2.10', '2001:db8::10'])
        self.assertEqual(normalize_options({})['gateway_addresses'], [])
        for values in ([], ['gateway.local'], ['192.0.2.10/24'], ['127.0.0.1'], ['::1'],
                       ['0.0.0.0'], ['::'], ['224.0.23.12'], ['ff02::1'],
                       ['255.255.255.255'], ['fe80::1%eth0'], [False], '192.0.2.10', ['192.0.2.1'] * 33):
            with self.subTest(values=values), self.assertRaises(ValueError):
                normalize_options({'enabled': True, 'gateway_addresses': values})


class FirewallTests(unittest.TestCase):
    def test_missing_capability_or_kernel_support_is_a_hard_error(self):
        with patch('butler.knx_firewall.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'denied')):
            with self.assertRaises(FirewallError):
                install({})

    def test_missing_binary_timeout_and_corrupt_table_listing_are_hard_errors(self):
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('nft', 10)):
            with self.subTest(failure=failure), patch('butler.knx_firewall.subprocess.run', side_effect=failure):
                with self.assertRaises(FirewallError):
                    install({})
        for result in ('invalid JSON', '{}', '{"nftables": null}'):
            with self.subTest(result=result), patch('butler.knx_firewall.subprocess.run', return_value=subprocess.CompletedProcess([], 0, result, '')):
                with self.assertRaises(FirewallError):
                    install({})

    def test_apply_failure_does_not_get_treated_as_a_successful_guard(self):
        with patch('butler.knx_firewall.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, json.dumps({'nftables': []}), ''),
                subprocess.CompletedProcess([], 1, '', 'unsupported rule')]) as run:
            with self.assertRaises(FirewallError):
                install({})
            self.assertEqual(run.call_count, 2)

    def test_replacement_is_one_transaction_and_never_flushes_other_tables(self):
        seen = []
        def execute(command, **kwargs):
            seen.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, json.dumps({'nftables': [
                {'table': {'family': 'inet', 'name': 'other'}},
                {'table': {'family': 'inet', 'name': TABLE}}]}), '')
        with patch('butler.knx_firewall.subprocess.run', side_effect=execute):
            install({'gateway_addresses': ['192.0.2.10', '2001:db8::10']})
        self.assertEqual(len(seen), 2)
        transaction = seen[1][1]['input']
        self.assertTrue(transaction.startswith('delete table inet ' + TABLE + '\n'))
        self.assertNotIn('flush ruleset', transaction)
        self.assertNotIn('other', transaction)
        self.assertFalse(seen[1][1].get('shell', False))
