from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from butler.supervisor import configure_agent_instructions


class AgentInstructionTests(unittest.TestCase):
    def test_existing_defaults_migrate_preserving_custom_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'AGENTS.md'
            path.write_text('Custom household instructions\n'
                            'Use butler-workspace worktree NAME for each concurrent task.\n'
                            'When asked to deliver, review and stage changes, then use\n'
                            'butler-workspace deliver --message "..." from the worktree.\n')
            configure_agent_instructions(path)
            first = path.read_text()
            self.assertTrue(first.startswith('Custom household instructions\n'))
            self.assertNotIn('from the worktree.', first)
            self.assertIn('butler-workspace settings', first)
            configure_agent_instructions(path)
            self.assertEqual(path.read_text(), first)

    def test_new_install_and_symlink_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'AGENTS.md'
            with patch('butler.supervisor.os.fchown'):
                configure_agent_instructions(path)
            first = path.read_text()
            configure_agent_instructions(path)
            self.assertEqual(path.read_text(), first)
            link = Path(folder) / 'link'
            link.symlink_to(path)
            with self.assertRaises(RuntimeError):
                configure_agent_instructions(link)
            self.assertEqual(path.read_text(), first)
