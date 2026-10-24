from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import wait as real_wait
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from schedule_agent.agent_run import _exec, job_lock, log_path
from schedule_agent.cli import _record_run, _run_stored_job, main
from schedule_agent.config import state_dir
from schedule_agent.jobs import delete_job, load_registry, parse_iso, upsert_job


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'XDG_STATE_HOME': str(self.root / 'state'),
        })
        env.start()
        self.addCleanup(env.stop)
        self.commands = patch('schedule_agent.agent_run.build_agent_cmd',
                              side_effect=lambda job: [sys.executable, '-u', '-c', job['prompt']])
        self.commands.start()
        self.addCleanup(self.commands.stop)
        self.stderr = io.StringIO()
        self.redirect = contextlib.redirect_stderr(self.stderr)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def add_job(self, name='demo', **fields):
        now = datetime.now().astimezone()
        job = {
            'id': name, 'enabled': True, 'backend': 'cursor', 'chatId': 'existing',
            'workspace': str(self.root), 'prompt': 'print("done")', 'timeout': '2s',
            'createdAt': (now - timedelta(days=1)).isoformat(),
            'schedule': {'type': 'at', 'runAt': (now - timedelta(minutes=1)).isoformat()},
        }
        job.update(fields)
        return upsert_job(job)

    def saved(self, name='demo'):
        return load_registry()['jobs'][name]

    def test_failed_one_shot_retries_after_backoff_then_completes(self):
        self.add_job(prompt='raise SystemExit(17)')
        self.assertEqual(main(['tick']), 3)
        failed = self.saved()
        self.assertTrue(failed['enabled'])
        self.assertEqual(failed['failureCount'], 1)
        self.assertEqual(failed['lastExit'], 17)
        retry_at = parse_iso(failed['nextRetryAt'])
        self.assertEqual(retry_at - parse_iso(failed['lastFinishedAt']), timedelta(minutes=1))
        with patch('schedule_agent.cli.run_job') as runner:
            self.assertEqual(main(['tick']), 0)
            runner.assert_not_called()
        class RetryClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return retry_at
        with patch('schedule_agent.cli.datetime', RetryClock), patch('schedule_agent.cli.run_job', return_value=(0, None)):
            self.assertEqual(main(['tick']), 0)
        saved = self.saved()
        self.assertFalse(saved['enabled'])
        self.assertEqual(saved['failureCount'], 0)
        self.assertIsNone(saved['nextRetryAt'])
        self.assertIn('completedAt', saved)
        self.assertIn('FAILED: demo: exit 17', self.stderr.getvalue())
        event = json.loads((state_dir() / 'failures.jsonl').read_text())
        self.assertEqual(event['job'], 'demo')
        self.assertEqual(event['lastExit'], 17)

    def test_launcher_exit_and_failure_event_with_real_fake_backend(self):
        fake = self.root / 'fake-agent'
        fake.write_text(
            f'#!{sys.executable}\n'
            'import sys\n'
            'prompt = sys.argv[sys.argv.index("-p") + 1]\n'
            'print("fake backend output", flush=True)\n'
            'sys.exit(9 if prompt == "fail" else 0)\n'
        )
        fake.chmod(0o755)
        self.add_job('bad', prompt='fail')
        self.add_job('good', prompt='succeed')
        launcher = Path(__file__).resolve().parents[1] / 'bin' / 'schedule-agent'
        env = {**os.environ, 'SCHEDULE_AGENT_BIN': str(fake)}
        result = subprocess.run([sys.executable, str(launcher), 'tick'], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('FAILED: bad: exit 9', result.stderr)
        self.assertEqual(self.saved('bad')['lastExit'], 9)
        self.assertEqual(self.saved('good')['lastStatus'], 'ok')
        self.assertIn('fake backend output', log_path('bad').read_text())

    def test_backoff_is_capped_at_one_hour(self):
        job = self.add_job(failureCount=20)
        _record_run(job, 1, None, complete_one_shot=True)
        saved = self.saved()
        self.assertEqual(parse_iso(saved['nextRetryAt']) - parse_iso(saved['lastFinishedAt']), timedelta(hours=1))

    def test_distinct_jobs_run_concurrently(self):
        marker = self.root / 'fast-started'
        slow = (
            'import pathlib,time\n'
            f'marker = pathlib.Path({str(marker)!r})\n'
            'deadline = time.monotonic() + 1\n'
            'while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)\n'
            'assert marker.exists(), "fast job blocked by slow job"\n'
        )
        self.add_job('slow', prompt=slow)
        self.add_job('fast', prompt=f'from pathlib import Path; Path({str(marker)!r}).touch()')
        self.assertEqual(main(['tick', '--workers', '2']), 0)
        self.assertEqual(self.saved('slow')['lastStatus'], 'ok')
        self.assertEqual(self.saved('fast')['lastStatus'], 'ok')

    def test_later_due_job_starts_while_another_job_is_running(self):
        initial = datetime.now().astimezone().replace(second=0, microsecond=0)
        current = [initial]
        later_started = threading.Event()
        self.add_job('slow', schedule={'type': 'at', 'runAt': initial.isoformat()})
        self.add_job('later', schedule={'type': 'at', 'runAt': (initial + timedelta(minutes=1)).isoformat()})
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return current[0]
        def run(job, **kwargs):
            if job['id'] == 'slow':
                current[0] = initial + timedelta(minutes=1)
                if not later_started.wait(2):
                    return 1, None
            else:
                later_started.set()
            return 0, None
        def fast_wait(fs, timeout, return_when):
            return real_wait(fs, timeout=min(timeout, .02), return_when=return_when)
        with patch('schedule_agent.cli.datetime', Clock), patch('schedule_agent.cli.run_job', side_effect=run), patch('schedule_agent.cli.wait', side_effect=fast_wait):
            self.assertEqual(main(['tick', '--workers', '2']), 0)
        self.assertTrue(later_started.is_set())
        self.assertFalse(self.saved('later')['enabled'])

    def test_workspace_error_does_not_abort_other_jobs(self):
        not_directory = self.root / 'file'
        not_directory.touch()
        self.add_job('bad', workspace=str(not_directory))
        self.add_job('good')
        self.assertEqual(main(['tick']), 3)
        self.assertEqual(self.saved('bad')['lastStatus'], 'failed')
        self.assertEqual(self.saved('good')['lastStatus'], 'ok')
        self.assertIn('ERROR:', log_path('bad').read_text())

    def test_unexpected_runner_exception_is_recorded_and_batch_continues(self):
        self.add_job('bad')
        self.add_job('good')
        def run(job, **kwargs):
            if job['id'] == 'bad':
                raise RuntimeError('fake failure')
            return 0, None
        with patch('schedule_agent.cli.run_job', side_effect=run):
            self.assertEqual(main(['tick']), 3)
        self.assertEqual(self.saved('bad')['lastError'], 'RuntimeError: fake failure')
        self.assertEqual(self.saved('good')['lastStatus'], 'ok')

    def test_bad_schedule_does_not_abort_other_jobs(self):
        self.add_job('bad', schedule={'type': 'cron', 'expr': 'invalid'})
        self.add_job('good')
        self.assertEqual(main(['tick']), 3)
        self.assertEqual(self.saved('good')['lastStatus'], 'ok')
        self.assertIn('FAILED: bad', self.stderr.getvalue())

    def test_backend_exit_four_is_failure_not_lock_skip(self):
        self.add_job(prompt='raise SystemExit(4)')
        self.assertEqual(main(['tick']), 3)
        self.assertEqual(self.saved()['lastExit'], 4)

    def test_overlapping_dispatch_skips_without_updating_state(self):
        job = self.add_job()
        with job_lock('demo'):
            self.assertEqual(main(['tick']), 0)
        self.assertEqual(self.saved(), job)
        self.assertEqual(main(['tick']), 0)
        with patch('schedule_agent.cli.run_job') as runner:
            self.assertEqual(_run_stored_job('demo', scheduled=True), 0)
            runner.assert_not_called()

    def test_removed_job_is_not_recreated(self):
        self.add_job()
        def remove(job, **kwargs):
            delete_job(job['id'])
            return 0, None
        with patch('schedule_agent.cli.run_job', side_effect=remove):
            self.assertEqual(main(['tick']), 0)
        self.assertEqual(load_registry()['jobs'], {})

    def test_replaced_job_is_not_overwritten_by_old_result(self):
        self.add_job()
        def replace(job, **kwargs):
            upsert_job({**job, 'prompt': 'replacement'}, replace=True)
            return 0, None
        with patch('schedule_agent.cli.run_job', side_effect=replace):
            self.assertEqual(main(['tick']), 0)
        self.assertEqual(self.saved()['prompt'], 'replacement')
        self.assertNotIn('lastStatus', self.saved())

    def test_start_time_preserves_occurrence_during_a_long_run(self):
        started = datetime.now().astimezone() - timedelta(hours=2)
        job = self.add_job()
        _record_run(job, 0, None, started=started)
        self.assertEqual(parse_iso(self.saved()['lastRun']), started.replace(microsecond=0))
        self.assertGreater(parse_iso(self.saved()['lastFinishedAt']), parse_iso(self.saved()['lastRun']))

    def test_dry_run_never_executes_or_changes_job(self):
        job = self.add_job()
        with patch('schedule_agent.cli.run_job') as runner:
            self.assertEqual(main(['tick', '--dry-run']), 0)
            runner.assert_not_called()
        self.assertEqual(self.saved(), job)

    def test_manual_run_records_failure_and_completes_on_success(self):
        self.add_job(prompt='raise SystemExit(1)')
        self.assertEqual(main(['run', 'demo']), 3)
        with patch('schedule_agent.cli.run_job', return_value=(0, None)):
            self.assertEqual(main(['run', 'demo']), 0)
        self.assertFalse(self.saved()['enabled'])

    def test_timeout_preserves_partial_output_and_spawned_id(self):
        job = self.add_job(chatId=None)
        command = [sys.executable, '-u', '-c',
                   'import time; print(\'{"session_id":"spawned-before-timeout"}\', flush=True); print("partial", flush=True); time.sleep(5)']
        with patch('schedule_agent.agent_run.parse_timeout', return_value=.2):
            code, spawned = _exec(job, command)
        self.assertEqual(code, 124)
        self.assertEqual(spawned, 'spawned-before-timeout')
        output = log_path('demo').read_text()
        self.assertIn('partial', output)
        self.assertIn('END exit=124', output)
        self.assertIn('timed out', output)

    def test_output_reaches_log_before_process_finishes(self):
        job = self.add_job()
        marker = self.root / 'release'
        command = [sys.executable, '-u', '-c',
                   'import pathlib,time; print("live output", flush=True); '
                   f'p=pathlib.Path({str(marker)!r}); '
                   '\nwhile not p.exists(): time.sleep(.01)']
        result = []
        thread = threading.Thread(target=lambda: result.append(_exec(job, command)))
        thread.start()
        try:
            import time
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if log_path('demo').exists() and 'live output' in log_path('demo').read_text():
                    break
                time.sleep(.01)
            self.assertIn('live output', log_path('demo').read_text())
            self.assertTrue(thread.is_alive())
        finally:
            marker.touch()
            thread.join(timeout=3)
        self.assertEqual(result, [(0, None)])


if __name__ == '__main__':
    unittest.main()
