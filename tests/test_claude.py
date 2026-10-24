from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from schedule_agent.backends import (
    BackendError, bin_exists, build_cmd, claude_auth_status, normalize_backend,
    parse_spawned_id,
)
from schedule_agent.chats import ChatError, chats_for_cwd, iter_chats, resolve_workspace
from schedule_agent.cli import main
from schedule_agent.jobs import load_registry, upsert_job


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'claude-config'
        env = patch.dict(os.environ, {
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'XDG_STATE_HOME': str(self.root / 'state'),
            'CLAUDE_CONFIG_DIR': str(self.config),
        })
        env.start()
        self.addCleanup(env.stop)
        self.output = io.StringIO()
        for redirect in (contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output)):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def make_session(self, session_id=None, events=None, project='project', **metadata):
        session_id = session_id or str(uuid4())
        path = self.config / 'projects' / project / f'{session_id}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        events = events if events is not None else [
            {'type': 'mode', 'sessionId': session_id},
            {'type': 'user', 'sessionId': session_id, 'cwd': str(self.root),
             'message': {'content': 'First prompt\nMore context'}},
        ]
        path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        if metadata:
            (path.parent / 'sessions-index.json').write_text(json.dumps({
                'entries': [{'sessionId': session_id, **metadata}],
            }))
        return session_id, path

    def job(self, **fields):
        now = datetime.now().astimezone()
        job = {'id': 'claude-test', 'backend': 'claude', 'workspace': str(self.root),
               'prompt': 'hello', 'chatId': None, 'spawn': 'once', 'timeout': '3s',
               'enabled': True, 'createdAt': now.isoformat(),
               'schedule': {'type': 'at', 'runAt': (now - timedelta(minutes=1)).isoformat()}}
        job.update(fields)
        return job

    def make_fake(self):
        fake = self.root / 'claude'
        fake.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys, time, uuid
if sys.argv[1:] == ['auth', 'status', '--json']:
    print(json.dumps({{'loggedIn': True, 'authMethod': 'fake'}}))
    raise SystemExit(0)
args = sys.argv[1:]
assert '--print' in args
assert args[args.index('--output-format') + 1] == 'stream-json'
assert '--verbose' in args
assert '--dangerously-skip-permissions' in args
assert args[-2] == '--'
resume = args[args.index('--resume') + 1] if '--resume' in args else None
session_id = resume or str(uuid.uuid4())
print(json.dumps({{'type':'system', 'subtype':'init', 'session_id':session_id}}), flush=True)
with pathlib.Path({str(self.root / 'calls.jsonl')!r}).open('a') as log:
    log.write(json.dumps({{'args': args, 'cwd': os.getcwd(), 'resume': resume, 'session': session_id}}) + '\\n')
mode = args[-1]
if mode == 'fail':
    print(json.dumps({{'type':'result', 'is_error':True, 'session_id':session_id}}), flush=True)
    raise SystemExit(12)
if mode == 'timeout': time.sleep(10)
print(json.dumps({{'type':'result', 'is_error':False, 'session_id':session_id, 'result':'ok'}}), flush=True)
''')
        fake.chmod(0o755)
        env = patch.dict(os.environ, {'SCHEDULE_CLAUDE_BIN': str(fake)})
        env.start()
        self.addCleanup(env.stop)
        return fake

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]

    def test_normalize_and_error_lists_claude(self):
        self.assertEqual(normalize_backend('Claude'), 'claude')
        self.assertEqual(normalize_backend('claude-code'), 'claude')
        with self.assertRaisesRegex(BackendError, 'cursor, codex, claude'):
            normalize_backend('unknown')

    def test_spawn_command_model_args_and_literal_prompt(self):
        self.make_fake()
        cmd = build_cmd(self.job(model='sonnet', prompt='--literal $() prompt',
                                 extraArgs=['--max-turns', '2']))
        self.assertNotIn('--resume', cmd)
        self.assertEqual(cmd[-2:], ['--', '--literal $() prompt'])
        self.assertEqual(cmd[cmd.index('--model') + 1], 'sonnet')
        self.assertEqual(cmd[cmd.index('--max-turns') + 1], '2')
        self.assertEqual(cmd[0], os.environ['SCHEDULE_CLAUDE_BIN'])

    def test_resume_command_and_new_each_run(self):
        resumed = build_cmd(self.job(chatId='saved-session'))
        self.assertEqual(resumed[resumed.index('--resume') + 1], 'saved-session')
        fresh = build_cmd(self.job(chatId='saved-session', spawn='each'))
        self.assertNotIn('--resume', fresh)

    def test_streaming_session_id_parser(self):
        self.assertEqual(parse_spawned_id('banner\n{"type":"system","subtype":"init","session_id":"claude-session"}\n'), 'claude-session')

    def test_discover_workspace_and_filter(self):
        session_id, path = self.make_session()
        rows = iter_chats('claude')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], session_id)
        self.assertEqual(rows[0]['title'], 'First prompt')
        self.assertEqual(rows[0]['metaPath'], str(path))
        self.assertEqual(resolve_workspace(session_id, backend='claude'), self.root)
        self.assertEqual(chats_for_cwd(str(self.root / 'other'), 'claude'), [])
        self.assertEqual(len(chats_for_cwd(str(self.root), 'claude')), 1)

    def test_index_title_and_content_blocks(self):
        session_id = str(uuid4())
        self.make_session(session_id, events=[{
            'type': 'user', 'sessionId': session_id, 'cwd': str(self.root),
            'message': {'content': [{'type': 'text', 'text': 'Read this'}, {'type': 'image'}]},
        }])
        self.assertEqual(iter_chats('claude')[0]['title'], 'Read this')
        self.make_session(session_id, customTitle='Named session', projectPath=str(self.root))
        self.assertEqual(iter_chats('claude')[0]['title'], 'Named session')

    def test_discovery_ignores_nested_sidechains_and_corrupt_files(self):
        main_id, path = self.make_session()
        nested = path.parent / main_id / 'subagents'
        nested.mkdir(parents=True)
        (nested / f'{uuid4()}.jsonl').write_text(path.read_text())
        side_id = str(uuid4())
        self.make_session(side_id, events=[{'sessionId': side_id, 'isSidechain': True, 'cwd': str(self.root)}])
        self.make_session(events=[{'no': 'session metadata'}])
        (path.parent / f'{uuid4()}.jsonl').write_text('bad json\n[]\n')
        (path.parent / 'agent-foo.jsonl').write_text(path.read_text())
        self.assertEqual([row['id'] for row in iter_chats('claude')], [main_id])

    def test_workspace_errors_and_explicit_override(self):
        with self.assertRaisesRegex(ChatError, 'projects'):
            resolve_workspace('missing', backend='claude')
        self.assertEqual(resolve_workspace('missing', str(self.root), 'claude'), self.root)
        with self.assertRaises(ChatError):
            resolve_workspace('missing', str(self.root / 'absent'), 'claude')

    def test_all_chats_includes_claude_and_add_infers_workspace(self):
        session_id, _ = self.make_session()
        with patch('schedule_agent.cli.timer_is_enabled', return_value=True):
            self.assertEqual(main(['add', '--backend', 'claude', '--chat-id', session_id,
                                   '--name', 'resume', '--at', 'now', '--prompt', 'hello']), 0)
        self.assertEqual(load_registry()['jobs']['resume']['workspace'], str(self.root))
        with patch('schedule_agent.chats.iter_cursor_chats', return_value=[]), patch('schedule_agent.chats.iter_codex_chats', return_value=[]):
            self.output.seek(0)
            self.output.truncate(0)
            self.assertEqual(main(['chats', '--backend', 'all', '--json']), 0)
            self.assertEqual(json.loads(self.output.getvalue())[0]['backend'], 'claude')

    def test_auth_success_failure_invalid_json_and_timeout(self):
        cases = [(0, {'loggedIn': True, 'authMethod': 'api_key'}, True),
                 (0, {'loggedIn': False}, False), (1, {'loggedIn': True}, False),
                 (0, [], False)]
        for code, data, expected in cases:
            with self.subTest(data=data, code=code), patch('schedule_agent.backends.subprocess.run', return_value=subprocess.CompletedProcess([], code, json.dumps(data), '')):
                self.assertEqual(claude_auth_status()[0], expected)
        with patch('schedule_agent.backends.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'not json', '')):
            self.assertFalse(claude_auth_status()[0])
        for error in (FileNotFoundError('missing'), subprocess.TimeoutExpired('claude', 10)):
            with patch('schedule_agent.backends.subprocess.run', side_effect=error):
                self.assertFalse(claude_auth_status()[0])

    def test_validate_checks_requested_claude_auth(self):
        self.make_fake()
        with patch('schedule_agent.cli.timer_is_enabled', return_value=True), patch('schedule_agent.cli.timer_is_active', return_value=True), patch('schedule_agent.cli.linger_enabled', return_value=True):
            self.assertEqual(main(['validate', '--backend', 'claude', '--json']), 0)
            self.assertIn('claudeAuth', self.output.getvalue())
            with patch('schedule_agent.cli.claude_auth_status', return_value=(False, 'not authenticated')):
                self.assertEqual(main(['validate', '--backend', 'claude']), 2)

    def test_missing_binary_override_does_not_fall_back_to_path(self):
        self.make_fake()
        with patch.dict(os.environ, {'PATH': str(self.root) + ':' + os.environ.get('PATH', '')}):
            self.assertFalse(bin_exists(self.root / 'missing/claude'))
            self.assertFalse(bin_exists(self.root))
            self.assertTrue(bin_exists(Path('claude')))

    def test_tick_creates_session_then_manual_run_resumes_it(self):
        self.make_fake()
        upsert_job(self.job())
        self.assertEqual(main(['tick']), 0)
        first = load_registry()['jobs']['claude-test']
        self.assertEqual(first['lastStatus'], 'ok')
        self.assertFalse(first['enabled'])
        self.assertEqual(main(['run', 'claude-test']), 0)
        calls = self.calls()
        self.assertIsNone(calls[0]['resume'])
        self.assertEqual(calls[1]['resume'], first['chatId'])
        self.assertEqual(calls[0]['cwd'], str(self.root))

    def test_new_each_run_uses_distinct_sessions(self):
        self.make_fake()
        upsert_job(self.job(spawn='each'))
        self.assertEqual(main(['run', 'claude-test']), 0)
        self.assertEqual(main(['run', 'claude-test']), 0)
        calls = self.calls()
        self.assertNotEqual(calls[0]['session'], calls[1]['session'])
        self.assertTrue(all(call['resume'] is None for call in calls))
        self.assertIsNone(load_registry()['jobs']['claude-test']['chatId'])
        self.assertEqual(load_registry()['jobs']['claude-test']['lastChatId'], calls[1]['session'])

    def test_failure_keeps_session_for_retry(self):
        self.make_fake()
        upsert_job(self.job(prompt='fail'))
        self.assertEqual(main(['tick']), 3)
        failed = load_registry()['jobs']['claude-test']
        self.assertTrue(failed['enabled'])
        self.assertEqual(failed['lastExit'], 12)
        self.assertTrue(failed['nextRetryAt'])
        self.assertEqual(main(['run', 'claude-test']), 3)
        self.assertEqual(self.calls()[1]['resume'], failed['chatId'])

    def test_timeout_keeps_session_id_from_stream_init(self):
        self.make_fake()
        upsert_job(self.job(prompt='timeout'))
        with patch('schedule_agent.agent_run.parse_timeout', return_value=.2):
            self.assertEqual(main(['tick']), 3)
        saved = load_registry()['jobs']['claude-test']
        self.assertEqual(saved['lastExit'], 124)
        self.assertEqual(saved['chatId'], self.calls()[0]['session'])

    def test_install_and_uninstall_include_custom_claude_skill(self):
        source = Path(__file__).resolve().parents[1]
        fake_home = self.root / 'install-home'
        fake_home.mkdir()
        fake_bin = self.root / 'fake-bin'
        fake_bin.mkdir()
        systemctl = fake_bin / 'systemctl'
        systemctl.write_text('#!/bin/sh\nexit 0\n')
        systemctl.chmod(0o755)
        env = {**os.environ, 'HOME': str(fake_home),
               'PATH': str(fake_bin) + ':' + os.environ.get('PATH', '')}
        install = subprocess.run(['bash', str(source / 'scripts/install.sh')], env=env,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(install.returncode, 0, install.stderr)
        for skill in (fake_home / '.cursor/skills/schedule-agent/SKILL.md',
                      fake_home / '.codex/skills/schedule-agent/SKILL.md',
                      self.config / 'skills/schedule-agent/SKILL.md'):
            self.assertEqual(skill.read_bytes(), (source / 'skill/SKILL.md').read_bytes())
        self.assertTrue((fake_home / '.local/lib/schedule-agent/schedule_agent/backends.py').is_file())
        units = fake_home / '.config/systemd/user'
        self.assertEqual(sorted(path.name for path in units.iterdir()),
                         ['cursor-schedule.service', 'cursor-schedule.timer'])
        uninstall = subprocess.run(['bash', str(source / 'scripts/uninstall.sh')], env=env,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
        self.assertFalse((self.config / 'skills/schedule-agent').exists())
        self.assertFalse((fake_home / '.local/bin/schedule-agent').exists())

    def test_recurring_claude_job_remains_enabled(self):
        self.make_fake()
        old = datetime.now().astimezone() - timedelta(days=2)
        upsert_job(self.job(createdAt=old.isoformat(), schedule={'type': 'cron', 'expr': '0 0 * * *'}))
        self.assertEqual(main(['tick']), 0)
        saved = load_registry()['jobs']['claude-test']
        self.assertTrue(saved['enabled'])
        self.assertEqual(saved['lastStatus'], 'ok')
        self.assertEqual(main(['tick']), 0)
        self.assertEqual(len(self.calls()), 1)


if __name__ == '__main__':
    unittest.main()
