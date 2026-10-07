from __future__ import annotations

from pathlib import Path
import os
import shutil
import pytest

pytestmark = pytest.mark.skipif(
    os.name == 'nt' or shutil.which('bash') is None,
    reason='Requires POSIX executable scripts and Bash; run on Linux, macOS, or WSL',
)

from prismatoid_batch.helper_scripts import run_helper
from prismatoid_batch.legacy_runner import run_legacy_solver


def _write_fake_sage(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import os
import runpy
import sys

if '-python' in sys.argv[1:]:
    print('unsupported -python reached fake Sage', file=sys.stderr)
    raise SystemExit(97)
if any(arg.startswith('-') for arg in sys.argv[2:]):
    print('option argument leaked through Sage parser', file=sys.stderr)
    raise SystemExit(98)
if len(sys.argv) < 2:
    raise SystemExit(2)
os.environ['FAKE_SAGE_SCRIPT_MODE'] = '1'
script = sys.argv[1]
sys.argv = [script] + sys.argv[2:]
runpy.run_path(script, run_name='__main__')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_legacy_runner_uses_sage_script_mode_and_strips_old_flag(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(source_root / "prismatoid_batch", project / "prismatoid_batch")
    entrypoint = project / "legacy.py"
    entrypoint.write_text("print('legacy wrapper reached')\n", encoding="utf-8")
    candidate = tmp_path / "0001"
    candidate.write_text("0 1 2\n3 4 5\n", encoding="utf-8")
    fake_sage = tmp_path / "sage"
    _write_fake_sage(fake_sage)

    record = run_legacy_solver(
        project,
        candidate,
        "0001",
        tmp_path / "work",
        entrypoint=entrypoint,
        # Also verify backward compatibility with a previously saved command.
        interpreter=f"{fake_sage} -python",
        timeout=30,
        keep_sandbox=True,
    )

    assert record.returncode == 0, record.stderr
    assert "legacy wrapper reached" in record.stdout
    assert "-python" not in record.command
    assert record.command[0] == str(fake_sage)
    assert record.command[1].endswith("legacy_wrapper.py")
    assert len(record.command) == 2


def test_preprocessing_helper_uses_sage_script_mode(tmp_path, monkeypatch):
    fake_sage = tmp_path / "sage"
    _write_fake_sage(fake_sage)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

    helper = tmp_path / "helper.py"
    helper.write_text(
        """import os
from pathlib import Path
if os.environ.get('FAKE_SAGE_SCRIPT_MODE') != '1':
    raise SystemExit(7)
Path(os.environ['PRISMATOID_OUTPUT']).write_text('0 1 2\\n2 3 4\\n', encoding='utf-8')
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("1 2 3\n3 4 5\n", encoding="utf-8")
    output = tmp_path / "prepared" / "candidate.txt"
    output.parent.mkdir()

    result = run_helper(helper, candidate, output, timeout=30)

    assert result.returncode == 0, result.stderr
    assert result.output == output
    assert output.read_text(encoding="utf-8") == "0 1 2\n2 3 4\n"
    assert "-python" not in result.command
    assert Path(result.command[0]).name == "sage"


def test_top_level_shell_launcher_bypasses_sage_option_parser(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    fake_sage = tmp_path / "sage"
    _write_fake_sage(fake_sage)

    import subprocess
    env = os.environ.copy()
    env["SAGE_BIN"] = str(fake_sage)
    completed = subprocess.run(
        ["bash", str(source_root / "run_prismatoid_batch.sh"), "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Batch non-realizability certificate search" in completed.stdout


def test_shell_launcher_preserves_option_arguments_and_spaced_paths(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    fake_sage = tmp_path / "sage"
    _write_fake_sage(fake_sage)
    data = tmp_path / "data set with spaces"
    data.mkdir()
    (data / "0001").write_text("0 1 2\n3 4 5\n0 1 3 4\n", encoding="utf-8")

    import subprocess
    env = os.environ.copy()
    env["SAGE_BIN"] = str(fake_sage)
    completed = subprocess.run(
        [
            "bash",
            str(source_root / "run_prismatoid_batch.sh"),
            "validate-data",
            "--data",
            str(data),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "candidates=1 invalid=0" in completed.stdout
