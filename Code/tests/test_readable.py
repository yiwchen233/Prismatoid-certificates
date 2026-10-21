from pathlib import Path
import subprocess,sys,shutil
import pytest
from human_certificate import read_certificate,verify_bundle,monomial,parse_poly,polynomial
import re

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def example(tmp_path_factory):
    output=tmp_path_factory.mktemp('readable')/'results'
    command=[sys.executable,str(ROOT/'run_prismatoid_batch.py'),'run','--data',str(ROOT/'examples/prepared'),
             '--output',str(output),'--lp-solver','scipy-highs','--flag-attempts','2','--timeout','180']
    done=subprocess.run(command,text=True,capture_output=True,timeout=240)
    assert done.returncode==0,done.stdout+done.stderr
    return output,command

def test_roundtrip_and_final_files(example):
    output,_=example
    b=read_certificate(output/'certificates/0213.txt')
    assert verify_bundle(b)['status']=='verified_exact'
    assert all(f.suffix=='.txt' for f in output.rglob('*') if f.is_file())
    assert len(list((output/'intermediate/0213').iterdir()))==4
    assert not (output/'inconclusive/0213.txt').exists()

def test_resume_and_settings_lock(example):
    output,command=example;path=output/'certificates/0213.txt';before=path.stat().st_mtime_ns
    done=subprocess.run(command,text=True,capture_output=True,timeout=60)
    assert done.returncode==0,done.stderr
    assert path.stat().st_mtime_ns==before
    altered=command+['--max-degree','2']
    assert subprocess.run(altered,capture_output=True,timeout=60).returncode!=0

@pytest.mark.parametrize('file,old,new',[
    ('certificates/0213.txt','c1 = ','c1 = -'),
    ('intermediate/0213/generators.txt','g1 = ','g1 = 3 + '),
    ('intermediate/0213/geometry.txt','v0 = ','v0 = 1 | '),
    ('intermediate/0213/orientations.txt','sign 1;','sign -1;'),
    ('intermediate/0213/coefficient-check.txt',' | 0\n',' | 1\n'),
])
def test_corruption_rejected(example,tmp_path,file,old,new):
    output,_=example;copy=tmp_path/'changed';shutil.copytree(output,copy)
    p=copy/file;s=p.read_text();assert old in s;p.write_text(s.replace(old,new,1))
    with pytest.raises((ValueError,IndexError,KeyError,TypeError)):
        verify_bundle(read_certificate(copy/'certificates/0213.txt'))

def test_explicit_flag_reproduces_geometry(example,tmp_path):
    output,command=example;b=read_certificate(output/'certificates/0213.txt')
    command=command.copy();command[command.index('--output')+1]=str(tmp_path/'rerun')
    command[command.index('--flag-attempts')+1]='1'
    command+=['--flag',','.join(map(str,b['metadata']['flag']))]
    done=subprocess.run(command,capture_output=True,text=True,timeout=240)
    assert done.returncode==0,done.stdout+done.stderr
    other=read_certificate(tmp_path/'rerun/certificates/0213.txt')
    assert other['metadata']['matrix']==b['metadata']['matrix']
    assert verify_bundle(other)['status']=='verified_exact'

def test_decoded_polynomials():
    names=['x_0_2','x_3_4']
    p=[(0,-3),(2,2),(256,1)]
    assert monomial(258,names)=='x_0_2^2*x_3_4'
    assert parse_poly(polynomial(p,names),names)==p

def test_empty_selection_fails(tmp_path):
    done=subprocess.run([sys.executable,str(ROOT/'run_prismatoid_batch.py'),'run','--data',str(ROOT/'examples/prepared'),
        '--output',str(tmp_path/'empty'),'--vertex-count','28'],capture_output=True,timeout=30)
    assert done.returncode!=0
    assert not (tmp_path/'empty').exists()

def test_failed_attempt_retains_no_solver_artifacts(tmp_path):
    output=tmp_path/'bad'
    done=subprocess.run([sys.executable,str(ROOT/'run_prismatoid_batch.py'),'run','--data',str(ROOT/'examples/prepared'),
        '--output',str(output),'--flag','2,3,4,5,6,7','--flag-attempts','1','--lp-solver','scipy-highs'],capture_output=True,timeout=60)
    assert done.returncode!=0
    assert (output/'inconclusive/0213.txt').exists()
    assert not list(output.glob('certificates/*.txt'))
    assert all(f.suffix=='.txt' for f in output.rglob('*') if f.is_file())


def test_previous_geometry_labels_remain_readable(example, tmp_path):
    output, _ = example
    copy = tmp_path / 'previous-format'
    shutil.copytree(output, copy)
    path = copy / 'intermediate/0213/geometry.txt'
    text = path.read_text()
    assert '[Reduced slack matrix R]' in text
    assert '[Ordered facet bases B_j]' in text
    assert re.search(r'^B0 = ', text, re.M)
    text = text.replace('[Reduced slack matrix R]', '[Reduced slack matrix]')
    text = text.replace('[Ordered facet bases B_j]', '[Ordered facet bases]')
    text = re.sub(r'^B(\d+) = ', r'F\1 = ', text, flags=re.M)
    path.write_text(text)
    assert read_certificate(copy / 'certificates/0213.txt') == read_certificate(output / 'certificates/0213.txt')
