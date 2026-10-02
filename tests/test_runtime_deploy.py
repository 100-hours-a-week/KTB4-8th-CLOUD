"""실제 deploy.sh를 가짜 Docker/AWS와 임시 runtime에서 실행하는 회귀 시험."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_runtime import ROOT, secrets

BASH = (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))

FAKE = r'''
import importlib.util, json, os, sys, time, uuid
from pathlib import Path
sys.stdout.reconfigure(newline="\n")
base = Path(os.environ["FIXTURE"])
config = json.loads((base / "fixture.json").read_text())
args = sys.argv[2:]
tool = sys.argv[1]
# AWS → docker login 파이프의 두 프로세스가 Windows에서 같은 로그를 덮어쓰지 않게 한다.
(base / "calls" / f"{time.time_ns()}-{uuid.uuid4().hex}.json").write_text(json.dumps([tool] + args))
if tool == "python3":
    if args[0].endswith("prepare-runtime.py"):
        spec = importlib.util.spec_from_file_location("runtime", base / "scripts/prepare-runtime.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.RUNTIME_DIR = base / "runtime"
        module.JWT_DIR = base / "runtime/jwt"
        module.os.geteuid = lambda: 0
        module.os.chown = lambda *a: None
        if os.name == "nt":
            module.os.chmod = lambda *a: None
        def read_secret(name):
            if config.get("fail_prepare"):
                raise module.RuntimeError_("simulated lookup failure")
            return config["secrets"][name]
        module.read_secret = read_secret
        sys.argv = args
        try:
            sys.exit(module.main())
        except (module.RuntimeError_, OSError):
            sys.exit(2)
    if args[0] == "-":
        sys.argv = args
        exec(compile(sys.stdin.read(), "<stdin>", "exec"))
        sys.exit(0)
    os.execv(sys.executable, [sys.executable] + args)
if tool == "aws":
    print("fake-login")
    sys.exit(0)
if tool == "curl":
    sys.exit(0)
if tool == "docker":
    if args[0] == "login":
        sys.stdin.read()
    elif args[0] == "inspect":
        template, cid = args[2], args[3]
        service = next(k for k,v in config["containers"].items() if v == cid)
        if "config-hash" in template:
            print(config["current"][service])
        elif "Config.Image" in template:
            print("registry/" + service + ":" + "a" * 40)
        elif "RestartCount" in template:
            print(0)
        else:
            print("healthy")
    elif args[0] == "compose":
        args = args[3:]
        if args[0] == "config" and "--hash" in args:
            if config.get("fail_hash"):
                sys.exit(1)
            for service, value in config["desired"].items():
                print(service, value)
        elif args[0] == "ps" and "-aq" in args:
            print(config["containers"][args[-1]])
        elif args[0] == "pull" and config.get("fail_pull"):
            sys.exit(1)
        elif args[0] == "up":
            assert "--force-recreate" in args
            service = args[-1]
            config["containers"][service] += "-new"
            # 실제 Compose는 env_file 값까지 넣어 라벨을 만들어 `config --hash`와 달라진다(EC2에서 확인).
            suffix = "+env" if service in ("backend", "ai-api") else ""
            config["current"][service] = config["desired"][service] + suffix
            fail = config.pop("fail_up_once", False)
            (base / "fixture.json").write_text(json.dumps(config))
            if fail:
                sys.exit(1)
sys.exit(0)
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required")
class RuntimeDeployTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for directory in ("scripts", "deployment", "bin", "state", "calls", "host/tls", "host/acme", "host/data/uploads"):
            (self.base / directory).mkdir(parents=True)
        for name in ("fullchain.pem", "privkey.pem"):
            (self.base / "host/tls" / name).write_text("test-only-certificate\n")
        for script in ("deploy.sh", "prepare-runtime.py"):
            shutil.copyfile(ROOT / "scripts" / script, self.base / "scripts" / script)
        services = ("ai-api", "backend", "frontend", "web")
        (self.base / "deployment/production-manifest.json").write_text(json.dumps({"images": {s: "a" * 40 for s in services}}))
        (self.base / "fake.py").write_text(FAKE, encoding="utf-8")
        for tool in ("docker", "aws", "curl", "python3"):
            path = self.base / "bin" / tool
            path.write_text('#!/usr/bin/env bash\nexec "' + Path(sys.executable).as_posix() + '" "' + (self.base / "fake.py").as_posix() + '" ' + tool + ' "$@"\n', encoding="utf-8", newline="\n")
            path.chmod(0o755)
        if os.name == "nt":
            # Git Bash에는 flock이 없다. Linux CI에서는 실제 flock을 사용한다.
            (self.base / "bin/flock").write_text("#!/usr/bin/env bash\nexit 0\n", newline="\n")
        self.config = {"secrets": secrets(), "current": {s: s for s in services},
                       "desired": {s: s for s in services}, "containers": {s: s + "-old" for s in services}}
        self.env = dict(os.environ, FIXTURE=str(self.base), STATE_DIR=(self.base / "state").as_posix(),
                        HOST_DIR=(self.base / "host").as_posix(),
                        AWS_ACCOUNT_ID="000000000000", BAKE_SECONDS="0", PYTHONUTF8="1")
        self.env["PATH"] = str(self.base / "bin") + os.pathsep + self.env["PATH"]
        self.save()

    def save(self):
        (self.base / "fixture.json").write_text(json.dumps(self.config))

    def run_deploy(self):
        # Git Bash가 Windows PATH 앞에 자체 /usr/bin을 넣으므로 셸 안에서 fixture를 우선한다.
        prefix = '$(cygpath -u "$FIXTURE")' if os.name == "nt" else '$FIXTURE'
        command = 'export PATH="' + prefix + '/bin:$PATH"; exec bash "$1"'
        result = subprocess.run([BASH, "-c", command, "runtime-test", (self.base / "scripts/deploy.sh").as_posix()], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.config = json.loads((self.base / "fixture.json").read_text())
        self.assertNotIn("test-only-password", result.stdout + result.stderr)
        self.assertNotIn("test-private", result.stdout + result.stderr)
        return result

    def calls(self):
        return [json.loads(path.read_text()) for path in sorted((self.base / "calls").glob("*.json"))]

    def clear_calls(self):
        for path in (self.base / "calls").glob("*.json"):
            path.unlink()

    def establish(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.clear_calls()

    def test_lookup_failure_stops_before_docker_and_keeps_files(self):
        self.establish()
        before = (self.base / "runtime/backend.env").read_bytes()
        self.config["fail_prepare"] = True
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("runtime_prepare_failed", result.stdout)
        self.assertFalse(any(c[0] == "docker" for c in self.calls()))
        self.assertEqual(before, (self.base / "runtime/backend.env").read_bytes())

    def test_first_run_establishes_runtime_then_no_change_is_noop(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["ai-api", "backend", "frontend"])
        self.clear_calls()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unchanged", result.stdout)
        self.assertFalse(any("up" in c for c in self.calls()))

    def test_jwt_only_change_is_applied_on_retry_after_pull_failure(self):
        self.establish()
        old_record = (self.base / "state/runtime-applied-backend.json").read_bytes()
        self.config["secrets"]["Secret-v1-BE"]["JWT_PRIVATE_KEY"] = secrets()["Secret-v1-BE"]["JWT_PRIVATE_KEY"].replace("test-private", "new-private")
        self.config["fail_pull"] = True
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("pull_failed", result.stdout)
        self.assertFalse(any("up" in c for c in self.calls()))
        self.assertEqual(old_record, (self.base / "state/runtime-applied-backend.json").read_bytes())
        self.config["fail_pull"] = False
        self.save()
        self.clear_calls()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["backend"])
        self.clear_calls()
        result = self.run_deploy()
        self.assertIn("unchanged", result.stdout)

    def test_missing_host_paths_stop_before_secret_lookup_and_docker(self):
        for path in ("host/tls/privkey.pem", "host/acme", "host/data/uploads"):
            with self.subTest(path=path):
                self.setUp()
                target = self.base / path
                target.unlink() if target.is_file() else target.rmdir()
                result = self.run_deploy()
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("host_files_missing", result.stdout)
                self.assertFalse(any(c[0] == "docker" for c in self.calls()))
                self.assertFalse((self.base / "runtime").exists())

    def test_hash_failure_stops_before_pull(self):
        self.config["fail_hash"] = True
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("invalid_compose", result.stdout)
        self.assertFalse(any("pull" in c or "up" in c for c in self.calls()))

    def test_failed_recreate_rolls_back_and_records_actual_container(self):
        self.establish()
        self.config["secrets"]["Secret-v1-BE"]["DB_PASSWORD"] = "changed-password"
        self.config["fail_up_once"] = True
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("rolled_back", result.stdout)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["backend", "backend"])
        record = json.loads((self.base / "state/runtime-applied-backend.json").read_text())
        self.assertEqual(record["container_id"], self.config["containers"]["backend"])
        self.assertEqual((self.base / "state/applied-config-backend").read_text().split()[0],
                         self.config["containers"]["backend"])
        self.assertEqual((self.base / "state/failed-images").read_text(), "")

    def test_env_file_label_mismatch_does_not_recreate_again(self):
        # 2026-09-30 운영: 변경 없는 두 번째 배포가 backend·ai-api를 다시 교체했다.
        self.establish()
        self.assertNotEqual(self.config["current"]["backend"], self.config["desired"]["backend"])
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unchanged", result.stdout)
        self.assertFalse(any("up" in c for c in self.calls()))

    def test_config_change_recreates_only_that_service_once(self):
        self.establish()
        self.config["desired"]["backend"] = "backend-v2"
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["backend"])
        self.clear_calls()
        result = self.run_deploy()
        self.assertIn("unchanged", result.stdout)

    def test_container_recreated_outside_deploy_falls_back_to_label_once(self):
        self.establish()
        self.config["containers"]["backend"] = "backend-manual"  # 기록과 다른 컨테이너
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["backend"])
        self.clear_calls()
        result = self.run_deploy()
        self.assertIn("unchanged", result.stdout)

    def test_blocked_backend_does_not_record_unapplied_jwt(self):
        (self.base / "state/failed-images").write_text("backend " + "a" * 40 + "\n")
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.base / "state/runtime-applied-backend.json").exists())
        self.assertFalse(any("up" in c and c[-1] == "backend" for c in self.calls()))

    def test_ai_env_change_recreates_only_ai_even_when_compose_hash_matches(self):
        self.establish()
        self.config["secrets"]["Secret-v1-AI"]["GOOGLE_API_KEY"] = "changed-api-key"
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["ai-api"])
    def test_frontend_env_change_recreates_only_frontend(self):
        self.establish()
        self.config["secrets"]["Secret-v1-FE"]["KAKAO_REST_API_KEY"] = "changed-kakao-key"
        self.save()
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c[-1] for c in self.calls() if "up" in c], ["frontend"])
        self.assertNotIn("changed-kakao-key", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
