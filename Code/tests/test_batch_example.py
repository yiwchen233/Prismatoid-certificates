"""Exercise the real solver, saved proof, independent checker, and resume."""
import json
from pathlib import Path
import subprocess
import sys


def test_example_certificate_and_resume(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'results with spaces'
    command = [sys.executable, str(root / 'run_prismatoid_batch.py'), 'run',
               '--data', str(root / 'examples/prepared'),
               '--project', str(root / 'core'),
               '--entrypoint', str(root / 'core/src/nonrealizability_certificate.py'),
               '--output', str(output), '--prepare-mode', 'prepared',
               '--n-factors', '2', '--max-degree', '3',
               '--search-variant', 'all-variable-products-simplified',
               '--flag-attempts', '2', '--random-seed', '0',
               '--lp-solver', 'scipy-highs', '--timeout', '180']
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / 'certificates/0213.json').read_text())
    assert report['status'] == 'certificate_exact'
    proof = output / 'exact_proofs/0213.json'
    assert json.loads(proof.read_text())['verification']['status'] == 'verified_exact'
    checked = subprocess.run(
        [sys.executable, str(root / 'core/src/modules/verify_certificate.py'), str(proof)],
        capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert 'Verified 1/1' in checked.stdout
    before = proof.read_bytes(), proof.stat().st_mtime_ns
    resumed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert (proof.read_bytes(), proof.stat().st_mtime_ns) == before
