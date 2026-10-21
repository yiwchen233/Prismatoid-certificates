"""Search inputs and retain only readable, independently checked successful witnesses."""
from pathlib import Path
import argparse, os, re, shutil, subprocess, sys, tempfile
from .facet_io import enumerate_candidates,read_facets,candidate_vertex_count,candidate_id
from .flag_search import sample_rank_certified_facet_flags
from .license_config import resolve_gurobi_license,apply_gurobi_license


def positive(text):
    n=int(text)
    if n<=0:raise argparse.ArgumentTypeError('Must be positive')
    return n


def build_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='prismatoid-readable 2.0')
    sub=p.add_subparsers(dest='command',required=True)
    v=sub.add_parser('validate-data');v.add_argument('--data',type=Path,required=True)
    r=sub.add_parser('run')
    r.add_argument('--data',type=Path,required=True);r.add_argument('--output',type=Path,required=True)
    r.add_argument('--vertex-count',type=positive,action='append')
    r.add_argument('--candidate',action='append',help='Candidate ID; repeat to select several')
    r.add_argument('--limit',type=positive)
    r.add_argument('--n-factors',type=positive,default=2)
    r.add_argument('--max-degree',type=positive,default=3)
    r.add_argument('--search-variant',choices=['legacy','all-variable-products-simplified'],default='all-variable-products-simplified')
    r.add_argument('--flag-attempts',type=positive,default=20)
    r.add_argument('--flag',help='Explicit ordered facet labels, comma-separated; use one attempt')
    r.add_argument('--random-seed',type=int,default=0)
    r.add_argument('--lp-solver',choices=['auto','gurobipy','scipy-highs'],default='auto')
    r.add_argument('--gurobi-license',type=Path)
    r.add_argument('--timeout',type=positive,default=36000,help='Seconds per flag, including construction and verification')
    r.add_argument('--gurobi-threads',type=positive,default=8)
    r.add_argument('--gurobi-method',type=int,default=0)
    r.add_argument('--no-resume',action='store_true')
    return p


def summary(output):
    lines=['SEARCH RESULTS','Candidate | status']
    for p in sorted((output/'certificates').glob('*.txt')):lines.append(p.stem+' | exact certificate')
    for p in sorted((output/'inconclusive').glob('*.txt')):lines.append(p.stem+' | '+p.read_text().splitlines()[0])
    (output/'SUMMARY.txt').write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser=build_parser();a=parser.parse_args(argv)
    if not a.data.is_dir():parser.error('Input directory does not exist')
    paths=enumerate_candidates(a.data.resolve())
    if not paths:parser.error('No recognized candidate inputs found')
    if a.command=='validate-data':
        for p in paths:read_facets(p)
        print(f'candidates={len(paths)} invalid=0');return 0
    from human_certificate import read_certificate,verify_bundle
    root=Path(__file__).resolve().parents[1]
    paths=[p for p in paths if (not a.vertex_count or candidate_vertex_count(p) in a.vertex_count)
           and (not a.candidate or candidate_id(p,a.data.resolve()) in a.candidate)]
    if a.limit:paths=paths[:a.limit]
    if not paths:parser.error('No candidates match the selection')
    ids=[candidate_id(p,a.data.resolve()) for p in paths]
    if len(ids)!=len(set(ids)):parser.error('Duplicate candidate IDs')
    explicit=None
    if a.flag:
        try:explicit=list(map(int,a.flag.split(',')))
        except ValueError:parser.error('--flag must contain integers separated by commas')
        if len(explicit)!=6 or len(set(explicit))!=6:parser.error('--flag must contain six distinct facet labels')
        if a.flag_attempts!=1:parser.error('Use --flag-attempts 1 with --flag')
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    config='READABLE SEARCH SETTINGS\n'+'\n'.join(f'{k}: {getattr(a,k)}' for k in
        ['n_factors','max_degree','search_variant','flag_attempts','flag','random_seed','lp_solver','timeout','gurobi_threads','gurobi_method'])+'\n'+\
        'generator_term_caps: '+os.getenv('PRISMATOID_GENERATOR_TERM_CAPS','4,8,0')+'\n'+\
        'product_budget: '+os.getenv('PRISMATOID_MAX_PRODUCTS','200000')+'\n'
    settings=output/'RUN.txt'
    if settings.exists():
        if settings.read_text()!=config:parser.error('Search settings differ: use a new output directory')
    elif any(output.iterdir()):parser.error('Use a new output directory; archived results are not a resume workspace')
    settings.write_text(config)
    env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(root),env.get('PYTHONPATH','')])
    env['PRISMATOID_LP_SOLVER']=a.lp_solver
    env['PRISMATOID_GUROBI_THREADS']=str(a.gurobi_threads);env['PRISMATOID_GUROBI_METHOD']=str(a.gurobi_method)
    env['PRISMATOID_GUROBI_LOG']='0'
    apply_gurobi_license(resolve_gurobi_license(a.gurobi_license,project_root=root/'core'),env)
    failures=0
    for path,cid in zip(paths,ids):
        F=[list(f) for f in read_facets(path).facets]
        cert=output/'certificates'/f'{cid}.txt'
        if cert.exists() and not a.no_resume:
            verify_bundle(read_certificate(cert),expected_facets=F)
            print(f'{cid}: retained verified certificate',flush=True);continue
        if cert.exists():cert.unlink()
        # Old successful data must never masquerade as a newly failed attempt.
        old=output/'intermediate'/cid
        if old.exists():shutil.rmtree(old)
        selected_default=[];pending=[explicit];success=False;errors=0;timeouts=0
        index=0
        while index<len(pending):
            flag=pending[index];seed=a.random_seed
            if flag=='fallback':flag=None;seed+=index
            with tempfile.TemporaryDirectory(prefix='prismatoid-result-') as tmp:
                command=[sys.executable,str(root/'prismatoid_batch/worker.py'),str(path),tmp,cid,
                         '{'+','.join(map(str,flag))+'}' if flag else '{}',str(seed),str(a.max_degree),str(a.n_factors),a.search_variant]
                try:
                    done=subprocess.run(command,env=env,text=True,capture_output=True,timeout=a.timeout)
                    found=re.search(r'^SELECTED_FLAG (.+)$',done.stdout,re.M)
                    if index==0 and found:selected_default=[tuple(map(int,found[1].split(',')))]
                    if done.returncode==0:
                        for name in ('certificates','intermediate'):
                            (output/name).mkdir(exist_ok=True)
                            source=Path(tmp)/name/(f'{cid}.txt' if name=='certificates' else cid)
                            shutil.move(str(source),str(output/name/source.name))
                        success=True
                    elif done.returncode!=2:
                        errors+=1
                        print(f'{cid}: attempt {index+1} failed; '+done.stderr[-500:],file=sys.stderr,flush=True)
                except subprocess.TimeoutExpired:timeouts+=1
            if success:break
            if index==0 and not explicit and a.flag_attempts>1:
                sampled=sample_rank_certified_facet_flags(F,5,a.flag_attempts-1,random_seed=a.random_seed,candidate_id=cid,exclude=selected_default)
                pending+=sampled+['fallback']*(a.flag_attempts-1-len(sampled))
            index+=1
        statusfile=output/'inconclusive'/f'{cid}.txt'
        if success:
            if statusfile.exists():statusfile.unlink()
            print(f'{cid}: exact certificate',flush=True)
        else:
            statusfile.parent.mkdir(exist_ok=True)
            state='execution incomplete' if errors or timeouts else 'no certificate found'
            statusfile.write_text(f'{state}\nCandidate: {cid}\nAttempts: {len(pending)}\nErrors: {errors}\nTimeouts: {timeouts}\nNo conclusion about realizability.\n')
            failures+=int(bool(errors or timeouts));print(f'{cid}: {state}',flush=True)
        summary(output)
    return int(bool(failures))
