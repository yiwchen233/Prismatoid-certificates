"""Readable certificates and an exact reader; no numerical solver is needed."""
from pathlib import Path
from fractions import Fraction
from collections import defaultdict
import re
import json
import hashlib
import sys

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


def cancellation_text(bundle):
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
    lines+=['','[Reduced rank pivots]', 'In order, remove each pivot row/column; its remaining row has one nonzero.']
    lines += [f'v{i}, F{flag[j]}' for i,j in meta['flag_witness']]
    lines+=['','[Facet basis rank pivots]', 'For each basis, rows are facets and columns are its vertices. Use the',
            'nonincidence pattern (entry 1 iff vertex is not in facet), removing pivots in order.']
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
    lines=['COLUMN ORIENTATIONS',
           'Let T(i,j) be sign_j*D(i,j) divided by its positive gcd content and',
           'common monomial (even if the certificate uses raw determinants).',
           'An anchor is a positive single monomial T(i,j). A propagation step is',
           'the exact identity T(i,j) = T(parent row,parent column). Follow parent',
           'links to anchors. The displayed row belongs to the prepared vertex set.', '']
    for j,p in sorted(meta['orientation_proofs'].items(),key=lambda x:int(x[0])):
        sign=meta['column_signs'].get(str(j),meta['column_signs'].get(int(j)))
        why='positive monomial' if p['kind']=='monomial' else f'equal T({p["parent"][0]},{p["parent"][1]})'
        lines.append(f'F{j}: sign {sign}; row {p["row"]}; {why}')
    (folder/'orientations.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
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
    pivots=[[int(i),flag.index(int(j))] for line in sections['[Reduced rank pivots]'] for i,j in re.findall(r'^v(\d+), F(\d+)$',line)]
    bw=[]
    for line in sections['[Facet basis rank pivots]']:
        m=re.match(r'F(\d+): (.+)',line)
        if m: bw.append([[int(r),bases[int(m[1])].index(int(v))] for r,v in re.findall(r'F(\d+), v(\d+)',m[2])])
    signs={};proofs={}
    for j,s,i,why in re.findall(r'^F(\d+): sign (-?1); row (\d+); (.+)$',(folder/'orientations.txt').read_text(),re.M):
        signs[j]=int(s);p={'row':int(i),'kind':'monomial' if why=='positive monomial' else 'propagation'}
        if p['kind']=='propagation':p['parent']=list(map(int,re.fullmatch(r'equal T\((\d+),(\d+)\)',why).groups()))
        proofs[j]=p
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
    if (folder/'coefficient-check.txt').read_text(encoding='utf-8')!=cancellation_text(bundle):
        raise ValueError('Coefficient table differs from the displayed generators/weights')
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
