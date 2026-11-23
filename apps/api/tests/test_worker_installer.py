import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "worker_install", Path(__file__).resolve().parents[3] / "deploy/aws/remote_install.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_frozen_sync_uses_system_python_and_separate_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtimes"
    monkeypatch.setattr(installer, "RUNTIMES", root)
    runtime = root / "fixture"

    def create_runtime(argv, **kwargs):
        if "sync" in argv:
            runtime.mkdir()

    run = Mock(side_effect=create_runtime)
    monkeypatch.setattr(subprocess, "run", run)
    release = tmp_path / "releases/fixture"
    assert installer.prepare_runtime(release) == runtime
    bootstrap, pip, sync = run.call_args_list
    assert bootstrap.args[0][:3] == ["/usr/bin/python3.12", "-m", "venv"]
    assert pip.args[0][-1] == "uv==0.13.7"
    assert sync.args[0][1:] == ["sync", "--python", "/usr/bin/python3.12", "--no-managed-python",
                                "--no-python-downloads", "--frozen", "--no-dev", "--extra", "engine-media"]
    assert sync.kwargs["cwd"] == release
    env = sync.kwargs["env"]
    assert env["UV_PROJECT_ENVIRONMENT"] == str(runtime)
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    installer.prepare_runtime(release)
    assert run.call_count == 3


def test_installer_uv_sync_dry_run(tmp_path, monkeypatch):
    """Exercise the installer's sync options using its pinned uv and the real lockfile."""
    release = Path(__file__).resolve().parents[3]
    runtimes = tmp_path / "runtimes"
    system_python = os.environ.get("WORKER_INSTALL_TEST_PYTHON", sys._base_executable)
    monkeypatch.setattr(installer, "SYSTEM_PYTHON", system_python)
    monkeypatch.setattr(installer, "RUNTIMES", runtimes)
    uv = shutil.which("uv")
    assert uv, "Install the worker installer's pinned uv on PATH for the release check"
    run = subprocess.run
    version = run([uv, "--version"], check=True, capture_output=True, text=True).stdout.split()[1]
    syncs = []

    def dry_run(argv, **kwargs):
        if argv[1:3] == ["-m", "venv"]:
            return
        if argv[1:4] == ["-m", "pip", "install"]:
            assert argv[-1] == f"uv=={version}"
            return
        assert argv[1] == "sync"
        env = dict(kwargs["env"], UV_CACHE_DIR=str(tmp_path / "uv-cache"))
        run([uv, *argv[1:], "--dry-run"], **{**kwargs, "env": env})
        # prepare_runtime writes its marker after sync. A dry run creates no venv.
        Path(env["UV_PROJECT_ENVIRONMENT"]).mkdir()
        syncs.append(argv[1])

    monkeypatch.setattr(subprocess, "run", dry_run)
    installer.prepare_runtime(release)
    assert syncs == ["sync"]


@pytest.mark.parametrize("denied", ["lerny-worker", "lerny-code", None])
def test_account_checks_gate_activation(tmp_path, monkeypatch, capsys, denied):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz"):
        pass
    digest = hashlib.sha256(archive.getvalue()).hexdigest()
    release = tmp_path / digest
    runtime = tmp_path / "runtime"
    client = Mock()
    client.get_object.return_value = {"Body": io.BytesIO(archive.getvalue())}
    client.get_parameter.return_value = {"Parameter": {"Value": '{"LERNY_GEMINI_CALLS_ENABLED":"false"}'}}
    monkeypatch.setattr(installer.boto3, "client", lambda *a, **kw: client)
    monkeypatch.setattr(installer, "RELEASES", tmp_path)
    monkeypatch.setattr(installer, "prepare_runtime", lambda r: runtime)
    activate = Mock()
    monkeypatch.setattr(installer, "activate", activate)
    monkeypatch.setattr(sys, "argv", ["install", "bucket", "key", digest, "region"])
    checked = []

    def probe(argv, **kwargs):
        if argv[0] != "runuser":
            assert argv[-1].endswith("install_media.py")
            return
        account = argv[2]
        checked.append(account)
        assert argv[:6] == ["runuser", "-u", account, "--", "env", "-i"]
        assert runtime / "bin/python" in argv and release / "apps/api" in argv
        assert "lerny.tracing.cloud_worker" in argv if account == "lerny-code" else "lerny.material_daemon" in argv
        assert kwargs["check"] and kwargs["cwd"] == "/"
        if denied == account:
            raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(subprocess, "run", probe)
    if denied:
        with pytest.raises(subprocess.CalledProcessError):
            installer.main()
        activate.assert_not_called()
    else:
        installer.main()
        activate.assert_called_once()
    assert checked == (["lerny-worker"] if denied == "lerny-worker" else ["lerny-worker", "lerny-code"])
    result = json.loads(capsys.readouterr().out)
    assert result["installed"] is (denied is None) and result["services_started"] is False
