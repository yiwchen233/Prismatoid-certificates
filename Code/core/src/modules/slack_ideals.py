from . import certificate_geometry as certgeom
import random
import copy as cp
import itertools
from itertools import chain, product as iter_prod
import numpy as np

from sage.all import (
    CombinatorialPolyhedron,
    PolynomialRing,
    matrix,
    flatten,
    QQ,
    set_random_seed,
    Graph
)

"""
Macaulay2               |  SageMath(Python)
----------------------- | ----------------------------  
abstractFaceLattice     |  get_abstract_face_lattice
findAbstractDim         |  get_abstract_dim
flagFromPosetCoatoms    |  flag_from_poset_coatoms
findFlag                |  get_flag
                        |  get_polynomial_ring
symbolicSlackMatrix     |  get_symbolic_slack_matrix
getAbstractFacetBases   |  get_abstract_facet_bases
containsFlag            |  contains_flag_matrix
                        |  get_nonsimplicial_facets
                        |  get_num_nonzero_entries
reducedSlackMatrix      |  reduced_slack_matrix
setOnesForest           |  set_ones_forest
"""

def get_abstract_face_lattice(coatoms):
    """ 
    Creates a CombinatorialPolyehdron object (Polytope) 
    based on the list of facets (coatoms) provided and returns
    the abstract face lattice, where the vertex index starts with 0.

    :param coatoms: a list of a list of integer facet indices 
        ex. [[1,2,3,4],[1,2,5,6],[1,3,5,7],[2,4,6,8],[3,4,7,8],[5,6,7,8]]
    :returns: Poset

    Documentation:
    - https://doc.sagemath.org/html/en/reference/discrete_geometry/sage/geometry/polyhedron/combinatorial_polyhedron/base.html#sage.geometry.polyhedron.combinatorial_polyhedron.base.CombinatorialPolyhedron.face_by_face_lattice_index
    - https://doc.sagemath.org/html/en/reference/discrete_geometry/sage/geometry/polyhedron/combinatorial_polyhedron/combinatorial_face.html#sage.geometry.polyhedron.combinatorial_polyhedron.combinatorial_face.CombinatorialFace.ambient_V_indices
    - https://doc.sagemath.org/html/en/reference/discrete_geometry/sage/geometry/polyhedron/combinatorial_polyhedron/combinatorial_face.html#sage.geometry.polyhedron.combinatorial_polyhedron.combinatorial_face.CombinatorialFace.ambient_Hrepresentation
    - https://ask.sagemath.org/question/35605/is-it-possible-to-compute-the-face-lattice-of-a-polytope-from-its-vertex-facet-incidences/
    """

    def f(i): 
        """
        Helper function that relabels the face lattice function output (see documentation above).
        """
        return (C.face_by_face_lattice_index(i).ambient_V_indices(), C.face_by_face_lattice_index(i).ambient_H_indices())

    C = CombinatorialPolyhedron(coatoms)
    F = C.face_lattice()  
    return F.relabel(f) 

def get_abstract_dim(coatoms):
    """
    Creates a CombinatorialPolyehdron object (Polytope) 
    based on the list of facets (coatoms) provided and returns
    the dimension of the Polytope.

    :param coatoms: a list of a list of integer facet indices 
        ex. [[1,2,3,4],[1,2,5,6],[1,3,5,7],[2,4,6,8],[3,4,7,8],[5,6,7,8]]
    :returns: int, dimension of the polyhedron
    """
    return CombinatorialPolyhedron(coatoms).dim()

def flag_from_poset_coatoms(i, coatoms):
    """ 
    Helper function for get_flag() function

    :param coatoms: a list of a list of integer facet indices 
        ex. [[1,2,3,4],[1,2,5,6],[1,3,5,7],[2,4,6,8],[3,4,7,8],[5,6,7,8]]
    :param i: int, facet index 
    :returns: a list of indices of coatoms elements that make up a flag in the Poset ex. [1,2,3,4]
    """
    # Get face lattice as poset object
    Pos = get_abstract_face_lattice(coatoms)

    # Get list of maximal chains
    M = Pos.maximal_chains()

    # Verify that all the chains in the list are the longest maximal chains
    C = [M[0]]
    for m in M:
        if len(m) > len(C[0]):
            C = [m]
        elif len(m) == len(C[0]):
            C.append(m)

    # Find a set of possible flags
    d = len(C[0]) - 1
    flags = set()
    for c in C:
        F = ()
        for j in range(d+1):
            facetIndex = c[d-j][1]
            for index in facetIndex:
                if j == 0 or j > 0 and index not in c[d-j+1][1]:
                    F += (index, )
                    break
        flags.add(F)
    flags = list(flags)
    flags.sort()

    # Return the first flag that has the coatom with facet index i
    for f in flags:
        if i in f:
            return f 

    # TODO: Properly handle exceptions
    self.logger.info("ERROR: Flag not found.")
    return None

def get_flag(coatoms, i=0):
    """ 
    Returns a list F of indices of coatoms elements that make up a flag in the Poset.

    :param coatoms: a list of a list of integer facet indices 
        ex. [[1,2,3,4],[1,2,5,6],[1,3,5,7],[2,4,6,8],[3,4,7,8],[5,6,7,8]]
    :param i: int, facet index 
        (default 0)
    :returns: a list of facet indices that make up the flag ex. [1,2,3,4]

    Documentation:
    - https://doc.sagemath.org/html/en/reference/combinat/sage/combinat/posets/posets.html#sage.combinat.posets.posets.FinitePoset.maximal_chains
    """
    return flag_from_poset_coatoms(i, coatoms)

def get_polynomial_ring(coatoms):
    """
    Creates a Polynomial Ring based on the list of facet indices (coatoms).

    :param coatoms: a list of a list of integer facet indices 
        ex. [[1,2,3,4],[1,2,5,6],[1,3,5,7],[2,4,6,8],[3,4,7,8],[5,6,7,8]]
    :returns: PolynomialRing in the rational field made up of x0...xn-1 where 
        n is the number of non-zero entries from a list of vertices F
    
    Documentation:
    - https://doc.sagemath.org/html/en/reference/polynomial_rings/sage/rings/polynomial/polynomial_ring_constructor.html#sage.rings.polynomial.polynomial_ring_constructor.PolynomialRing
    """
    vertices = sorted(set(flatten(coatoms)))
    r, c = len(vertices), len(coatoms)
    support = np.zeros((r, c))
    coords_nonzero_entries = []
    for i, vert in enumerate(vertices):
        for j, facet in enumerate(coatoms):
            if vert not in facet:
                support[i, j] = 1
                coords_nonzero_entries.append((i,j))
    return PolynomialRing(QQ, len(coords_nonzero_entries), var_array=['x'])

def get_symbolic_slack_matrix(F, R):
    """
    Constructs a symbolic slack matrix out of the list of vertices F and ring R.
    
    :param F: list of vertices
    :param R: Polynomial Ring
    :returns: symbolic slack matrix
    """
    coatoms = sorted(set(flatten(F)))
    r, c = len(coatoms), len(F)
    support = np.zeros((r, c))
    coords_nonzero_entries = []
    for i, vert in enumerate(coatoms):
        for j, facet in enumerate(F):
            if vert not in facet:
                support[i, j] = 1
                coords_nonzero_entries.append((i,j))
    # coords_nonzero_entries = np.argwhere(support != 0)
    n_vars = R.ngens()
    if n_vars > 0 and n_vars < len(coords_nonzero_entries):
        logger.info(
            f" -- warning: not enough variables: {n_vars} < {len(coords_nonzero_entries)}. "
            "Creating new ring."
        )
        R = QQ[','.join([f'x{i}' for i in range(len(coords_nonzero_entries))])]
    vars = list(R.gens())
    symb_slack_matrix = matrix(R, np.zeros((r, c)))
    for i, coords in enumerate(coords_nonzero_entries):
        symb_slack_matrix[coords] = vars[i]
    return symb_slack_matrix

def get_abstract_facet_bases(d, coatoms=None):
    return certgeom.facet_bases([list(f) for f in (coatoms or [])], int(d))[0]

def contains_flag_matrix(fl, S):
    indices=list(fl)
    if not indices or len(set(indices))!=len(indices): return False
    if any(j<0 or j>=S.ncols() for j in indices): return False
    return certgeom.rank_witness([[S[i,j]!=0 for j in indices] for i in range(S.nrows())]) is not None

def get_nonsimplicial_facets_matrix(S, d):
    """
    Helper function for reduced_slack_matrix which returns nonsimplicial facet columns.

    :param S: matrix, the slack matrix
    :param d: int, dimension of polytope
    :return list of column index in matrix S which contains nonsimplicial facets

    TODO: This is not working properly
    Original Macaulay2 code: 
        nonSimpF := positions(entries transpose S, r -> (v - nonzeroEntries(matrix {r}) > d));
    """
    
    v = S.nrows()
    result = []
    for i, e in enumerate(S.transpose().rows()):
        if v - get_num_nonzero_entries(e) > d:
            result.append(i)
    return result

def get_nonsimplicial_facets_list(F, d):
    """
    Finds nonsimplicial facets in polytope with facets F and dimension d.

    :param F: list of facets (coatoms)
    :param d: int, dimension of polytope
    :return list of nonsimplicial facets and list of nonsimplicial facet indices
    """
    nonsimplicial_facets = []
    nonsimplicial_facets_indices = []
    for i in range(len(F)):
        f = F[i]
        if len(f) != d:
            nonsimplicial_facets.append(f)
            nonsimplicial_facets_indices.append(i)  
    return nonsimplicial_facets, nonsimplicial_facets_indices

def get_num_nonzero_entries(arr):
    """
    Helper function for get_nonsimplicial_facets which returns the number of nonzero entries in array arr.

    :param arr: list of integers
    :return int, number of nonzero entries in list arr
    """
    return len([e for e in arr if e != 0])

def reduced_slack_matrix(fl, d, S):
    """Use exactly the requested columns; never silently add columns or change flags."""
    indices=list(fl)
    if len(indices)!=int(d)+1 or not contains_flag_matrix(indices,S):
        raise ValueError('Expected dimension+1 distinct rank-certified columns')
    required=get_nonsimplicial_facets_matrix(S,int(d))
    if not set(required).issubset(indices):
        raise ValueError('The flag must already contain every nonsimplicial facet')
    return S[:,indices]

def set_ones_forest(S, T=None, rs=0):
    """Positive row/column scaling with a checked acyclic edge set."""
    r,c=S.nrows(),S.ncols();parent=list(range(r+c))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    explicit=bool(T)
    edges=[tuple(sorted(map(int,e))) for e in T] if explicit else [(i,r+j) for i in range(r) for j in range(c) if S[i,j]!=0]
    if not explicit: random.Random(int(rs)).shuffle(edges)
    forest=[];W=cp.copy(S)
    for i,v in edges:
        if not (0<=i<r and r<=v<r+c) or S[i,v-r]==0:
            raise ValueError('Invalid forest edge')
        a,b=find(i),find(v)
        if a==b:
            if explicit: raise ValueError('Supplied unit entries contain a cycle')
            continue
        parent[a]=b;forest.append((i,v));W[i,v-r]=1
    return W,sorted(forest)
