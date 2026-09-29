import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import candidate
import release
from deploy import Engine
from test_release import FakeEngine, manifest, snapshot


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, release.ROOT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ssm = module('ssm_deploy', 'ssm-deploy.py')
pinning = module('pin_manifest', 'pin-manifest.py')


class VersionTests(unittest.TestCase):
    def test_initial_human_pin_can_fill_digests_without_changing_images(self):
        before, after = manifest(), manifest()
        before['digests'] = dict.fromkeys(release.SERVICES)
        before['sources']['backend']['run_id'] = None
        candidate.validate_transition(before, after, is_bot=False)
        with self.assertRaisesRegex(ValueError, 'human PR'):
            candidate.validate_transition(before, after, is_bot=True)

    def test_initial_pin_cannot_also_change_the_backend_version(self):
        before, after = manifest(), manifest()
        before['digests'] = dict.fromkeys(release.SERVICES)
        after['images']['backend'] = 'b' * 40
        after['sources']['backend']['sha'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'preserving'):
            candidate.validate_transition(before, after, is_bot=False)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            release.loads('{"backend":1,"backend":2}')

    def test_changed_ecr_tag_is_not_silently_re_pinned(self):
        m = manifest()
        with patch('release.lookup_digest', return_value='sha256:' + 'b' * 64):
            with self.assertRaisesRegex(ValueError, 'reviewed manifest'):
                release.resolve_images(m, {}, '602601433533')

    def test_resolution_uses_reviewed_digests(self):
        m = manifest()
        with patch('release.lookup_digest', return_value='sha256:' + 'a' * 64):
            result = release.resolve_images(m, {}, '602601433533')
        self.assertEqual(set(result), release.SERVICES)
        self.assertTrue(all('@sha256:' in value for value in result.values()))

    def test_non_backend_digest_change_rejected(self):
        before, after = manifest(), manifest()
        after['digests']['frontend'] = 'sha256:' + 'b' * 64
        with self.assertRaisesRegex(ValueError, 'Only Backend'):
            release.require_backend_only(before, after)

    def test_initial_pin_preserves_all_image_versions(self):
        m = manifest()
        m['digests'] = dict.fromkeys(release.SERVICES)
        m['sources']['backend']['run_id'] = None
        policy = {'backend': {'repository': 'owner/backend', 'workflow': '.github/workflows/ci.yml'}}
        ci = {'id': 123, 'path': policy['backend']['workflow'], 'head_sha': 'a' * 40}
        with patch.object(pinning, 'github', return_value={'workflow_runs': [ci]}), \
             patch.object(pinning, 'verify_source') as verify, \
             patch.object(pinning, 'lookup_digest', return_value='sha256:' + 'a' * 64):
            result = pinning.pin(m, policy, 'token')
        self.assertEqual(m['images'], result['images'])
        self.assertIsNone(m['sources']['backend']['run_id'])
        self.assertEqual(123, result['sources']['backend']['run_id'])
        verify.assert_called_once_with('backend', result['sources']['backend'], policy, 'token', latest=False)
        release.validate_manifest(result)

    def test_dev_build_is_rejected(self):
        ci = {'head_sha': 'a' * 40, 'head_branch': 'dev'}
        policy = {'backend': {'repository': 'owner/backend', 'workflow': '.github/workflows/ci.yml'}}
        with patch('release.github', return_value=ci):
            with self.assertRaisesRegex(ValueError, 'main push'):
                release.verify_source('backend', {'sha': 'a' * 40, 'run_id': 1}, policy, 'token')

    def test_non_backend_candidate_rejected_before_github_write(self):
        for group in ('frontend', 'ai', 'worker'):
            event = {'sender': {'login': 'bot'}, 'client_payload': {'group': group, 'sha': 'a' * 40, 'run_id': 1}}
            with patch.dict(os.environ, {'CD_BOT_LOGIN': 'bot'}), patch('candidate.github') as api:
                with self.assertRaises(ValueError):
                    candidate.create(event, 'repo', 'token', 'source', {})
                api.assert_not_called()

    def test_backend_candidate_preserves_other_versions_and_pins_digest(self):
        baseline = manifest()
        event = {'sender': {'login': 'bot'}, 'client_payload': {'group': 'backend', 'sha': 'b' * 40, 'run_id': 22}}
        def api(path, token, method='GET', data=None):
            if path.endswith('/git/ref/heads/main'):
                return {'object': {'sha': 'c' * 40}}
            if '/pulls?' in path:
                return []
            if method == 'POST' and path.endswith('/pulls'):
                return {'html_url': 'https://example.test/pr/1'}
            return {}
        policy = {'backend': {'repository': 'owner/backend'}}
        with patch.dict(os.environ, {'CD_BOT_LOGIN': 'bot', 'AWS_ACCOUNT_ID': '602601433533'}), \
             patch('candidate.github', side_effect=api) as calls, \
             patch('candidate.get_file', return_value=(baseline, 'blob')), \
             patch('candidate.verify_source'), patch('candidate.resolve_images'), \
             patch('candidate.lookup_digest', return_value='sha256:' + 'b' * 64):
            candidate.create(event, 'owner/cloud', 'token', 'source', policy)
        put = next(c for c in calls.call_args_list if len(c.args) > 2 and c.args[2] == 'PUT')
        import base64
        after = json.loads(base64.b64decode(put.args[3]['content']))
        release.require_backend_only(baseline, after)
        self.assertEqual('b' * 40, after['images']['backend'])
        self.assertEqual('sha256:' + 'b' * 64, after['digests']['backend'])
        self.assertEqual(22, after['sources']['backend']['run_id'])


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = FakeEngine(self.tmp.name)
        self.actual = {s: {'Config': {'Labels': {'com.docker.compose.config-hash': s + '-hash'}}}
                       for s in release.SERVICES}

    def adopt(self):
        hashes = '\n'.join(s + ' ' + s + '-hash' for s in release.SERVICES)
        with patch.object(self.engine, 'check_actual', return_value=self.actual), \
             patch.object(self.engine, 'compose', return_value=hashes):
            return self.engine.adopt()

    def test_adopt_verifies_before_recording_without_replacement(self):
        self.assertEqual(0, self.adopt())
        self.assertEqual(self.engine.target, self.engine.read('current'))
        self.assertEqual('adopted', self.engine.read('result')['status'])
        self.assertFalse(any(c[0] == 'replace' for c in self.engine.calls))

    def test_adopt_refuses_config_drift_without_recording_success(self):
        self.actual['backend']['Config']['Labels']['com.docker.compose.config-hash'] = 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'configuration differs'):
            self.adopt()
        self.assertIsNone(self.engine.read('current'))

    def test_adopt_does_not_overwrite_existing_state(self):
        self.engine.write('current', snapshot())
        with self.assertRaisesRegex(RuntimeError, 'fresh state'):
            self.adopt()

    def test_failed_adopt_health_never_creates_current(self):
        self.engine.fail_verify = 1
        with self.assertRaises(RuntimeError):
            self.adopt()
        self.assertIsNone(self.engine.read('current'))

    def test_runtime_file_change_blocks_deploy_before_replacement(self):
        old = copy.deepcopy(self.engine.target)
        old['runtime_files'] = {'backend.env': 'old'}
        self.engine.write('current', old)
        self.engine.target['runtime_files'] = {'backend.env': 'changed'}
        with self.assertRaisesRegex(RuntimeError, 'Runtime files changed'):
            self.engine.deploy()
        self.assertFalse(any(c[0] == 'replace' for c in self.engine.calls))

    def test_sha_tag_adoption_compares_actual_image_identity(self):
        target = snapshot()
        actual = {s: {'Config': {'Image': s + ':old-sha'}, 'Image': 'sha256:image-id',
                      'State': {'Running': True, 'Health': {'Status': 'healthy'}}} for s in release.SERVICES}
        with patch.object(self.engine, 'inspect', return_value=actual), patch('deploy.run', return_value='sha256:image-id\n'):
            Engine.check_actual(self.engine, target)
        actual['backend']['Image'] = 'sha256:different'
        with patch.object(self.engine, 'inspect', return_value=actual), patch('deploy.run', return_value='sha256:image-id\n'):
            with self.assertRaisesRegex(RuntimeError, 'image drift'):
                Engine.check_actual(self.engine, target)


class DeliveryTests(unittest.TestCase):
    def test_delivery_archives_exact_commit_without_mutating_checkout(self):
        script = ssm.remote_command('a' * 40, 'deploy')
        self.assertIn("archive '" + 'a' * 40 + "'", script)
        self.assertIn('merge-base --is-ancestor', script)
        self.assertIn('flock', script)
        for forbidden in ('git checkout', 'git reset', 's3', 'DEPLOY_BUCKET'):
            self.assertNotIn(forbidden, script)

    def test_untrusted_revision_or_mode_cannot_enter_remote_shell(self):
        for revision, mode in [('$(id)', 'deploy'), ('a' * 40, 'deploy; id')]:
            with self.assertRaises(ValueError):
                ssm.remote_command(revision, mode)

    def test_ssm_success_requires_zero_response_code(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, json.dumps({'Status': 'Success', 'ResponseCode': 1}), '')
        with patch('subprocess.run', return_value=result), patch.object(ssm, 'save'):
            with self.assertRaisesRegex(RuntimeError, 'invocation failed'):
                ssm.wait_command('command', 'instance', sleep=lambda _: None)


if __name__ == '__main__':
    unittest.main()
