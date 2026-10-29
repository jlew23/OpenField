"""Claude line tests: finding jarvis-galaxy and its agents, streaming a turn, thread memory, old CLIs, LAN guard."""
import json, os, shutil, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from station import claude_line, db

FAKE = Path(__file__).resolve().parent / 'fixtures' / 'fake_claude'


class ClaudeLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        db.init(self.tmp / 'station.db')
        docs = self.tmp / 'Documents'
        (docs / 'openfield').mkdir(parents=True)
        self.galaxy = docs / 'jarvis-galaxy'
        (self.galaxy / 'subagents').mkdir(parents=True)
        (self.galaxy / 'subagents' / 'beat-scout.md').write_text('---\nname: beat-scout\ndescription: Finds beats\n---\nScout.\n')
        (self.galaxy / 'subagents' / 'notes.md').write_text('no front matter here')
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        shutil.copy(FAKE, bin_dir / 'claude')
        (bin_dir / 'claude').chmod(0o755)
        self.env = patch.dict(os.environ, {'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}', 'JARVIS_GALAXY_DIR': ''})
        self.env.start()
        claude_line.set_runs(docs / 'openfield')
        claude_line._status_cache.clear()
        claude_line._partial['ok'] = True

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_galaxy_and_agents(self):
        self.assertEqual(claude_line.galaxy_dir(), self.galaxy)
        found, folders = claude_line.agents()
        self.assertEqual([a['name'] for a in found], ['beat-scout'])
        self.assertEqual(folders[0]['folder'], 'subagents')
        st = claude_line.status()
        self.assertTrue(st['ok'])
        self.assertIn('Claude Code', st['version'])

    def test_turn_streams_and_thread_resumes(self):
        events = list(claude_line.ask('you there?'))
        kinds = [k for k, _ in events]
        self.assertIn('delta', kinds)
        self.assertEqual(kinds[-1], 'done')
        self.assertIn('you there?', events[-1][1]['text'])
        self.assertEqual(db.get_setting('claude_line_session'), 'sess-123')
        list(claude_line.ask('again', agent='beat-scout'))
        calls = [json.loads(l) for l in (self.tmp / 'bin' / 'calls.jsonl').read_text().splitlines()]
        self.assertNotIn('--resume', calls[0]['argv'])
        self.assertIn('--resume', calls[1]['argv'])
        self.assertTrue(calls[1]['argv'][calls[1]['argv'].index('-p') + 1].startswith('Use the beat-scout subagent'))
        self.assertEqual(Path(calls[1]['cwd']).name, 'jarvis-galaxy')
        self.assertEqual([m['role'] for m in claude_line.history()], ['user', 'assistant', 'user', 'assistant'])
        claude_line.new_thread()
        self.assertEqual(claude_line.history(), [])

    def test_older_cli_without_partial_messages(self):
        with patch.dict(os.environ, {'FAKE_OLD': '1'}):
            events = list(claude_line.ask('hello'))
        self.assertEqual(events[-1][0], 'done')
        self.assertFalse(claude_line._partial['ok'])

    def test_missing_cli_explains(self):
        with patch.object(claude_line, 'cli', return_value=None):
            events = list(claude_line.ask('hi'))
        self.assertEqual(events[-1][0], 'error')
        self.assertIn('Claude Code', events[-1][1])

    def test_lan_guard(self):
        from station import api
        api._local_only(SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')))
        with self.assertRaises(HTTPException):
            api._local_only(SimpleNamespace(client=SimpleNamespace(host='192.168.1.50')))
        claude_line.update_config({'allow_lan': True})
        api._local_only(SimpleNamespace(client=SimpleNamespace(host='192.168.1.50')))
        self.assertTrue(claude_line.config()['allow_lan'])


if __name__ == '__main__':
    unittest.main()
