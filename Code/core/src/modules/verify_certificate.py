#!/usr/bin/env python3
"""Independent stdlib-only verifier for patched core certificates.

This file does not import the search engine, numpy, SciPy, Sage, or any solver.
Determinants are expanded by all permutations; monomials use sorted tuples of
variable indices, NOT the search engine's packed-exponent arithmetic.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache
import hashlib
import itertools
import json
from math import gcd
from pathlib import Path
import sys

PERMS = [(p, -1 if sum(p[i]>p[j] for i in range(6) for j in range(i+1,6))%2 else 1)
         for p in itertools.permutations(range(6))]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def triangular(pattern, pivots):
    require(bool(pattern), "Empty rank-witness matrix")
    remaining=set(range(len(pattern[0]))); used=set()
    require(len(pivots)==len(remaining), "Incomplete rank witness")
    for r,c in pivots:
        require(isinstance(r,int) and isinstance(c,int), "Noninteger pivot")
        require(0<=r<len(pattern) and c in remaining and r not in used,"Invalid pivot")
        require([j for j in sorted(remaining) if pattern[r][j]]==[c],"Pivot is not an isolated nonzero")
        remaining.remove(c);used.add(r)
    require(not remaining,"Incomplete pivot elimination")


def mult(a,b):
    out=defaultdict(Fraction)
    for ma,ca in a.items():
        for mb,cb in b.items():
            out[tuple(sorted(ma+mb))]+=ca*cb
    return {m:c for m,c in out.items() if c}


def decode_packed(items,nvars):
    out={}
    for packed,coefficient in items:
        require(type(packed) is int and type(coefficient) is int,"Noninteger polynomial encoding")
        require(0<=packed<1<<(8*nvars),"Invalid exponent encoding")
        mon=[]
        for k in range(nvars):
            exp=(packed>>(8*k))&255
            require(exp<=6,"Unexpected exponent (beyond supported search degree)")
            mon.extend([k]*exp)
        mon=tuple(mon)
        require(mon not in out and coefficient!=0,"Duplicate/zero stored monomial")
        out[mon]=coefficient
    require(bool(out),"Zero stored generator")
    return out


def verify_bundle(bundle, expected_facets=None):
    meta=bundle["metadata"]
    F=meta["facets"]; flag=meta["flag"]; tokens=meta["matrix"];bases=meta["facet_bases"]
    require(all(all(type(v) is int for v in f) and len(f)==len(set(f)) for f in F),"Invalid facet vertices")
    require(all(f==sorted(f) for f in F),"Unsorted facets")
    require(len(set(map(tuple,F)))==len(F),"Duplicate facets")
    vertices=sorted(set(itertools.chain.from_iterable(F))); n=len(vertices)
    require(vertices==list(range(n)),"Noncontiguous vertex labels")
    require(len(F)>2 and set(F[0]).isdisjoint(F[1]) and set(F[0]+F[1])==set(vertices),"Invalid bases")
    require(all(len(f)>5 for f in F[:2]) and all(len(f)==5 for f in F[2:]),"Not the supported dimension-five type")
    require(len(flag)==6 and len(set(flag))==6 and all(type(j) is int and 0<=j<len(F) for j in flag),"Invalid flag")
    require({0,1}.issubset(flag),"Reduced columns omit a nonsimplicial base")
    digest=hashlib.sha256(json.dumps(F,separators=(",", ":")).encode()).hexdigest()
    require(digest==meta["facet_sha256"],"Facet hash mismatch")
    if expected_facets is not None:
        require(F==expected_facets,"Certificate is for a different facet list")
    triangular([[i not in F[j] for j in flag] for i in vertices],meta["flag_witness"])
    require(len(bases)==len(F) and len(meta["basis_witnesses"])==len(F),"Wrong number of facet bases")
    for j,b in enumerate(bases):
        require(len(b)==5 and len(set(b))==5 and set(b).issubset(F[j]),f"Invalid basis for facet {j}")
        triangular([[v not in f for v in b] for f in F],meta["basis_witnesses"][j])
    require(len(tokens)==n and all(len(r)==6 for r in tokens),"Wrong reduced-matrix shape")
    names=meta["variable_names"]
    require(all(isinstance(s,str) and s for s in names) and len(names)==len(set(names)),"Invalid variable list")
    used_names=[x for row in tokens for x in row if isinstance(x,str)]
    require(len(used_names)==len(set(used_names)) and set(names)==set(used_names),"Variable repetition/mismatch")
    name_to_id={s:i for i,s in enumerate(names)}
    parent=list(range(n+6))
    def find(v):
        while parent[v]!=v:
            v=parent[v]
        return v
    matrix=[]
    for i,row in enumerate(tokens):
        new=[]
        for j,x in enumerate(row):
            require(type(x) is int and x in (0,1) or isinstance(x,str) and x in name_to_id,"Invalid reduced entry")
            require((x==0)==(i in F[flag[j]]),"Reduced zero pattern differs from input incidences")
            if x==0:
                new.append(None)
            elif x==1:
                a,b=find(i),find(n+j)
                require(a!=b,"Unit entries contain a cycle (normalization unjustified)")
                parent[a]=b;new.append(())
            else:
                new.append((name_to_id[x],))
        matrix.append(new)

    @lru_cache(maxsize=None)
    def raw_det(j,i):
        require(0<=j<len(F) and 0<=i<n,"Out-of-range determinant coordinate")
        rows=bases[j]+[i]
        if len(set(rows))!=6:
            return {}
        out=defaultdict(int)
        for perm,sgn in PERMS:
            mon=[]
            for k,row in enumerate(rows):
                entry=matrix[row][perm[k]]
                if entry is None:
                    break
                mon.extend(entry)
            else:
                out[tuple(sorted(mon))]+=sgn
        return {m:c for m,c in out.items() if c}

    @lru_cache(maxsize=None)
    def sat(j,i):
        require(i not in F[j],"A positive slack generator is on an incidence")
        raw=raw_det(j,i)
        require(bool(raw),"Zero nonincidence determinant")
        monoms=list(raw)
        common=Counter(monoms[0])
        for m in monoms[1:]:common &= Counter(m)
        common_tuple=tuple(sorted(common.elements()))
        content=gcd(*(abs(c) for c in raw.values()))
        result={tuple(sorted((Counter(m)-common).elements())):c//content for m,c in raw.items()}
        return result,common_tuple,content

    signs={int(j):s for j,s in meta["column_signs"].items()}
    proofs={int(j):p for j,p in meta["orientation_proofs"].items()}
    require(set(signs)==set(proofs),"Missing orientation proof")
    require(all(type(s) is int and s in (-1,1) for s in signs.values()),"Invalid column sign")
    done=set();active=set()
    def orient(j):
        require(j in signs and j not in active,"Missing/cyclic orientation proof")
        if j in done:return
        active.add(j)
        proof=proofs[j];row=proof["row"]
        p,_,_=sat(j,row);p={m:signs[j]*c for m,c in p.items()}
        if proof["kind"]=="monomial":
            require(len(p)==1 and next(iter(p.values()))>0,"Invalid monomial sign anchor")
        elif proof["kind"]=="propagation":
            parent_row,parent_col=proof["parent"]
            orient(parent_col)
            parent_p,_,_=sat(parent_col,parent_row)
            parent_p={m:signs[parent_col]*c for m,c in parent_p.items()}
            require(p==parent_p,"Orientation propagation identity is false")
        else:
            raise ValueError("Unknown orientation proof type")
        active.remove(j);done.add(j)
    for j in signs:orient(j)

    # Check all true incidence determinants: omitted base vertices must not
    # silently become positive 'nonincidences' during reconstruction.
    for j,f in enumerate(F):
        for i in f:
            require(not raw_det(j,i),f"Nonzero reconstructed incidence {(i,j)}")

    generators=[]
    maximum=meta["max_generator_degree"]
    require(type(maximum) is int and 1<=maximum<=100,"Invalid maximum generator degree")
    for entry in bundle["generators"]:
        stored=decode_packed(entry["polynomial"],len(names))
        provenance=entry["provenance"];kind=provenance["kind"]
        if kind=="slack":
            i,j=provenance["row"],provenance["column"]
            require(j in done and provenance["sign"]==signs[j],"Unjustified generator sign")
            p,common,content=sat(j,i)
            raw_mode=meta.get('normalization')=='raw_signed_determinants'
            require((1 if raw_mode else content)==provenance["content"],"Wrong positive content divisor")
            packed=provenance["monomial"]
            divisor=[]
            require(type(packed) is int and 0<=packed<1<<(8*len(names)),"Bad monomial divisor")
            for k in range(len(names)):divisor.extend([k]*((packed>>(8*k))&255))
            require(tuple(divisor)==(() if raw_mode else common),"Wrong positive monomial divisor")
            actual={m:signs[j]*c for m,c in (raw_det(j,i) if raw_mode else p).items()}
        elif kind=="variable":
            k=provenance["index"]
            require(type(k) is int and 0<=k<len(names),"Invalid variable index")
            actual={(k,):1}
        elif kind=="constant":
            actual={():1}
        else:
            raise ValueError("Unknown generator type")
        require(actual==stored,"Stored generator differs from independently rebuilt determinant")
        require(max(map(len,actual))<=maximum,"Generator degree exceeds recorded limit")
        generators.append(actual)
    terms=bundle["terms"]
    require(bool(terms),"Empty certificate")
    total=Fraction(0);residual=defaultdict(Fraction)
    max_factors=0
    max_factors_allowed=meta.get('max_factors',2)
    require(type(max_factors_allowed) is int and 1<=max_factors_allowed<=5,'Invalid factor limit')
    for term in terms:
        w=Fraction(term["weight"])
        require(w>0,"Nonpositive certificate weight")
        indices=term["factors"]
        require(1<=len(indices)<=max_factors_allowed and all(type(i) is int and 0<=i<len(generators) for i in indices),"Invalid generator product")
        p={():1}
        for i in indices:p=mult(p,generators[i])
        require(bool(p),"Zero polynomial product")
        for m,c in p.items():residual[m]+=w*c
        total+=w;max_factors=max(max_factors,len(indices))
    require(total==1,"Weights do not sum exactly to one")
    require(all(c==0 for c in residual.values()),"Certificate identity has nonzero exact residual")
    return {"status":"verified_exact","terms":len(terms),"generators":len(generators),
            "max_factors":max_factors,"max_generator_degree":maximum,
            "verified_orientations":len(done),"facets":len(F),"vertices":n,
            "identity_zero":True,"weights_strictly_positive":True,"weight_sum":"1",
            "positive_scaling_forest":True,"flag_rank_witness":True,
            "facet_basis_rank_witnesses":True,"facet_sha256":digest,
            "independent_arithmetic":"tuple monomials, permutation determinants, Fraction"}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("path",type=Path,help="certificate JSON file or directory")
    p.add_argument("--report",type=Path)
    args=p.parse_args(argv)
    paths=[args.path] if args.path.is_file() else sorted(args.path.glob("*.json"))
    require(bool(paths),"No certificate JSON files found")
    results={};failed=False
    for path in paths:
        try:
            result=verify_bundle(json.loads(path.read_text()));results[path.stem]=result
            print(f"{path.stem}: VERIFIED EXACT ({result['terms']} terms; rank, scaling, orientation and identity checked)")
        except Exception as e:
            results[path.stem]={"status":"verification_failed","error":str(e)};failed=True
            print(f"{path.stem}: FAILED: {e}",file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(results,indent=2)+"\n")
    print(f"Verified {sum(r['status']=='verified_exact' for r in results.values())}/{len(results)}")
    return 1 if failed else 0

if __name__=="__main__":
    raise SystemExit(main())
