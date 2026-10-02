"""실제 AWS/Secret 없이 조회 실패, 파일 보존, JWT 적용 상태를 검증한다."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runtime", ROOT / "scripts/prepare-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def secrets():
    return {
        "Secret-v1-BE": {
            "DB_USERNAME": "keepgo_app", "DB_PASSWORD": "test-only-password",
            "JWT_PUBLIC_KEY": "-----BEGIN PUBLIC KEY-----\ntest-public\n-----END PUBLIC KEY-----\n",
            "JWT_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\ntest-private\n-----END PRIVATE KEY-----\n",
        },
        "Secret-v1-AI": {"GOOGLE_API_KEY": "test-only-api-key",
                         "NAVER_MAP_CLIENT_ID": "test-only-map-id", "NAVER_MAP_CLIENT_SECRET": "test-only-map-secret"},
                         "Secret-v1-FE": {"KAKAO_REST_API_KEY": "test-only-kakao-key"},
    }


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.data = secrets()
        for name, value in (("RUNTIME_DIR", base / "runtime"),
                            ("JWT_DIR", base / "runtime/jwt"),
                            ("STATE_DIR", base / "state")):
            mock = patch.object(runtime, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(runtime.os, "chown", create=True)
        mock.start()
        self.addCleanup(mock.stop)
        if os.name == "nt":
            # Windows read-only 속성은 Linux 디렉터리 기반 rename 권한과 다르다.
            mock = patch.object(runtime.os, "chmod")
            mock.start()
            self.addCleanup(mock.stop)

    def prepare(self):
        with patch.object(runtime, "read_secret", side_effect=lambda name: self.data[name]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                runtime.prepare()
        self.assertNotIn("test-only-password", output.getvalue())
        self.assertNotIn("test-private", output.getvalue())

    def files(self):
        return {str(p.relative_to(runtime.RUNTIME_DIR)): p.read_bytes()
                for p in runtime.RUNTIME_DIR.rglob("*") if p.is_file()}

    def test_lookup_failure_preserves_all_runtime_files(self):
        self.prepare()
        before = self.files()
        with patch.object(runtime, "read_secret", side_effect=[self.data["Secret-v1-BE"],
                          runtime.RuntimeError_("조회 실패")]):
            with self.assertRaises(runtime.RuntimeError_):
                runtime.prepare()
        self.assertEqual(before, self.files())

    def test_validation_failure_preserves_all_runtime_files(self):
        self.prepare()
        before = self.files()
        for key, bad in (("DB_PASSWORD", ""), ("DB_PASSWORD", "bad\nvalue"),
                         ("DB_PASSWORD", {"unexpected": "object"}),
                         ("JWT_PRIVATE_KEY", 123), ("JWT_PUBLIC_KEY", "invalid")):
            with self.subTest(key=key, bad=bad):
                self.data = secrets()
                self.data["Secret-v1-BE"][key] = bad
                with self.assertRaises(runtime.RuntimeError_):
                    self.prepare()
                self.assertEqual(before, self.files())

    def test_missing_naver_key_stops_before_writing(self):
        self.prepare()
        before = self.files()
        for key in ("NAVER_MAP_CLIENT_ID", "NAVER_MAP_CLIENT_SECRET"):
            with self.subTest(key=key):
                self.data = secrets()
                del self.data["Secret-v1-AI"][key]
                with self.assertRaises(runtime.RuntimeError_):
                    self.prepare()
                self.assertEqual(before, self.files())

    def test_sentry_dsn_is_passed_only_when_present_and_unlisted_keys_are_not(self):
        self.data["Secret-v1-AI"].update(SENTRY_DSN="https://key@sentry.example/1", UNLISTED_KEY="unused")
        self.prepare()
        ai_env = (runtime.RUNTIME_DIR / "ai.env").read_text()
        self.assertIn("SENTRY_DSN=https://key@sentry.example/1\n", ai_env)
        self.assertNotIn("UNLISTED_KEY", ai_env)
        self.data = secrets()
        self.prepare()  # 선택 키라 없어도 배포는 계속된다
        self.assertNotIn("SENTRY_DSN", (runtime.RUNTIME_DIR / "ai.env").read_text())

    def test_unchanged_files_keep_inode(self):
        self.prepare()
        path = runtime.JWT_DIR / "private_key.pem"
        inode = path.stat().st_ino
        with patch.object(runtime.os, "replace", wraps=os.replace) as replace:
            self.prepare()
        replace.assert_not_called()
        self.assertEqual(inode, path.stat().st_ino)

    def test_jwt_change_stays_pending_until_applied_even_after_resync(self):
        self.prepare()
        self.assertEqual(runtime.check_applied("backend", "container-old"), 1)
        runtime.record_applied("backend", "container-old")
        self.assertEqual(runtime.check_applied("backend", "container-old"), 0)
        self.data["Secret-v1-BE"]["JWT_PRIVATE_KEY"] = self.data["Secret-v1-BE"]["JWT_PRIVATE_KEY"].replace("test-private", "rotated-private")
        self.prepare()
        self.assertEqual(runtime.check_applied("backend", "container-old"), 1)
        self.prepare()  # pull 실패 이후 동일 Secret 재조회
        self.assertEqual(runtime.check_applied("backend", "container-old"), 1)
        runtime.record_applied("backend", "container-new")
        self.assertEqual(runtime.check_applied("backend", "container-new"), 0)
        self.assertEqual(runtime.check_applied("backend", "container-old"), 1)
        self.assertNotIn("rotated-private", (runtime.STATE_DIR / "runtime-applied-backend.json").read_text())

    def test_env_change_marks_only_affected_service(self):
        self.prepare()
        runtime.record_applied("backend", "container")
        runtime.record_applied("ai-api", "ai-container")
        self.data["Secret-v1-BE"]["DB_PASSWORD"] = "new-password"
        self.prepare()
        self.assertIn("new-password", (runtime.RUNTIME_DIR / "backend.env").read_text())
        self.assertEqual(runtime.check_applied("backend", "container"), 1)
        self.assertEqual(runtime.check_applied("ai-api", "ai-container"), 0)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is required (daemon is not used)")
    def test_env_change_is_detected_independently_of_compose_hash(self):
        self.prepare()
        runtime.record_applied("backend", "container")
        compose = runtime.RUNTIME_DIR.parent / "compose.yaml"
        compose.write_text("services:\n  backend:\n    image: example/backend:test\n    env_file:\n      - path: ./runtime/backend.env\n        format: raw\n", encoding="utf-8")

        def config_hash():
            result = subprocess.run(["docker", "compose", "-f", str(compose), "config", "--hash", "backend"],
                                    capture_output=True, text=True, check=True, timeout=20)
            return result.stdout.strip()

        before = config_hash()
        self.data["Secret-v1-BE"]["DB_PASSWORD"] = "new-password"
        self.prepare()
        self.assertTrue(before)
        self.assertTrue(config_hash())  # CLI 버전에 따라 같아도 자체 적용 기록이 변경을 감지해야 한다.
        self.assertEqual(runtime.check_applied("backend", "container"), 1)

    def test_corrupt_state_requires_reapply(self):
        self.prepare()
        runtime.record_applied("backend", "container")
        (runtime.STATE_DIR / "runtime-applied-backend.json").write_text("broken")
        self.assertEqual(runtime.check_applied("backend", "container"), 1)

    def test_aws_errors_are_redacted(self):
        for stdout, stderr, code in (("", "AccessDenied: sensitive", 1),
                                     ("", "ResourceNotFound: sensitive", 1),
                                     ("not-json-sensitive", "", 0),
                                     ("[]", "", 0)):
            result = subprocess.CompletedProcess([], code, stdout, stderr)
            with patch.object(runtime.subprocess, "run", return_value=result):
                with self.assertRaises(runtime.RuntimeError_) as error:
                    runtime.read_secret("Secret-v1-BE")
                self.assertNotIn("sensitive", str(error.exception))


if __name__ == "__main__":
    unittest.main()
