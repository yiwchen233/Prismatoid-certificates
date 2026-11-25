from pathlib import Path
import subprocess,sys,shutil
import pytest
from human_certificate import (read_certificate,verify_bundle,monomial,parse_poly,polynomial,
                               cancellation_text,orientation_text,_coefficient_table_text)
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
    ('intermediate/0213/coefficient-check.txt',' = 0\n',' = 1\n'),
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
    text = text.replace('[Why R has rank 6]', '[Reduced rank pivots]')
    text = text.replace('[Why the chosen facet vertices are affinely independent]', '[Facet basis rank pivots]')
    text = re.sub(r'^B(\d+) = ', r'F\1 = ', text, flags=re.M)
    path.write_text(text)
    assert read_certificate(copy / 'certificates/0213.txt') == read_certificate(output / 'certificates/0213.txt')


def test_sparse_coefficient_blocks():
    bundle = {
        'metadata': {'variable_names': ['x', 'y']},
        'generators': [{'polynomial': [(1, -1)]},
                       {'polynomial': [(1, 1), (256, 1)]},
                       {'polynomial': [(256, -1)]}],
        'terms': [{'weight': '1/3', 'factors': [i]} for i in range(3)],
    }
    text = cancellation_text(bundle)
    assert 'every omitted product has coefficient zero' in text
    assert 'P2 = g2; c2 = 1/3' in text
    blocks = text.split('Monomial: ')[1:]
    rows = [[line.split() for line in block.splitlines() if re.match(r'^P\d+\s', line)] for block in blocks]
    assert rows == [[['P1', '-1', '1/3', '-1/3'], ['P2', '1', '1/3', '1/3']],
                    [['P2', '1', '1/3', '1/3'], ['P3', '-1', '1/3', '-1/3']]]
    assert 'Sum: -1/3 + 1/3 = 0' in blocks[0]
    assert 'Sum: 1/3 - 1/3 = 0' in blocks[1]


def test_orientation_dependencies_precede_uses(example):
    output, _ = example
    bundle = read_certificate(output / 'certificates/0213.txt')
    text = (output / 'intermediate/0213/orientations.txt').read_text()
    assert 'test vertex' not in text
    done = set()
    propagated = False
    for line in text.splitlines():
        match = re.match(r'F(\d+): sign (-?1); T\((\d+),(\d+)\)(.+)', line)
        if not match:
            continue
        j, _, i, left_j, why = match.groups()
        assert j == left_j
        assert int(i) == bundle['metadata']['orientation_proofs'][j]['row']
        if why == ' is a positive monomial':
            assert not propagated
        else:
            propagated = True
            parent = re.fullmatch(r' = T\((\d+),(\d+)\)', why)
            assert int(parent[2]) in done
        assert int(j) not in done
        done.add(int(j))
    assert done == {int(j) for j in bundle['metadata']['orientation_proofs']}


@pytest.mark.parametrize('field', ['coefficient', 'weight', 'contribution', 'product_weight', 'determinant_row', 'determinant_facet'])
def test_displayed_arithmetic_and_vertex_corruption_rejected(example, tmp_path, field):
    output, _ = example
    copy = tmp_path / 'changed'
    shutil.copytree(output, copy)
    folder = copy / 'intermediate/0213'
    if field in ('determinant_row', 'determinant_facet'):
        path = folder / 'orientations.txt'
        if field == 'determinant_row':
            text = re.sub(r'T\(\d+,', 'T(999,', path.read_text(), count=1)
        else:
            text = re.sub(r'(T\(\d+,)\d+', r'\g<1>999', path.read_text(), count=1)
    else:
        path = folder / 'coefficient-check.txt'
        text = path.read_text()
        if field == 'product_weight':
            text = text.replace('c1 = ', 'c1 = 9', 1)
        else:
            index = {'coefficient': 1, 'weight': 2, 'contribution': 3}[field]
            match = re.search(r'^P\d+\s+-?\d+\s+[\d/]+\s+-?[\d/]+$', text, re.M)
            cells = match[0].split()
            cells[index] = '999'
            text = text[:match.start()] + '   '.join(cells) + text[match.end():]
    path.write_text(text)
    with pytest.raises(ValueError):
        verify_bundle(read_certificate(copy / 'certificates/0213.txt'))


def test_orientation_writer_rejects_cycle():
    meta = {'column_signs': {'0': 1, '1': 1}, 'orientation_proofs': {
        '0': {'kind': 'propagation', 'row': 2, 'parent': [3, 1]},
        '1': {'kind': 'propagation', 'row': 3, 'parent': [2, 0]},
    }}
    with pytest.raises(ValueError, match='cyclic'):
        orientation_text(meta)


def test_saved_table_and_orientation_format_remain_readable(example, tmp_path):
    output, _ = example
    bundle = read_certificate(output / 'certificates/0213.txt')
    copy = tmp_path / 'saved-format'
    shutil.copytree(output, copy)
    folder = copy / 'intermediate/0213'
    (folder / 'coefficient-check.txt').write_text(_coefficient_table_text(bundle))
    lines = ['COLUMN ORIENTATIONS']
    meta = bundle['metadata']
    for j, proof in meta['orientation_proofs'].items():
        why = ('positive monomial' if proof['kind'] == 'monomial'
               else f'equal T({proof["parent"][0]},{proof["parent"][1]})')
        lines.append(f'F{j}: sign {meta["column_signs"][j]}; row {proof["row"]}; {why}')
    (folder / 'orientations.txt').write_text('\n'.join(lines) + '\n')
    assert read_certificate(copy / 'certificates/0213.txt') == bundle


def test_redundant_vertex_field_remains_readable(example, tmp_path):
    output, _ = example
    bundle = read_certificate(output / 'certificates/0213.txt')
    copy = tmp_path / 'redundant-vertex'
    shutil.copytree(output, copy)
    path = copy / 'intermediate/0213/orientations.txt'
    text = re.sub(r'^(F\d+: sign -?1; )(T\((\d+),)',
                  lambda m: f'{m[1]}test vertex v{m[3]}; {m[2]}',
                  path.read_text(), flags=re.M)
    path.write_text(text)
    assert read_certificate(copy / 'certificates/0213.txt') == bundle
    path.write_text(re.sub(r'test vertex v\d+;', 'test vertex v999;', text, count=1))
    with pytest.raises(ValueError, match='row mismatch'):
        read_certificate(copy / 'certificates/0213.txt')
