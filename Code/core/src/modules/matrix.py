from itertools import chain
import numpy as np
from sage.matrix import *

def get_unique_entries_of_matrix(M):
    """
    Returns a list of unique entries of matrix M
    """
    return np.sort(np.unique(list(chain.from_iterable(M))))

def get_vars_in_matrix(M):
    """
    Returns a list of variables in matrix M 
    """
    return np.delete(np.unique(get_unique_entries_of_matrix(M)),[0,1])

def get_num_vars_in_matrix(M):
    """
    Returns the number of variables in matrix M 
    """
    return get_vars_in_matrix(M).size

def get_hash_table_from_matrix(M):
    """
    Returns hash table whose elements are (i,j):M[i,j]
    """
    return {(i, j):M[i,j] for i, row in enumerate(M) for j, col in enumerate(M[1])}