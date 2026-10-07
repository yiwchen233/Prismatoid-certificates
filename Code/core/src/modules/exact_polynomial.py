"""Small exact integer-polynomial fallback for environments without Sage.

Sage installations use Sage's QQ polynomial ring instead. This implementation is
not a Sage mock: it is a separate explicit backend for the same sparse polynomials.
"""
from .certificate_geometry import canonical, multiply, degree, BITS, MASK

class ExactRing:
    def __init__(self, names):
        self.names = tuple(names)
        self._gens = tuple(ExactPolynomial(self, ((1 << (BITS*i), 1),)) for i in range(len(names)))
    def gens(self): return self._gens
    def ngens(self): return len(self.names)
    def __call__(self, value):
        if isinstance(value, ExactPolynomial):
            if self.names != value.ring.names: raise ValueError('Polynomial ring mismatch')
            return value
        if isinstance(value, str):
            if value in self.names: return self._gens[self.names.index(value)]
            value = int(value)
        if isinstance(value, dict):
            packed = {}
            for exp, c in value.items():
                if len(exp) != len(self.names): raise ValueError('Exponent length mismatch')
                packed[sum(int(e) << (BITS*i) for i,e in enumerate(exp))] = int(c)
            return ExactPolynomial(self, canonical(packed))
        return ExactPolynomial(self, () if int(value)==0 else ((0,int(value)),))
    def __repr__(self): return 'Exact integer polynomial ring in '+', '.join(self.names)

class ExactPolynomial:
    __slots__ = ('ring', 'terms')
    def __init__(self, ring, terms): self.ring,self.terms=ring,tuple(terms)
    def __hash__(self): return hash((self.ring.names,self.terms))
    def __eq__(self, other):
        try: other=self.ring(other)
        except (TypeError,ValueError): return False
        return self.terms == other.terms
    def __bool__(self): return bool(self.terms)
    def __mul__(self, other): return ExactPolynomial(self.ring,multiply(self.terms,self.ring(other).terms))
    __rmul__=__mul__
    def __add__(self, other):
        d=dict(self.terms)
        for m,c in self.ring(other).terms: d[m]=d.get(m,0)+c
        return ExactPolynomial(self.ring,canonical(d))
    __radd__=__add__
    def __neg__(self): return ExactPolynomial(self.ring,tuple((m,-c) for m,c in self.terms))
    def __sub__(self,other): return self+-self.ring(other)
    def __pow__(self,n):
        if not isinstance(n,int) or n<0: raise ValueError('Nonnegative integer exponent required')
        p=self.ring(1)
        for _ in range(n): p=p*self
        return p
    def dict(self): return {tuple((m>>(BITS*i))&MASK for i in range(self.ring.ngens())):c for m,c in self.terms}
    def degree(self): return degree(self.terms)
    def number_of_terms(self): return len(self.terms)
    def __repr__(self):
        parts=[]
        for m,c in self.terms:
            xs=[]
            for i,name in enumerate(self.ring.names):
                e=(m>>(BITS*i))&MASK
                if e: xs.append(name if e==1 else f'{name}^{e}')
            parts.append(str(c)+('*'+'*'.join(xs) if xs else ''))
        return ' + '.join(parts).replace('+ -','- ') if parts else '0'
    __str__=__repr__

def to_ring(ring, p):
    n=ring.ngens()
    return ring({tuple((m>>(BITS*i))&MASK for i in range(n)):c for m,c in p})

def from_ring(p):
    return canonical({sum(int(e)<<(BITS*i) for i,e in enumerate(exp)):int(c) for exp,c in p.dict().items()})
