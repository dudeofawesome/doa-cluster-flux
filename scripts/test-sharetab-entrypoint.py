#!/usr/bin/env python3
"""Exercise the patched upstream entrypoint without a database or root access."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(sys.argv.pop(1)).resolve()


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = self.root / 'app'
        self.app.mkdir()
        for directory in ('migrations', 'after-push'):
            folder = self.app / 'prisma' / directory
            folder.mkdir(parents=True)
            (folder / 'test.sql').write_text('SELECT 1;')
        self.home = self.root / 'home'
        self.home.mkdir()
        machine_id = self.root / 'machine-id'
        machine_id.write_text('test-machine-id')
        script = (SOURCE / 'docker/entrypoint.sh').read_text()
        script = script.replace('/etc/machine-id', str(machine_id))
        script = script.replace('/app/', str(self.app) + '/')
        script = script.replace('/data/', str(self.root / 'data') + '/')
        self.entrypoint = self.root / 'entrypoint.sh'
        self.entrypoint.write_text(script)
        self.events = self.root / 'events.jsonl'
        node = self.root / 'node'
        node.write_text(f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
with open(os.environ['EVENTS'], 'a') as out:
    out.write(json.dumps({{'args': args, 'pid': os.getpid(),
        'env': {{key: os.environ.get(key) for key in
            ('UPLOAD_DIR', 'CLAUDE_DIR', 'OPENAI_CODEX_DIR', 'DB_MODE')}}}}) + '\\n')
if os.environ.get('FAIL_STEP') in args:
    sys.exit(23)
''')
        node.chmod(0o755)
        # Runtime startup must never try privilege switching or bundled Postgres.
        for command in ('su-exec', 'chown', 'initdb', 'pg_ctl', 'psql'):
            stub = self.root / command
            stub.write_text('#!/bin/sh\nexit 99\n')
            stub.chmod(0o755)
        self.env = {
            'PATH': str(self.root) + os.pathsep + os.defpath,
            'HOME': str(self.home),
            'NEXTAUTH_SECRET': 'test-nextauth-secret',
            'AUTH_SECRET': 'test-auth-secret',
            'DATABASE_URL': 'postgresql://test:test@database/sharetab',
            'EVENTS': str(self.events),
        }

    def run_entrypoint(self, **env):
        process = subprocess.Popen(
            ['sh', str(self.entrypoint)], env=self.env | env,
            cwd=self.app, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
        output, _ = process.communicate(timeout=10)
        events = [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []
        return process, output, events

    def test_startup_order_storage_and_exec(self):
        process, output, events = self.run_entrypoint()
        self.assertEqual(process.returncode, 0, output)
        self.assertEqual([event['args'] for event in events[:5]], [
            [str(self.app / 'db.mjs'), 'wait'],
            [str(self.app / 'db.mjs'), 'check-schema', str(self.app / 'prisma/schema.prisma')],
            [str(self.app / 'db.mjs'), 'run', str(self.app / 'prisma/migrations/test.sql')],
            ['/prisma-cli/node_modules/prisma/build/index.js', 'db', 'push'],
            [str(self.app / 'db.mjs'), 'run', str(self.app / 'prisma/after-push/test.sql')],
        ])
        server = events[-1]
        self.assertEqual(server['args'], ['server.js'])
        self.assertEqual(server['pid'], process.pid)
        self.assertEqual(server['env'], {
            'UPLOAD_DIR': str(self.root / 'data/uploads'),
            'CLAUDE_DIR': str(self.root / 'data/claude'),
            'OPENAI_CODEX_DIR': str(self.root / 'data/chatgpt'),
            'DB_MODE': 'external',
        })
        self.assertTrue((self.root / 'data/uploads/receipts').is_dir())
        self.assertEqual((self.home / '.claude').resolve(), self.root / 'data/claude')

    def test_database_url_required(self):
        process, output, events = self.run_entrypoint(DATABASE_URL='')
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('DATABASE_URL must point to the external PostgreSQL database', output)
        self.assertEqual(events, [])

    def test_failed_database_steps_stop_startup(self):
        for step in ('wait', 'check-schema', 'run', 'push'):
            with self.subTest(step=step):
                self.events.unlink(missing_ok=True)
                process, output, events = self.run_entrypoint(FAIL_STEP=step)
                self.assertEqual(process.returncode, 23, output)
                self.assertNotIn(['server.js'], [event['args'] for event in events])


if __name__ == '__main__':
    unittest.main()
