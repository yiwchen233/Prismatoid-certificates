"""Readable certificates and an exact reader; no numerical solver is needed."""
from pathlib import Path
from fractions import Fraction
from collections import defaultdict
import re
import json
import hashlib
import sys
import textwrap

CORE = Path(__file__).resolve().parent / 'core/src'
sys.path.insert(0, str(CORE))
from modules.verify_certificate import verify_bundle


def monomial(packed, names):
    parts=[]
    for k,name in enumerate(names):
        e=(packed >> (8*k)) & 255
        if e: parts.append(name + (f'^{e}' if e != 1 else ''))
    if packed >> (8*len(names)): raise ValueError('Unknown variable in monomial')
    return '*'.join(parts) or '1'


def polynomial(items, names):
    parts=[]
    for m,c in sorted(items):
        c=Fraction(c)
        if not c: continue
        mon=monomial(m,names)
        term=str(abs(c)) if mon=='1' else ('' if abs(c)==1 else str(abs(c))+'*')+mon
        parts.append(('- ' if c<0 else '+ ')+term)
    return ' '.join(parts).removeprefix('+ ') or '0'


def parse_poly(text, names):
    positions={name:i for i,name in enumerate(names)}
    out={}
    for sign,term in re.findall(r'([+-]?)\s*([^+\-]+)',text):
        m=0;c=Fraction(-1 if sign=='-' else 1)
        for factor in term.strip().split('*'):
            if factor[0].isdigit(): c*=Fraction(factor)
            else:
                match=re.fullmatch(r'(\w+)(?:\^(\d+))?',factor)
                if not match or match[1] not in positions: raise ValueError('Invalid polynomial factor '+factor)
                e=int(match[2] or 1)
                if not 0<=e<256: raise ValueError('Exponent out of range')
                m+=e << (8*positions[match[1]])
        if c:
            if m in out: raise ValueError('Duplicate monomial')
            if c.denominator!=1: raise ValueError('Noninteger generator coefficient')
            out[m]=int(c)
    return sorted(out.items())


def products(bundle):
    out=[]
    for term in bundle['terms']:
        p={0:1}
        for i in term['factors']:
            q=defaultdict(int)
            for a,c in p.items():
                for b,d in bundle['generators'][i]['polynomial']: q[a+b]+=c*d
            p={a:c for a,c in q.items() if c}
        out.append(p)
    return out


def _coefficient_table_text(bundle):
    ps=products(bundle); names=bundle['metadata']['variable_names']
    lines=['COEFFICIENT CHECK', 'Columns are coefficients in the products P1, P2, ... (before weighting).',
           'Multiply each column by its coefficient c_k from the certificate.',
           'The last column is the exact weighted sum; every entry must be zero.', '',
           'Monomial | '+' | '.join('P'+str(i+1) for i in range(len(ps)))+' | weighted sum']
    for m in sorted(set().union(*(p.keys() for p in ps))):
        coeff=[p.get(m,0) for p in ps]
        residual=sum(Fraction(t['weight'])*c for t,c in zip(bundle['terms'],coeff))
        if residual: raise ValueError('Nonzero coefficient residual')
        lines.append(monomial(m,names)+' | '+' | '.join(map(str,coeff))+' | 0')
    return '\n'.join(lines)+'\n'


def cancellation_text(bundle):
    """Display exact cancellation one monomial at a time, omitting zero entries."""
    ps = products(bundle)
    names = bundle['metadata']['variable_names']
    weights = [Fraction(t['weight']) for t in bundle['terms']]
    monomials = sorted(set().union(*(p.keys() for p in ps)))
    lines = ['COEFFICIENT CHECK',
             'Each block checks the coefficient of one monomial in the identity.',
             'Contribution = coefficient in Pk * weight ck.',
             'Only nonzero coefficients are listed; every omitted product has coefficient zero.',
             'All arithmetic is exact. Every displayed sum must be zero.', '',
             'PRODUCTS AND WEIGHTS']
    for k, term in enumerate(bundle['terms'], 1):
        factors = '*'.join(f'g{i+1}' for i in term['factors'])
        lines.append(f'P{k} = {factors}; c{k} = {weights[k-1]}')
    lines += ['', f'Monomials checked: {len(monomials)}', '']
    for m in monomials:
        rows = []
        contributions = []
        for k, (p, weight) in enumerate(zip(ps, weights), 1):
            coefficient = p.get(m, 0)
            if coefficient:
                contribution = coefficient * weight
                rows.append([f'P{k}', str(coefficient), str(weight), str(contribution)])
                contributions.append(contribution)
        if sum(contributions):
            raise ValueError('Nonzero coefficient residual')
        lines += textwrap.wrap('Monomial: ' + monomial(m, names).replace('*', ' * '),
                               width=88, subsequent_indent='          ',
                               break_long_words=False, break_on_hyphens=False)
        lines.append('')
        headings = ['Product', 'Coefficient', 'Weight', 'Contribution']
        widths = [max(len(row[i]) for row in [headings] + rows) for i in range(4)]
        for row in [headings] + rows:
            lines.append('   '.join(value.ljust(widths[i]) if i == 0 else value.rjust(widths[i])
                                    for i, value in enumerate(row)))
        total = str(contributions[0])
        for contribution in contributions[1:]:
            total += (' - ' if contribution < 0 else ' + ') + str(abs(contribution))
        lines += ['', 'Sum: ' + total + ' = 0', '']
    return '\n'.join(lines)


def orientation_text(meta):
    """Put direct sign checks first and each dependent column after its source."""
    proofs = {int(j): p for j, p in meta['orientation_proofs'].items()}
    signs = {int(j): s for j, s in meta['column_signs'].items()}
    if set(proofs) != set(signs):
        raise ValueError('Missing orientation proof')
    lines = ['COLUMN SIGNS',
             'T(i,j) = sign * D(i,j) / (positive gcd content * common monomial).',
             'Here sign is +1 or -1 recorded for facet Fj; i identifies row i of R.',
             'D(i,j) is defined in generators.txt using the matrix and bases in geometry.txt.',
             'Both indices in T(i,j) start at zero.',
             'Under a hypothetical realization, one nonzero entry fixes the whole facet column sign.',
             'Direct positive-monomial checks come first. Each equality then uses a column',
             'whose sign has already been established; its referenced vertex may be different.', '']
    remaining = set(proofs)
    done = set()
    while remaining:
        ready = []
        for j in sorted(remaining):
            proof = proofs[j]
            if proof['kind'] == 'monomial':
                ready.append(j)
            elif proof['kind'] == 'propagation':
                if int(proof['parent'][1]) in done:
                    ready.append(j)
            else:
                raise ValueError('Unknown orientation proof type')
        if not ready:
            raise ValueError('Missing/cyclic orientation proof')
        for j in ready:
            proof = proofs[j]
            i = proof['row']
            why = (f'T({i},{j}) is a positive monomial' if proof['kind'] == 'monomial'
                   else f'T({i},{j}) = T({proof["parent"][0]},{proof["parent"][1]})')
            lines.append(f'F{j}: sign {signs[j]}; {why}')
        remaining.difference_update(ready)
        done.update(ready)
    return '\n'.join(lines) + '\n'


def write_certificate(bundle, group, source_labels=None):
    """Write only the successful witness, as ordinary labelled text."""
    group=Path(group); cid=bundle['candidate_id']; meta=bundle['metadata']
    folder=group/'intermediate'/cid; folder.mkdir(parents=True,exist_ok=True)
    (group/'certificates').mkdir(exist_ok=True)
    names=meta['variable_names']; flag=meta['flag']; F=meta['facets']
    attempt=bundle.get('search_attempt',{})
    lines=[f'CERTIFICATE {cid}', 'Status: exact positive identity',
           'Selected facets: '+ ' '.join(map(str,flag)),
           'Random seed: '+str(attempt.get('random_seed',0)),
           'Generator term cap: '+str(attempt.get('term_limit',0)),
           'Generator degree bound: '+str(meta['max_generator_degree']),
           'Factor bound: '+str(meta.get('max_factors',2)),
           'Normalization: '+meta['normalization'], '',
           'Only the successful reduction is retained. All indices below are zero-based,',
           'except the local labels g1, P1, c1, ... which start at 1.',
           f'Generator definitions and reconstruction data: ../intermediate/{cid}/', '',
           'IDENTITY: c1*P1 + c2*P2 + ... = 0',
           'The c_k are strictly positive rational weights; their sum is 1.', '']
    for k,t in enumerate(bundle['terms'],1):
        lines.append(f'P{k} = '+ '*'.join(f'g{i+1}' for i in t['factors'])+f'; c{k} = {t["weight"]}')
    lines+=['', 'Each g is positive under a hypothetical realization; see generators.txt.',
            'Check the zero identity using coefficient-check.txt. No floating-point',
            'coefficients or LP row numbers are needed for this displayed certificate.']
    (group/'certificates'/f'{cid}.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    lines=['RECONSTRUCTION DATA',f'Candidate: {cid}','Dimension: '+str(meta['dimension']),
           'Rows are prepared vertices v_i. Facets F_j are listed in prepared input order.',
           'A variable x_i_j is the positive entry in row i and original facet column j.', '',
           '[Facets]']
    lines += [f'F{j} = '+ ' '.join(map(str,f)) for j,f in enumerate(F)]
    lines+=['','[Reduced slack matrix R]', 'R has one row per prepared vertex and six columns, in the order below.', 'Columns: '+' '.join('F'+str(j) for j in flag)]
    lines += [f'v{i} = '+' | '.join(map(str,row)) for i,row in enumerate(meta['matrix'])]
    lines+=['','[Variable order]']+names
    lines+=['','[Ordered facet bases B_j]', 'Bj denotes B_j: the five vertex indices for facet Fj, in determinant row order.']
    lines += [f'B{j} = '+' '.join(map(str,b)) for j,b in enumerate(meta['facet_bases'])]
    lines+=['','[Why R has rank 6]',
            'The six pairs below identify rows and columns of R, both ordered by the pairs.',
            'Each pair identifies a diagonal entry of the resulting 6-by-6 submatrix.',
            'Its diagonal entries are nonzero, and all entries above the diagonal are zero.',
            'This lower-triangular submatrix has nonzero determinant, so R has rank 6.']
    lines += [f'v{i}, F{flag[j]}' for i,j in meta['flag_witness']]
    lines+=['','[Why the chosen facet vertices are affinely independent]',
            'For Fj, the five pairs (Fk, vi) identify facet rows Fk and vertex columns vi from Bj.',
            'In listed pair order, they form a 5-by-5 submatrix.',
            'An entry is 0 when the vertex belongs to the facet, and * otherwise.',
            'A * denotes an unknown positive slack entry in a hypothetical realization.',
            'Every diagonal entry is *, and all entries above the diagonal are zero.',
            'This lower-triangular submatrix has nonzero determinant, establishing affine',
            'independence of the five chosen vertices under a hypothetical realization.']
    for j,pivots in enumerate(meta['basis_witnesses']):
        lines.append(f'F{j}: '+'; '.join(f'F{r}, v{meta["facet_bases"][j][c]}' for r,c in pivots))
    lines+=['','[Original vertex labels]', 'Each prepared vertex corresponds to the following original input label.']
    if source_labels is None:
        lines+=['Not supplied: compare the complete facet list above with the input.']
    else: lines += [f'v{i} = {label}' for i,label in enumerate(source_labels)]
    (folder/'geometry.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    lines=['POSITIVE GENERATORS',
           'D(i,j) = det R[B_j followed by i, all six columns in the displayed order].',
           'For slack sources, g = sign * D(i,j) / (content * monomial).',
           'The divisor is positive. In geometry.txt, see [Reduced slack matrix R]',
           'and [Ordered facet bases B_j]; Bj denotes B_j (e.g. B3 means B_3).',
           'Signs are justified in orientations.txt. Each expanded g appears above its source.', '']
    for k,g in enumerate(bundle['generators'],1):
        p=g['provenance'];lines.append(f'g{k} = '+polynomial(g['polynomial'],names))
        if p['kind']=='slack':
            lines.append(f'g{k} source: D({p["row"]},{p["column"]}); sign {p["sign"]}; content {p["content"]}; monomial '+monomial(p['monomial'],names))
        elif p['kind']=='variable':lines.append(f'g{k} source: variable '+names[p['index']])
        else:lines.append(f'g{k} source: constant 1')
        lines.append('')
    (folder/'generators.txt').write_text('\n'.join(lines),encoding='utf-8')
    (folder/'orientations.txt').write_text(orientation_text(meta),encoding='utf-8')
    (folder/'coefficient-check.txt').write_text(cancellation_text(bundle),encoding='utf-8')


def read_certificate(path):
    path=Path(path);text=path.read_text(encoding='utf-8');cid=path.stem
    folder=path.parent.parent/'intermediate'/cid
    def field(key):return re.search('^'+re.escape(key)+r': (.+)$',text,re.M)[1]
    flag=list(map(int,field('Selected facets').split()))
    sections={}; current=None
    for line in (folder/'geometry.txt').read_text(encoding='utf-8').splitlines():
        if line.startswith('['):current=line;sections[current]=[]
        elif current:sections[current].append(line)
    def facets(section, prefix='F'):
        rows=[re.fullmatch(prefix+r'(\d+) = (.+)',line) for line in sections[section] if re.match(prefix+r'\d+ = ',line)]
        if [int(m[1]) for m in rows]!=list(range(len(rows))):raise ValueError('Facet label order')
        return [list(map(int,m[2].split())) for m in rows]
    F=facets('[Facets]')
    # Accept the earlier readable edition as well as explicitly named R/B_j sections.
    basis_section='[Ordered facet bases B_j]' if '[Ordered facet bases B_j]' in sections else '[Ordered facet bases]'
    bases=facets(basis_section, 'B' if basis_section=='[Ordered facet bases B_j]' else 'F')
    matrix_section='[Reduced slack matrix R]' if '[Reduced slack matrix R]' in sections else '[Reduced slack matrix]'
    matrix_lines=[line for line in sections[matrix_section] if re.match(r'v\d+ = ',line)]
    if [int(re.match(r'v(\d+)',line)[1]) for line in matrix_lines]!=list(range(len(matrix_lines))):raise ValueError('Vertex row order')
    if 'Columns: '+' '.join('F'+str(j) for j in flag) not in sections[matrix_section]:raise ValueError('Reduced column labels')
    matrix=[[int(x) if x.isdigit() else x for x in line.split(' = ')[1].split(' | ')] for line in matrix_lines]
    names=[line for line in sections['[Variable order]'] if re.fullmatch(r'\w+',line)]
    rank_section='[Why R has rank 6]' if '[Why R has rank 6]' in sections else '[Reduced rank pivots]'
    independence_section='[Why the chosen facet vertices are affinely independent]'
    if independence_section not in sections: independence_section='[Facet basis rank pivots]'
    pivots=[[int(i),flag.index(int(j))] for line in sections[rank_section] for i,j in re.findall(r'^v(\d+), F(\d+)$',line)]
    bw=[]
    for line in sections[independence_section]:
        m=re.match(r'F(\d+): (.+)',line)
        if m: bw.append([[int(r),bases[int(m[1])].index(int(v))] for r,v in re.findall(r'F(\d+), v(\d+)',m[2])])
    signs={};proofs={}
    for line in (folder/'orientations.txt').read_text(encoding='utf-8').splitlines():
        if not re.match(r'^F\d+:',line): continue
        current=re.fullmatch(r'F(\d+): sign (-?1); (?:test vertex v(\d+); )?T\((\d+),(\d+)\)(.+)',line)
        if current:
            j,s,stated_i,i,left_j,why=current.groups()
            if j!=left_j: raise ValueError('Orientation determinant facet mismatch')
            if stated_i is not None and stated_i!=i: raise ValueError('Orientation determinant row mismatch')
            if why==' is a positive monomial':
                p={'row':int(i),'kind':'monomial'}
            else:
                parent=re.fullmatch(r' = T\((\d+),(\d+)\)',why)
                if not parent: raise ValueError('Invalid orientation equality')
                p={'row':int(i),'kind':'propagation','parent':list(map(int,parent.groups()))}
        else:
            previous=re.fullmatch(r'F(\d+): sign (-?1); row (\d+); (.+)',line)
            if not previous: raise ValueError('Invalid orientation entry')
            j,s,i,why=previous.groups()
            p={'row':int(i),'kind':'monomial' if why=='positive monomial' else 'propagation'}
            if p['kind']=='propagation':
                parent=re.fullmatch(r'equal T\((\d+),(\d+)\)',why)
                if not parent: raise ValueError('Invalid orientation equality')
                p['parent']=list(map(int,parent.groups()))
        if j in signs: raise ValueError('Duplicate orientation entry')
        signs[j]=int(s);proofs[j]=p
    gs=[]
    for line in (folder/'generators.txt').read_text().splitlines():
        m=re.fullmatch(r'g(\d+) = (.+)',line)
        if m:
            if int(m[1])!=len(gs)+1:raise ValueError('Generator numbering')
            gs.append({'polynomial':parse_poly(m[2],names)})
        m=re.fullmatch(r'g(\d+) source: (.+)',line)
        if m:
            source=m[2]
            if source=='constant 1':p={'kind':'constant'}
            elif source.startswith('variable '):p={'kind':'variable','index':names.index(source[9:])}
            else:
                i,j,s,c,mon=re.fullmatch(r'D\((\d+),(\d+)\); sign (-?1); content (\d+); monomial (.+)',source).groups()
                mono=parse_poly(mon,names)
                if len(mono)!=1 or mono[0][1]!=1:raise ValueError('Invalid divisor')
                p=dict(kind='slack',row=int(i),column=int(j),sign=int(s),content=int(c),monomial=mono[0][0])
            gs[int(m[1])-1]['provenance']=p
    terms=[]
    for k,factors,k2,w in re.findall(r'^P(\d+) = (.+); c(\d+) = ([\d/]+)$',text,re.M):
        if k!=k2 or int(k)!=len(terms)+1:raise ValueError('Term numbering')
        terms.append({'weight':w,'factors':[int(x[1:])-1 for x in factors.split('*')]})
    meta=dict(facets=F,flag=flag,matrix=matrix,variable_names=names,facet_bases=bases,
              flag_witness=pivots,basis_witnesses=bw,column_signs=signs,orientation_proofs=proofs,
              normalization=field('Normalization'),dimension=5,max_factors=int(field('Factor bound')),
              max_generator_degree=int(field('Generator degree bound')),
              facet_sha256=hashlib.sha256(json.dumps(F,separators=(',',':')).encode()).hexdigest())
    bundle=dict(candidate_id=cid,metadata=meta,generators=gs,terms=terms,
                search_attempt=dict(flag=flag,random_seed=int(field('Random seed')),term_limit=int(field('Generator term cap'))))
    check=(folder/'coefficient-check.txt').read_text(encoding='utf-8')
    expected=(_coefficient_table_text(bundle) if check.startswith('COEFFICIENT CHECK\nColumns are coefficients')
              else cancellation_text(bundle))
    if check!=expected:
        raise ValueError('Coefficient check differs from the displayed generators/weights')
    return bundle


def main():
    import argparse
    p=argparse.ArgumentParser(description='Verify readable certificates without an LP solver.')
    p.add_argument('path',type=Path)
    p.add_argument('--data',type=Path,help='Also compare each proof with its numbered raw input and vertex-label mapping')
    args=p.parse_args()
    paths=[args.path] if args.path.is_file() else sorted(args.path.rglob('certificates/*.txt'))
    if not paths: p.error('No certificate files found; supply a candidate file or a results group/root')
    failed=0
    for path in paths:
        try:
            expected=None
            if args.data:
                from prismatoid_batch.facet_io import read_facets,read_box_prismatoid
                source=args.data/path.stem
                expected=[list(f) for f in read_facets(source).facets]
                labels=list(read_box_prismatoid(source).all_source_vertices)
                geometry=(path.parent.parent/'intermediate'/path.stem/'geometry.txt').read_text()
                mapping=geometry.split('[Original vertex labels]')[1]
                pairs=[(int(i),int(v)) for i,v in re.findall(r'^v(\d+) = (\d+)$',mapping,re.M)]
                if pairs!=list(enumerate(labels)):raise ValueError('Original vertex mapping mismatch')
            result=verify_bundle(read_certificate(path),expected_facets=expected)
            print(f'{path.stem}: VERIFIED EXACT ({result["terms"]} terms)',flush=True)
        except Exception as exc:failed+=1;print(f'{path}: FAILED: {exc}',file=sys.stderr,flush=True)
    print(f'Verified {len(paths)-failed}/{len(paths)}')
    return int(bool(failed))

if __name__=='__main__':raise SystemExit(main())
