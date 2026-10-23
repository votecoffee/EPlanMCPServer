import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from scripts import launcher


def test_installer_plan_preserves_paths_and_has_no_activation(tmp_path, monkeypatch):
    repo = tmp_path / "source repo cafÃ©"
    repo.mkdir()
    (repo / ".venv/Scripts").mkdir(parents=True)
    (repo / ".venv/Scripts/python.exe").write_bytes(b"fixture")
    monkeypatch.setattr(launcher, "REPO", repo)
    monkeypatch.setattr(launcher, "stage", lambda *a: repo / "reviewed wheels")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "uv fixture.exe")
    calls = []
    monkeypatch.setattr(launcher, "install", calls.append)
    assert launcher.main(["--install-only", "--offline", "--root", "drawing=C:\\Design Files\\Î±"]) == 0
    assert calls[-1][-2:] == ["--root", "drawing=C:\\Design Files\\Î±"]
    assert all("codex" not in str(command[0]).lower() for command in calls)
    assert not any("serve" in command for command in calls)
    assert "--require-hashes" in calls[0] and "--offline" in calls[0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CMD forwarding")
def test_real_cmd_forwarding_spaces_failure_and_help(tmp_path):
    repo = tmp_path / "installer space cafÃ©"
    repo.mkdir()
    (repo / "scripts").mkdir()
    source = Path(__file__).resolve().parents[1]
    for name in ("Install.cmd", "InstallAndRun.cmd"):
        shutil.copyfile(source / name, repo / name)
    venv.EnvBuilder(with_pip=False).create(repo / ".venv")
    (repo / "scripts/launcher.py").write_text(
        'import sys,json;from pathlib import Path;Path("argv.json").write_text(json.dumps(sys.argv[1:]));print("fixture help" if "--help" in sys.argv else "fixture");sys.exit(37 if "--fail" in sys.argv else 0)',
        encoding="utf-8",
        newline="\n",
    )

    def run(name, *args):
        command = 'cmd.exe /d /s /c ""' + str(repo / name) + '" ' + subprocess.list2cmdline(list(args)) + '"'
        return subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)

    result = run("Install.cmd", "--root", "drawing=C:\\Design Files\\Î±", "--fail")
    assert result.returncode == 37, result.stdout + result.stderr
    assert json.loads((repo / "argv.json").read_text()) == [
        "--install-only",
        "--root",
        "drawing=C:\\Design Files\\Î±",
        "--fail",
    ]
    assert run("InstallAndRun.cmd", "--help").returncode == 0
    # Exercise the actual public parser too, without invoking installation.
    shutil.copyfile(source / "scripts/launcher.py", repo / "scripts/launcher.py")
    shutil.copyfile(source / "scripts/framework_dependency.py", repo / "scripts/framework_dependency.py")
    result = run("Install.cmd", "--help")
    assert result.returncode == 0 and "framework-wheel" in result.stdout
    assert run("Install.cmd", "--unknown-fixture-argument").returncode == 2
    assert (
        run(
            "Install.cmd", "--framework-wheel", str(tmp_path / "missing wheel folder" / "missing.whl")
        ).returncode
        == 1
    )
    assert run("Install.cmd", "--stdio").returncode == 2


def test_configure_cannot_activate_oda(tmp_path, monkeypatch):
    from scripts import configure

    monkeypatch.setattr(configure, "__file__", str(tmp_path / "scripts" / "configure.py"))
    monkeypatch.setattr(
        sys, "argv", ["configure.py", "--root", "fixture=C:\\Synthetic", "--oda", "not-run.exe"]
    )
    with pytest.raises(SystemExit) as error:
        configure.main()
    assert error.value.code == 2
    assert not (tmp_path / ".local").exists()
