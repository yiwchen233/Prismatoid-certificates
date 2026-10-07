"""Shared exact geometry for the repaired NonRealizabilityTest implementation.

No candidate-specific recipes, certificates, or saved reductions are read. LP solutions are only proposals: every accepted
certificate is checked using Python integers / fractions. Exponents are encoded
in 8-bit fields (base 256), allowing total polynomial degree at most 255.
"""
from __future__ import annotations
import ast
import hashlib
import itertools
import json
import math
import random
import re
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

VERSION = "1.2.9-core-patch"
BITS = 8
MASK = (1 << BITS) - 1


def canonical(poly):
    return tuple(sorted((int(m), int(c)) for m, c in poly.items() if c))


def multiply(a, b):
    out = defaultdict(int)
    for ma, ca in a:
        for mb, cb in b:
            out[ma + mb] += ca * cb
    return canonical(out)


def scale(p, s):
    return tuple((m, s*c) for m, c in p)


def degree(p):
    def deg(m):
        total = 0
        while m:
            total += m & MASK
            m >>= BITS
        return total
    return max((deg(m) for m, c in p), default=-1)


def saturate(poly, nvars):
    """Divide ONLY by a positive monomial and a positive integer gcd."""
    if not poly:
        return (), 0, 1
    common = 0
    for i in range(nvars):
        shift = BITS * i
        e = min((m >> shift) & MASK for m, c in poly)
        common += e << shift
    content = math.gcd(*(abs(c) for m, c in poly))
    return tuple((m-common, c//content) for m, c in poly), common, content


def facet_hash(facets):
    return hashlib.sha256(json.dumps(facets, separators=(",", ":")).encode()).hexdigest()


def rank_witness(pattern):
    """Triangular nonsingular minor spanning all columns; return (row,col) pivots.

    A row with a single nonzero among remaining columns is a pivot. Removing
    it and its column recursively yields a triangular minor with positive
    diagonal. This is an incidence-only sufficient rank test, not numerical rank.
    """
    if not pattern or not pattern[0]:
        return []
    remaining = set(range(len(pattern[0])))
    used = set()
    pivots = []
    while remaining:
        hit = None
        for i, row in enumerate(pattern):
            if i in used:
                continue
            supp = [j for j in remaining if row[j]]
            if len(supp) == 1:
                hit = (i, supp[0])
                break
        if hit is None:
            return None
        i, j = hit
        pivots.append([i, j]); used.add(i); remaining.remove(j)
    return pivots


def flag_witness(facets, flag, dimension=5):
    if len(flag) != dimension+1 or len(set(flag)) != dimension+1 or any(not 0 <= j < len(facets) for j in flag):
        return None
    n = 1 + max(itertools.chain.from_iterable(facets))
    return rank_witness([[i not in facets[j] for j in flag] for i in range(n)])


def facet_bases(facets, dimension=5):
    """Choose affinely spanning rows by a monomial-minor certificate."""
    bases, witnesses = [], []
    sets = [set(f) for f in facets]
    for j, f in enumerate(facets):
        found = False
        for b in itertools.combinations(f, dimension):
            # Columns of the transposed submatrix are the five selected vertices.
            witness = rank_witness([[v not in g for v in b] for g in sets])
            if witness is not None:
                bases.append(list(b)); witnesses.append(witness); found = True; break
        if not found:
            raise ValueError(f"No incidence-certified facet basis for facet {j}")
    return bases, witnesses


def sample_flag(facets, rng, exclude=(), dimension=5):
    """Require all nonsimplicial facets, sample remaining columns, certify rank."""
    required = [j for j,f in enumerate(facets) if len(f)>dimension]
    count = dimension+1-len(required)
    if count < 0:
        raise ValueError("More nonsimplicial facets than reduced columns; this reduction is unsupported")
    choices = [j for j in range(len(facets)) if j not in required]
    excluded = {frozenset(f) for f in exclude}
    for _ in range(50000):
        flag = required + sorted(rng.sample(choices, count))
        if frozenset(flag) not in excluded and flag_witness(facets, flag, dimension) is not None:
            return flag
    raise ValueError("No new rank-certified flag found in the sampling budget")


def normalized_matrix(facets, flag, rng):
    """Positive row/column scaling: set one spanning-forest edge per union to 1."""
    n = 1+max(itertools.chain.from_iterable(facets))
    edges = [(i,j) for i in range(n) for j, f in enumerate(flag) if i not in facets[f]]
    order = list(edges); rng.shuffle(order)
    parent = list(range(n+len(flag)))
    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]; v = parent[v]
        return v
    ones = set()
    for i,j in order:
        a,b = find(i),find(n+j)
        if a != b:
            parent[a] = b; ones.add((i,j))
    tokens = [[0]*len(flag) for _ in range(n)]
    names = []
    for i,j in edges:
        if (i,j) in ones:
            tokens[i][j] = 1
        else:
            name = f"x_{i}_{flag[j]}"
            tokens[i][j] = name; names.append(name)
    return tokens


def matrix_encoding(tokens):
    width = len(tokens[0]) if tokens else 0
    names = sorted({x for row in tokens for x in row if isinstance(x,str)})
    lookup = {x: 1 << (BITS*i) for i,x in enumerate(names)}
    matrix = []
    for row in tokens:
        if not width or len(row) != width:
            raise ValueError("Reduced matrix rows must have the same positive width")
        if any(x not in (0,1) and x not in lookup for x in row):
            raise ValueError("Reduced entries must be 0, 1, or distinct variables")
        matrix.append([None if x == 0 else (0 if x == 1 else lookup[x]) for x in row])
    flat = [x for row in tokens for x in row if isinstance(x,str)]
    if len(flat) != len(set(flat)):
        raise ValueError("A variable was repeated in distinct reduced-matrix entries")
    return matrix,names


def validate_reduction(facets, flag, tokens):
    dimension = len(flag)-1
    witness = flag_witness(facets, flag, dimension)
    if witness is None or not {j for j,f in enumerate(facets) if len(f)>dimension}.issubset(flag):
        raise ValueError("Six selected columns must contain both bases and a rank witness")
    n = 1+max(itertools.chain.from_iterable(facets))
    if len(tokens) != n or any(len(r) != len(flag) for r in tokens):
        raise ValueError("Incorrect reduced-matrix shape")
    matrix_encoding(tokens)
    parent = list(range(n+len(flag)))
    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]; v = parent[v]
        return v
    for i,row in enumerate(tokens):
        for j,x in enumerate(row):
            if (x == 0) != (i in facets[flag[j]]):
                raise ValueError(f"Zero pattern mismatch at {(i,j)}")
            if x == 1:
                a,b = find(i),find(n+j)
                if a == b:
                    raise ValueError("Unit entries contain a cycle: scaling not justified")
                parent[a] = b
    return witness


def determinant_engine(matrix):
    """Memoized Laplace expansion with integer coefficients and sparse monomials."""
    @lru_cache(maxsize=None)
    def minor(rows, cols):
        if not rows:
            return ((0,1),)
        # Choose the sparsest row for this minor, preserving permutation parity.
        pos = min(range(len(rows)), key=lambda k: sum(matrix[rows[k]][j] is not None for j in cols))
        row = rows[pos]
        remaining_rows = rows[:pos]+rows[pos+1:]
        out = defaultdict(int)
        for k,j in enumerate(cols):
            mon = matrix[row][j]
            if mon is None:
                continue
            sign = -1 if (pos+k)%2 else 1
            for m,c in minor(remaining_rows, cols[:k]+cols[k+1:]):
                out[m+mon] += sign*c
        return canonical(out)
    def det(rows):
        if len(set(rows)) != len(rows):
            return ()
        sign = -1 if sum(rows[i]>rows[j] for i in range(len(rows)) for j in range(i+1,len(rows)))%2 else 1
        p = minor(tuple(sorted(rows)), tuple(range(len(matrix[0]))))
        return p if sign == 1 else scale(p,-1)
    det.cache_info = minor.cache_info
    det.clear = minor.cache_clear
    return det


def build_generators(facets, flag, tokens, max_degree=3, log=print, simplify=True):
    """Build strict-positive polynomials with checkable orientation provenance."""
    if not 1 <= max_degree <= 100:
        raise ValueError("max_degree must be between 1 and 100")
    fw = validate_reduction(facets, flag, tokens)
    bases, bw = facet_bases(facets, len(flag)-1)
    matrix,names = matrix_encoding(tokens)
    det = determinant_engine(matrix)
    cols = []
    for j,f in enumerate(facets):
        entries = []
        for i in range(len(matrix)):
            if i in f:
                # Selected bases must make all true incidences vanish identically.
                if det(bases[j]+[i]):
                    raise ValueError(f"Nonzero determinant at incidence {(i,j)}")
                continue
            raw = det(bases[j]+[i])
            if not raw:
                raise ValueError(f"Identically zero nonincidence determinant {(i,j)}")
            p,mon,gcd = saturate(raw,len(names))
            entries.append({"row":i,"column":j,"poly":p,"monomial":mon,"content":gcd})
        cols.append(entries)
    log(f"determinants reconstructed; {len(names)} variables; cache {det.cache_info().currsize}")
    det.clear()
    signs = {}; proofs = {}; known = {}
    remaining = set(range(len(facets)))
    while remaining:
        changed = False
        for j in sorted(remaining):
            hit = None
            for e in cols[j]:
                p = e["poly"]
                if len(p) == 1:
                    s = 1 if p[0][1] > 0 else -1
                    hit = (s,{"kind":"monomial","row":e["row"]});break
                if p in known:
                    hit = (1,{"kind":"propagation","row":e["row"],"parent":known[p]});break
                neg = scale(p,-1)
                if neg in known:
                    hit = (-1,{"kind":"propagation","row":e["row"],"parent":known[neg]});break
            if hit is None:
                continue
            s,proof = hit; signs[j]=s; proofs[j]=proof
            for e in cols[j]:
                p = scale(e["poly"],s)
                known.setdefault(p,[e["row"],j])
            remaining.remove(j); changed=True
        if not changed:
            break
    log(f"oriented {len(signs)}/{len(facets)} columns; unresolved {sorted(remaining)}")
    by_poly = {}
    for j in sorted(signs):
        for e in cols[j]:
            p = scale(e["poly"],signs[j])
            if not simplify:
                p = tuple((m+e["monomial"], c*e["content"]) for m,c in p)
            if degree(p) <= max_degree:
                by_poly.setdefault(p,{"kind":"slack", "row":e["row"],"column":j,
                   "monomial":e["monomial"] if simplify else 0,"content":e["content"] if simplify else 1,"sign":signs[j]})
    # All variables and 1 are strictly positive; they participate in products.
    by_poly.setdefault(((0,1),),{"kind":"constant"})
    for i,name in enumerate(names):
        by_poly.setdefault(((1 << (BITS*i),1),),{"kind":"variable","index":i})
    generators = list(by_poly.items())
    log(f"{len(generators)} unique saturated generators of degree <= {max_degree}")
    meta = {"facets":facets,"flag":flag,"matrix":tokens,"variable_names":names,
            "facet_bases":bases,"basis_witnesses":bw,"flag_witness":fw,
            "column_signs":signs,"orientation_proofs":proofs,"unoriented_columns":sorted(remaining),
            "normalization":("divide_all_common_positive_monomials_and_positive_integer_content" if simplify else "raw_signed_determinants"),
            "dimension":len(flag)-1,"max_generator_degree":max_degree,"version":VERSION,"facet_sha256":facet_hash(facets)}
    return generators,meta


def build_products(generators, n_factors=2, log=print):
    if not 1 <= n_factors <= 5:
        raise ValueError("n_factors must be in 1,...,5")
    polys = {p:[i] for i,(p,pr) in enumerate(generators)}
    for k in range(2, n_factors+1):
        for ids in itertools.combinations_with_replacement(range(len(generators)), k):
            p = ((0,1),)
            for i in ids: p = multiply(p, generators[i][0])
            if not p: raise ArithmeticError("Product of nonzero polynomials became zero")
            polys.setdefault(p, list(ids))
    log(f"{len(polys)} distinct products / LP variables")
    return list(polys.items())
