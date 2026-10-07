"""Sage interface to Gurobi for non-realizability certificates of combinatorial polytopes."""

import argparse
import copy as cp
import csv
import gc
from itertools import chain, product as iter_prod
import numpy as np
import os
import random
import time

from modules.logger import get_logger
from modules.macaulay2_parser import fix_m2_list, sage_orientation
from modules import certificate_geometry as certgeom
from modules.exact_polynomial import ExactRing, to_ring, from_ring
import ast

try:
    import sage.all
    HAVE_SAGE = True
except ModuleNotFoundError as exc:
    if exc.name not in {'sage','sage.all'}: raise
    HAVE_SAGE = False

if HAVE_SAGE:
    from sage.all import (
        macaulay2,
        det,
        product,
        matrix,
        vector,
        MixedIntegerLinearProgram,
        QQ,
        zero_vector,
        ZZ,
        PolynomialRing
    )
    from sage.rings.polynomial.polydict import ETuple
    
    from modules.matrix import get_unique_entries_of_matrix
    from modules.matrix import get_vars_in_matrix
    from modules.matrix import get_num_vars_in_matrix
    from modules.matrix import get_hash_table_from_matrix
    from modules.slack_ideals import get_abstract_face_lattice
    from modules.slack_ideals import get_abstract_dim
    from modules.slack_ideals import flag_from_poset_coatoms
    from modules.slack_ideals import get_flag
    from modules.slack_ideals import get_polynomial_ring
    from modules.slack_ideals import get_symbolic_slack_matrix
    from modules.slack_ideals import get_abstract_facet_bases
    from modules.slack_ideals import contains_flag_matrix
    from modules.slack_ideals import get_nonsimplicial_facets_matrix
    from modules.slack_ideals import get_nonsimplicial_facets_list
    from modules.slack_ideals import get_num_nonzero_entries
    from modules.slack_ideals import reduced_slack_matrix
    from modules.slack_ideals import set_ones_forest
    from modules.sphere_database import sphere_database
else:
    ETuple = tuple

CORE_PATCH_VERSION = "1.2.9-core-patch"

def _parse_indices(value):
    if value is None: return []
    if isinstance(value,str):
        value=ast.literal_eval(fix_m2_list(value))
    if not isinstance(value,(list,tuple,set,frozenset)):
        raise ValueError('Expected a list of integer indices')
    return [int(v) for v in value]

gc.enable()

DIR_PATH = os.path.dirname(os.path.realpath(__file__))

class NonRealizabilityTest:

    def __init__(
        self,
        check_certificate_m2="false",
        dimension=4,
        deep_sign_check="false",
        facets="{}",
        file_name="Altshuler_N10_3574",
        flag="{}",
        force_new_flag="false",
        gurobi_interface="matlab",
        include_rows="{}",
        language="m2",
        load_data="false",
        matrix_method="sphere_new",
        max_deg=2,
        n_factors=2,
        oriented="false",
        prismatoid="false",
        random_seed=0,
        redundant_facets="false",
        selected_cols="{}",
        selected_rows="{}",
        shuffle_constraints="false",
        sleep=3,
        small_determinants="false",
        suffix="",
        switch_to_sage="false",
    ):
        os.makedirs(os.path.join(DIR_PATH,'dump'), exist_ok=True)
        os.makedirs(os.path.join(DIR_PATH,'logs'), exist_ok=True)
        self.n_factors = int(n_factors)
        self.max_deg = max_deg

        self.check_certificate_m2 = check_certificate_m2
        self.deep_sign_check = deep_sign_check
        self.oriented = oriented
        self.small_determinants = small_determinants
        self.prismatoid = prismatoid
        self.dimension = dimension
        self.force_new_flag = force_new_flag
        self.load_data = load_data
        self.language = language
        self.redundant_facets = redundant_facets
        self.switch_to_sage = switch_to_sage

        self.facets = facets
        self.selected_cols = selected_cols
        self.selected_rows = selected_rows
        self.include_rows = include_rows
        self.flag = flag

        self.shuffle_constraints = shuffle_constraints

        self.file_name_old = file_name
        self.suffix = suffix
        self.file_name = file_name

        self.full_file_name = os.path.join(f"{DIR_PATH}/dump", f'{self.file_name}_iter{self.n_factors}_deg{self.max_deg}')

        self.logger = get_logger(os.path.join(f"{DIR_PATH}/logs", f'{self.file_name}_iter{self.n_factors}_deg{self.max_deg}_output'), suffix=self.suffix)

        if self.suffix:
            self.full_file_name += f'_{self.suffix}'

        if matrix_method in {"sphere_from_data", "sphere", "prismatoid_from_data", "prismatoid", "sphere_new"}:
            self._generate_constraints = getattr(self, f"matrix_{matrix_method}")
        else:
            raise NotImplementedError(
                'interface not implemented. '
                'Insert one of "sphere_from_data", "sphere", "sphere_new", "prismatoid_from_data", "prismatoid".'
            )

        self.gurobi_interface = gurobi_interface
        self.random_seed = random_seed
        self.R = None
        self.sleep = sleep

    def matrix_sphere_new(self):
        return (
            f'matrixSphereNew("{self.file_name_old}", {self.n_factors}, {self.max_deg}, '
            f'DeepSignCheck => {self.deep_sign_check}, '
            f'Dimension => {self.dimension}, '
            f'Facets => {self.facets}, '
            f'ForceNewFlag => {self.force_new_flag}, '
            f'LoadData => {self.load_data}, '
            f'Prismatoid => {self.prismatoid}, '
            f'Oriented => {self.oriented}, '
            f'SmallDeterminants => {self.small_determinants}, '
            f'SelectedColumns => {self.selected_cols}, '
            f'SelectedRows => {self.selected_rows}, '
            f'IncludeRows => {self.include_rows}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}, '
            f'Flag => {self.flag}, '
            f'RandomSeed => {self.random_seed}, '
            f'Suffix => "{self.suffix}", '
            f'SwitchToSage => {self.switch_to_sage}, '
            f'DumpSage => true'
            ');'
        )

    def matrix_sphere_from_data(self):

        return (
            f'matrixSphereFromData("{self.file_name}", '
            f'{self.n_factors}, {self.max_deg}, '
            f'Oriented => {self.oriented}, '
            f'SmallDeterminants => {self.small_determinants}, '
            f'SelectedColumns => {self.selected_cols}, '
            f'SelectedRows => {self.selected_rows}, '
            f'IncludeRows => {self.include_rows}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}, '
            f'Flag => {self.flag}, '
            f'RandomSeed => {self.random_seed}, '
            f'Suffix => "{self.suffix}",'
            f'SwitchToSage => {self.switch_to_sage}, '
            f'DumpSage => true'
            ');'
        )

    def matrix_sphere(self):

        return (
            f'matrixSphere("{self.file_name}", '
            f'({self.facets}, {self.dimension}, {self.n_factors}, {self.max_deg}), '
            f'Oriented => {self.oriented}, '
            f'SmallDeterminants => {self.small_determinants}, '
            f'SelectedColumns => {self.selected_cols}, '
            f'SelectedRows => {self.selected_rows}, '
            f'IncludeRows => {self.include_rows}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}, '
            f'Flag => {self.flag}, '
            f'RandomSeed => {self.random_seed}, '
            f'Suffix => "{self.suffix}",'
            f'SwitchToSage => {self.switch_to_sage}, '
            f'DumpSage => true'
            ');'
        )

    def matrix_prismatoid_from_data(self):

        return (
            f'matrixPrismatoidFromData("{self.file_name_old}", '
            f'{self.n_factors}, {self.max_deg}, '
            f'Oriented => {self.oriented}, '
            f'SmallDeterminants => {self.small_determinants}, '
            f'SelectedColumns => {self.selected_cols}, '
            f'SelectedRows => {self.selected_rows}, '
            f'IncludeRows => {self.include_rows}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}, '
            f'Flag => {self.flag}, '
            f'RandomSeed => {self.random_seed}, '
            f'Suffix => "{self.suffix}",'
            f'SwitchToSage => {self.switch_to_sage}, '
            f'DumpSage => true'
            ');'
        )

    def matrix_prismatoid(self):

        return (
            f'matrixPrismatoid("{self.file_name_old}", '
            f'{self.n_factors}, {self.max_deg}, '
            f'Oriented => {self.oriented}, '
            f'SmallDeterminants => {self.small_determinants}, '
            f'SelectedColumns => {self.selected_cols}, '
            f'SelectedRows => {self.selected_rows}, '
            f'IncludeRows => {self.include_rows}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}, '
            f'Flag => {self.flag}, '
            f'RandomSeed => {self.random_seed}, '
            f'Suffix => "{self.suffix}",'
            f'SwitchToSage => {self.switch_to_sage}, '
            f'DumpSage => true'
            ');'
        )

    @staticmethod
    def _flatten(nested_list):
        return list(chain.from_iterable(nested_list))

    @staticmethod
    def partition_factors(predicate, iterable):
        """
        Source: https://giannitedesco.github.io/2020/12/14/a-faster-partition-function.html
        """
        ts, fs = [], []
        t = ts.append
        f = fs.append
        for q, e in iterable:
            (t if predicate(q) else f)(q ** e)
        return ts, fs

    def sat_poly(self, f, coord_pair, sign_C):
        """
        -- INPUT: polynomial f
        -- OUTPUT: f divided by any (positive) monomial factors
        -- Note: the constant factor still appears in the result
        """
        if self.R(f).degree() == 0:
            return (self.R(1), coord_pair, sign_C), self.R(f)

        factors = f.factor()
        monomial_part, simplified_f = self.partition_factors(
            predicate=lambda q: q.number_of_terms() == 1 and q.degree() != 0,
            iterable=factors
        )
        return (product(monomial_part), coord_pair, sign_C), product(simplified_f + [factors.unit()])

    def find_first_sign(self, col, pos_sat):
        """
        -- INPUT: col = list of polynomials (in a certain column of slack matrix)
        --     pos_sat = list of polynomials already determined to be positive
        -- OUTPUT: if there exist g in col and p in posSat such that g % p == 0
        --     and g//p is a monomial, it returns the sign of g//p; otherwise it returns 0
        """
        for g in col:
            for p in pos_sat:
                quot = g // p
                if (g % p == 0) and quot.number_of_terms() == 1:
                    return self.sat_poly(quot, None, None)[1]
        return 0

    def find_sign(self, g, pos_sat):
        """
        -- INPUT: g = polynomial (in a certain column of slack matrix)
        --     pos_sat = list of polynomials already determined to be positive
        -- OUTPUT: if there exist g in col and p in posSat such that g % p == 0
        --     and g//p is a monomial, it returns the sign of g//p; otherwise it returns 0
        """
        for p in pos_sat:
            quot = g // p
            if (g % p == 0) and quot.number_of_terms() == 1:
                return self.sat_poly(quot, None, None)[1]
        return 0

    def pos_check(self, hash_M, rest_cols, pos_sat_hash, orientation):
        """
        -- INPUT: hash_M = hashTable whose keys are pairs of indices of a matrix M
        --                and values are nonzero entries of M
        --     rest_cols = columns left to check for sign
        --     pos_sat_hash = hash table of polynomials already determined to be positive
        --     orientation = list containing facets orientation (as pairs (col index, sign +1/-1))
        -- OUTPUT: rest_cols = columns whose sign are left to determine
        --    pos_sat_hash = list of polynomials entries determined to be > 0)
        --    pos_C = list of columns whose sign we determined
        --    orientation = updated orientation list
        """
        pos_C = set()
        for c in rest_cols:
            hash_col_C = {(i, j): v for (i, j), v in hash_M.items() if j == c}

            if self.deep_sign_check == "true":
                sign_C = {
                    self.find_sign(g, set(pos_sat_hash.values())) for g in hash_col_C.values()
                }
                if {1, -1}.issubset(sign_C):
                    self.logger.info(f"Conflicting signs: {sign_C}")
                    raise Exception(f"\nFound incompatible signs in column {c}")
            else:
                sign_C = {
                    self.find_first_sign(hash_col_C.values(), set(pos_sat_hash.values()))
                }
            # do we need _flatten(pos_sat_hash.values()) ??
            if sign_C == {0}:
                continue

            unique_sign_C = (sign_C - {0}).pop()

            orientation.update({c: unique_sign_C})
            # otherwise append index c to the list of columns for which we set the sign
            pos_C.add(c)

            # we add to posSatHash the unique elements in posPolyC multiplied
            # by sign and divided by possible monomial factors
            new_hash_col_C = dict(
                (
                    self.sat_poly(unique_sign_C * v, coord_pair, unique_sign_C)
                    for coord_pair, v in hash_col_C.items()
                )
            )
            pos_sat_hash.update(new_hash_col_C)
        rest_cols -= pos_C
        return rest_cols, pos_sat_hash, pos_C, orientation

    def col_signs(self, fbases, slack_matrix):
        """
        -- INPUT: Fbases = list of facet bases
        --        M = reconstructed slack matrix
        --        fileName = string, name of file
        -- OUTPUT: list posSat of polynomial entries in the reconstructed matrix with correct signs
        """
        rest_cols = set(range(len(fbases)))

        # hashTable whose keys are pairs of indices and values are nonzero entries of M
        r, c = slack_matrix.nrows(), slack_matrix.ncols()
        hash_M = {(i, j): slack_matrix[i,j] for i, j in iter_prod(range(r), range(c)) if slack_matrix[i,j] != 0}

        self.logger.info("\nCheck for reconstructed columns containing monomials.")
        # load orientation if given
        if self.oriented == "false":
            orientation = dict()
        else:
            orientation = sage_orientation(file_name=self.file_name, redundant_facets=self.redundant_facets)
        if len(orientation) > 0:

            self.logger.info("\nOrientation file found.")

            start = time.time()
            for c in rest_cols:
                hash_col_C = {(i, j): v for (i, j), v in hash_M.items() if j == c}

                mons = {k: v for k, v in hash_col_C.items() if v.number_of_terms() == 1}
                # if there are no monomials in the column c, then check another column
                if len(mons) == 0:
                    continue

                # compute signs of monomials and check they have same sign
                unique_signs = list({self.sat_poly(m, None, None)[1] for m in mons.values()})
                if not(all(s > 0 for s in unique_signs) or all(s < 0 for s in unique_signs)):
                    self.logger.info(f"Conflicting signs: {unique_signs}")
                    raise Exception(f"\nFound incompatible signs (from monomials) in column {c}")

                # sign of column c in given orientation
                sign_C = orientation[c]
                if unique_signs[0] != sign_C:
                    self.logger.info("Switching signs to the input orientation")
                    orientation = {k: -v for k, v in orientation.items()}

                break

            end = time.time()
            self.logger.info(f' -- {end - start:,.6f} seconds elapsed')

            self.logger.info('Creating pos_sat_hash')
            start = time.time()
            pos_sat_hash = dict(
                self.sat_poly(orientation[j] * v, (i, j), orientation[j]) 
                for (i, j), v in hash_M.items() if (
                    i in self.selected_rows and j in self.selected_cols
                    and self.include_rows.issubset(set(fbases[j]).union({i}))
                    and v.degree() <= int(self.max_deg)
                )
            )
            self.logger.info(f' -- {time.time() - start:,.6f} seconds elapsed')

            self.logger.info(f"\nOrientation : {sorted(list(orientation.items()))}")

            # selecting constraints contained in the flag columns divided by monomial factors
            self.logger.info("\nRemultiplying by monomial factors.")
            if self.small_determinants == "true":
                return {
                    ((i, j), k2): v if j in self.flag else k0 * v
                    for (k0, (i, j), k2), v in pos_sat_hash.items()
                }
            return {(k1, k2): k0 * v for (k0, k1, k2), v in pos_sat_hash.items()}
            
        # the orientation is not given
        start = time.time()
        pos_sat_hash = dict()
        pos_C = set()
        for c in rest_cols:
            hash_col_C = {(i, j): v for (i, j), v in hash_M.items() if j == c}

            mons = {k: v for k, v in hash_col_C.items() if v.number_of_terms() == 1}

            # if there are no monomials in the column c, then check another column
            if len(mons) == 0:
                continue

            # compute signs of monomials and check they have same sign
            unique_signs = list({self.sat_poly(m, None, None)[1] for m in mons.values()})
            if not(all(s > 0 for s in unique_signs) or all(s < 0 for s in unique_signs)):
                self.logger.info(f"Conflicting signs: {unique_signs}")
                raise Exception(f"\nFound incompatible signs (from monomials) in column {c}")

            sign_C = unique_signs[0]
            orientation.update({c: sign_C})

            # we get here if all monomials have the same sign
            pos_C.add(c)

            # we add to posSatHash the unique elements in hash_col_C multiplied by sign_C 
            # and divided by possible monomial factors

            new_hash_col_C = dict(
                self.sat_poly(sign_C * v, coord_pair, sign_C)
                for coord_pair, v in hash_col_C.items()
            )

            pos_sat_hash.update(new_hash_col_C)

        rest_cols -= pos_C
        end = time.time()
        self.logger.info(f' -- {end - start:,.6f} seconds elapsed')

        self.logger.info("\nOrientation file not found.")

        self.logger.info(f"\nIndices of columns containing monomials: {sorted(set(range(len(fbases))) - rest_cols)}")
        self.logger.info(f"Indices of columns with no monomials: {rest_cols}")

        self.logger.info("\nTest remaining reconstructed columns against polynomials in pos_sat_hash.")

        # Test remaining reconstructed columns for elements that now already
        # occur in the positive polynomial list.
        # Add these entries with appropriate sign to list of positive polynomials
        pos_C = set({-1})
        start = time.time()

        while len(rest_cols) != 0 and len(pos_C) != 0:
            rest_cols, pos_sat_hash, pos_C, orientation = self.pos_check(
                hash_M,
                rest_cols,
                pos_sat_hash,
                orientation
            )
            self.logger.info(f"List of columns left to fix: {rest_cols}")

        end = time.time()
        self.logger.info(f' -- {end - start:,.6f} seconds elapsed')

        if self.redundant_facets == "true":
            orientation_file_name = f"{self.file_name}_orientation_redundant_facets.txt"
        else:
            orientation_file_name = f"{self.file_name}_orientation.txt"
        
        self.dump_to_file("orientation", orientation_file_name, str(set(orientation.items())))

        if len(rest_cols) > 0:
            self.logger.info("Warning: rest_cols is non-empty after fixing the column signs.")

        self.logger.info(f"\nOrientation : {sorted(list(orientation.items()))}")

        # selecting constraints contained in the flag columns divided by monomial factors
        self.logger.info("\nRemultiplying by monomial factors.")
        if self.small_determinants == "true":
            return {
                ((i, j), k2): v if j in self.flag else k0 * v
                for (k0, (i, j), k2), v in pos_sat_hash.items() if (
                    i in self.selected_rows and j in self.selected_cols
                    and self.include_rows.issubset(set(fbases[j]).union({i}))
                    and v.degree() <= int(self.max_deg)
                )
            }
        return {
            ((i, j), k2): k0 * v for (k0, (i, j), k2), v in pos_sat_hash.items() if (
                i in self.selected_rows and j in self.selected_cols
                and self.include_rows.issubset(set(fbases[j]).union({i}))
                and v.degree() <= int(self.max_deg)
            )
        }

    @staticmethod
    def _split_standard_form(poly_dict, n_vars):
        constant_term = poly_dict.pop(ETuple([0] * n_vars), 0)
        return constant_term, poly_dict

    def _get_products_step(self, constr_dict, h, new_constraint_dict = None, last_iter = None):
        constr_list = list(constr_dict.keys())
        if h == 2:
            stratified_constrs = [
                [
                    (
                        constr_list[i] * Cj,
                        [
                            constr_dict[constr_list[i]][0]+constr_dict[Cj][0],
                            constr_dict[constr_list[i]][1]*constr_dict[Cj][1]
                        ]
                    ) for i in range(j+1)
                ]
                for j, Cj in enumerate(constr_list)
            ]
            new_constraint_dict = cp.copy(constr_dict)
        else:
            stratified_constrs = [
                self._flatten(
                    [
                        [
                            (
                                p * Ck,
                                [
                                    new_constraint_dict[p][0]+constr_dict[Ck][0],
                                    new_constraint_dict[p][1]*constr_dict[Ck][1]
                                ]
                            ) for p, _ in last_Cj
                        ] for last_Cj in last_iter[:k+1]
                    ]
                )
                for k, Ck in enumerate(constr_list)
            ]
        constrs = dict(self._flatten(stratified_constrs))

        self.logger.info(f"#unique products of {h} constraints: {len(constrs)}")
        new_constraint_dict.update(constrs)
        return new_constraint_dict, stratified_constrs

    def get_products(self, constraint_dict):
        """Generate the bounded family; 1 and every reduced variable participate."""
        provenance_by_poly = {p:pr for p,pr in self._all_generators}
        chosen = [(from_ring(p), provenance_by_poly[from_ring(p)]) for p in constraint_dict]
        # Keep identical insertion order under Sage and plain Python.
        products = certgeom.build_products(chosen, int(self.n_factors), self.logger.info)
        self._stage_generators = chosen
        self._stage_products = products
        self._batch_constraint_dict = {}
        legacy = list(constraint_dict.values())
        for p, ids in products:
            coords=[]; sign=1
            for idx in ids:
                coords.extend(legacy[idx][0]); sign*=legacy[idx][1]
            self._batch_constraint_dict[to_ring(self.R,p)] = [coords,sign]
        return self._batch_constraint_dict

    def get_coefficient_matrix(self, constraint_dict):
        # constraint_dict = dict(sorted(constraint_dict.items(), key=lambda item: item[1][0]))
        constraint_list = constraint_dict.keys()
        self.logger.info("Creating standard form of polynomials.")
        start = time.time()
        standard_forms = [p.dict() for p in constraint_list]
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info("\nIsolating constant terms.")
        start = time.time()
        constant_terms, split_standard_forms = list(
            zip(
                *[self._split_standard_form(sfp, n_vars=len(self.R.gens())) for sfp in standard_forms]
            )
        )
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info("\nCreating lists of monomials, coefficients, and constant terms.")
        start = time.time()
        list_mons_per_poly, sparse_matrix_entries_list = (
            [list(sfp.keys()) for sfp in split_standard_forms],
            [list(sfp.values()) for sfp in split_standard_forms]
        )
        sparse_matrix_entries = self._flatten(sparse_matrix_entries_list)
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info("\nCreating list of unique monomials.")
        start = time.time()
        set_mons = set(self._flatten(list_mons_per_poly))
        dict_mons = {mon: j+1 for j, mon in enumerate(set_mons)}
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info("\nGenerating row and column indices for sparse matrix.")
        start = time.time()
        sparse_matrix_rows = self._flatten([[i+1] * len(p) for i, p in enumerate(list_mons_per_poly)])
        # sparse_matrix_cols_list = [[dict_mons[m] for m in mp] for mp in list_mons_per_poly]
        sparse_matrix_cols = self._flatten([[dict_mons[m] for m in mp] for mp in list_mons_per_poly])
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info("\nAppending constant term entries.")
        start = time.time()
        if any(v != 0 for v in constant_terms):  # sum(constant_terms) > 0:
            indices_constant_terms, nonzero_constant_terms = list(zip(*[(i+1, c) for i, c in enumerate(constant_terms) if c != 0]))
            sparse_matrix_rows += indices_constant_terms
            sparse_matrix_cols += [len(set_mons)+1] * len(indices_constant_terms)
            sparse_matrix_entries += nonzero_constant_terms
        else:
            sparse_matrix_rows += [1]
            sparse_matrix_cols += [len(set_mons)+1]
            sparse_matrix_entries += [0]
            self.logger.info(f"Warning: no constant term column, adding a dummy 0 entry in position (1, {len(set_mons)+1}).")
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info(f"\nDumping sparse matrix to file {self.full_file_name}_matrix.txt")
        start = time.time()
        with open(f"{self.full_file_name}_matrix.txt", 'w') as outcsv:
            writer = csv.writer(outcsv, delimiter=' ', lineterminator='\n')
            for el in [sparse_matrix_rows, sparse_matrix_cols, sparse_matrix_entries]:
                writer.writerow(el)
        end = time.time()
        self.logger.info(f" -- {end - start:,.6f} seconds elapsed")

        self.logger.info(f"\n-> Number of rows: {len(list_mons_per_poly):,}")
        self.logger.info(f"-> Number of columns: {len(set_mons)+1:,}")
        self.logger.info(f"-> Number of non-zero entries: {len(sparse_matrix_rows):,}")

        return sparse_matrix_rows, sparse_matrix_cols, sparse_matrix_entries
    
    def solve_lp(self, matrix_fname=None, M=None):
        """Default standalone LP; batch subclasses retain their selected backend."""
        from scipy.sparse import coo_matrix, vstack
        from scipy.optimize import linprog
        if M is None:
            M=np.loadtxt(matrix_fname or self.full_file_name+'_matrix.txt',dtype=np.int64)
        rows,cols,values=M
        r=max(int(i) for i in rows); c=max(int(j) for j in cols)
        B=coo_matrix((values,([int(j)-1 for j in cols],[int(i)-1 for i in rows])),shape=(c,r)).tocsr()
        A=vstack([B,coo_matrix(np.ones((1,r)))],format='csr')
        rhs=np.zeros(c+1);rhs[-1]=1
        result=linprog(np.zeros(r),A_eq=A,b_eq=rhs,bounds=(0,None),method='highs',
            options={'time_limit':float(os.getenv('PRISMATOID_LP_TIME_LIMIT','300')),
                     'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
        self.logger.info('HiGHS status=%s: %s',result.status,result.message)
        if not result.success: return '',np.array([],dtype=int)
        witness=self.accept_exact_solution(result.x)
        return 'exact positive polynomial identity',np.array([i for i,w in witness],dtype=int)

#     def solve_lp_new(self, matrix_fname=None, M=None):
#         if M is None:
#             matrix_file_name = matrix_fname or f'{self.full_file_name}_matrix.txt'
#             M = np.loadtxt(matrix_file_name).astype(np.int32)

#         rr = np.max(M[0])
#         cc = np.max(M[1])

        #self.logger.info("Defining sparse matrix")
#         B = matrix(ZZ, {(M0i-1, M[1][i]-1): M[2][i] for i, M0i in enumerate(M[0])}, sparse=True)
#         B_npmatrix = np.array(B)

#         last_col = matrix(ZZ, rr, 1, {(i, 0): 1 for i in range(rr)}, sparse=True)

        #self.logger.info("Matrix D")
#         D = B.augment(last_col).transpose()
#         D_npmatrix = np.array(D)

#         num_vars = B_npmatrix.shape[0]
#         bounds = [(None, 0) for _ in range(num_vars)]
#         sol = linprog(c=np.ones(num_vars), A_eq=B_npmatrix.transpose(), b_eq=zero_vector(cc), A_ub=-np.ones((1, num_vars)), b_ub=np.array([1.0]), bounds=bounds)
#         sol_vars = sol.x
#         sol_fval = sol.fun + 1

#         self.logger.info(f"Objective value: {sol_fval}")

#         slacks = np.dot(D_npmatrix, sol_vars) - vector(list(zero_vector(cc))+[-1])
#         self.logger.info(f"Are there zero slacks? {any(slacks==0)}")

#         idx_nonzero_dual_vars = np.nonzero(sol_vars)[0]
#         self.logger.info(f"Indices of nonzero dual variables : {[m+1 for m in idx_nonzero_dual_vars]}")

#         sparse_subD = D[:-2, list(idx_nonzero_dual_vars)]

#         constant_terms_subD =  np.array(D[-2, list(idx_nonzero_dual_vars)])

#         # transform sparse_subD into numpy array
#         numpy_subD = np.array(sparse_subD)

        # a = array with row indices of nonzero elements, i.e. indices of monomials appearing in sparse_subD
        # b = array with column indices of nonzero elements
#         a, b = np.nonzero(numpy_subD)
#         unique_mons_index = list(np.unique(a))
#         mons_index = unique_mons_index + [cc-1]
#         self.logger.info(f"Column indices : {[m+1 for m in mons_index]}")

#         certificate_matrix = matrix(
#             np.concatenate(
#                 (numpy_subD[unique_mons_index, :].transpose(), constant_terms_subD.reshape(-1, 1)),
#                 axis=1
#             )
#         )

#         self.logger.info(f"Submatrix of nonzero primal constraints :\n{certificate_matrix}")
#         self.logger.info(f"Sum of nonzero primal constraints :\n{sum(certificate_matrix.rows())}")

#         str_certificate = " ".join([str(c+1) for c in mons_index])
#         for i in range(len(np.unique(b))):
#             mons_constr_cert = " ".join(
#                 [str(c) for c in certificate_matrix[i]]
#             )
#             str_certificate += f"\n{mons_constr_cert}"

#         with open(self.full_file_name + "_certificate.txt", "w") as text_file:
#             _ = text_file.write(str_certificate)

#         with open(self.full_file_name + "_certificate_rows.txt", "w") as text_file:
#             _ = text_file.write(" ".join(str(idx_nonzero_dual_vars)))
        
#         return str_certificate, idx_nonzero_dual_vars

#     def check_certificate(self, constraint_dict, fbases):
#         # TODO: This generates ValueError: could not convert string to float: '['
#         certificate_row = np.loadtxt(self.full_file_name + "_certificate_rows.txt").astype(np.int32)
# 
#         certificate_pairs = [(k, [i+1]+v) for i, (k, v) in enumerate(constraint_dict.items()) if i+1 in certificate_row]
#         certificate, coordinates = list(zip(*certificate_pairs))
# 
#         certificate_coords = [list(np.array(coord)+1) for _, coord, _ in coordinates]
# 
#         # self.logger.info("\nCertificate:")
#         # for p, (i, lst, sign) in certificate_pairs:
#         #     plus_one_list = list(map(tuple, np.array(lst) + 1))
#         #     self.logger.info(f"    {[i, plus_one_list, sign]}\t=>\t{p}")
# 
#         with open(self.full_file_name + "_finalCertificate_sage.txt", "w") as out_file:
#             out_file.write(
#                 f"""{
#                     [list(map(tuple, a)) for a in certificate_coords]
#                 }""".replace('[', '{').replace(']', '}')
#             )
# 
#         self.logger.info(f"\nNumber of constraints in certificate: {len(certificate)}")
#         self.logger.info(f"Slack certificate (with indices starting from 1!):")
#         subset_fbases = dict()
#         for _, (i, lst, sign) in certificate_pairs:
#             plus_one_list = list(map(tuple, np.array(lst) + 1))
#             subset_fbases.update({i+1: list(np.array(fbases[i]) + 1) for i in list(zip(*lst))[1]})
#             self.logger.info(f"    {[i, plus_one_list, sign]}")
# 
#         self.logger.info(
#             f"\nFacets in certificate (with indices starting from 1!):\n{sorted(subset_fbases.items())}"
#         )
# 
#         if sum(certificate) == 0:
#             self.logger.info("\nThe certificate sums to 0!")
#         else:
#             self.logger.info("\nThe certificate does NOT sum to 0.")
    
    def read_data_from_file(self):
        """
        Reads from a textfile (must be stored in the database folder in this directory).

        :param sphere_name = string identifying the sphere (it can be one of the following: "Altshuler_M963", "Altshuler_N10_3574", "Doolittle_11v", "Doolittle_13v1", "Doolittle_13v2", "Novik_Zheng_12v", "Firsching_F374225", "Firsching_T2775", "Zheng_16v", "Criado_Santos_P1039", "Criado_Santos_P1963", "Criado_Santos_P2669", "Criado_Santos_P3513", "Criado_Santos_P2105")
        :return F = list of facets as list of vertex labels
        :return d = integer, dimension of sphere
        :return fl = list, containing column indices of a flag
        :return ringS = str, polynomial ring of the full slack matrix
        :return S1 = str, reduced dehomogenized slack matrix corresponding to flag fl
        :return T = list, empty list

        TODO: 
        * This works if each data is separated by a new line, so some prismatoid data files might error out
        * This assumes that the data file does not have a spanning tree
        * This does not work yet for prismatoid data files
        """
        with open(f'database/{self.file_name}_data.txt') as myfile:
            data = myfile.readlines()
        return (
            eval(fix_m2_list(data[1][:-2])), 
            int(data[2][0]),  
            eval(fix_m2_list(data[3][:-2])),
            fix_m2_list(data[4][:-2]),
            fix_m2_list(data[5][:-2]),
            []
        )
    
    def read_data_from_database(self):
        """
        Checks if the file name is in the database, if it is then read from existing database.

        :param sphere_name = string identifying the sphere (it can be one of the following: "Altshuler_M963", "Altshuler_N10_3574", "Doolittle_11v", "Doolittle_13v1", "Doolittle_13v2", "Novik_Zheng_12v", "Firsching_F374225", "Firsching_T2775", "Zheng_16v", "Criado_Santos_P1039", "Criado_Santos_P1963", "Criado_Santos_P2669", "Criado_Santos_P3513", "Criado_Santos_P2105")
        :return F = list of facets as list of vertex labels
        :return d = integer, dimension of sphere
        :return fl = list, containing column indices of a flag
        :return ringS = str, polynomial ring of the full slack matrix
        :return S1 = str, reduced dehomogenized slack matrix corresponding to flag fl
        :return T = list, spanning forest used to dehomogenize S1 (the ones in S1 correspond to the edges of T)
        """
        files_in_database = [
            "Altshuler_M963",
            "Altshuler_N10_3574",
            "Doolittle_11v",
            "Doolittle_13v1", 
            "Doolittle_13v2",
            "Novik_Zheng_12v",
            "Firsching_F374225",
            "Firsching_T2775",
            "Zheng_16v",
            "Criado_Santos_P1039",
            "Criado_Santos_P1963", 
            "Criado_Santos_P2669",
            "Criado_Santos_P3513",
            "Criado_Santos_P2105",
            "test1",
            "test2",
            "test3"
        ]
        if self.file_name in files_in_database:
            return sphere_database(self.file_name)
        else:
            return None
    
    def get_Fbases(self, F, d, S=None, S1=None):
        """Keep original facets; certify a spanning basis for each by zero pattern."""
        bases, witnesses = certgeom.facet_bases(F, int(d))
        self.facet_basis_witnesses = witnesses
        return bases

    def get_pos_sat_hash(self, S1, Fbases):
        """Reconstruct and orient actual signed determinants, then apply degree cap."""
        generators, meta = certgeom.build_generators(
            self.original_facets, list(self.flag), self.reduced_tokens,
            max_degree=int(self.max_deg), log=self.logger.info,
            simplify=str(self.small_determinants).lower() == 'true')
        if Fbases != meta['facet_bases']:
            raise ValueError('Facet-basis mismatch in reconstruction')
        meta['max_factors'] = int(self.n_factors)
        self.geometry_metadata = meta
        self._all_generators = generators
        out = {}
        include = set(_parse_indices(self.include_rows))
        for p, provenance in generators:
            if provenance['kind'] == 'slack':
                i,j = provenance['row'],provenance['column']
                if i not in self.selected_rows or j not in self.selected_cols: continue
                if not include.issubset(set(Fbases[j]) | {i}): continue
                legacy = [[(i,j)],provenance['sign']]
            elif provenance['kind']=='variable':
                q = provenance['index']+1
                legacy = [[(-q,-q)],1]
            else: legacy = [[(-0,-0)],1]
            out[to_ring(self.R,p)] = legacy
        return out

    def get_contraints(self, F, d, S1, S=None):
        if len(self.flag) != int(d)+1:
            raise ValueError('Reduced matrix must contain exactly dimension+1 columns')
        bases = self.get_Fbases(F,d,S,S1)
        return bases, self.get_pos_sat_hash(S1,bases)

    def dump_to_file(self, dump_data_description, dump_file_name, dump_contents):
        self.logger.info(f"Dumping {dump_data_description} to file {dump_file_name}...")

        with open(os.path.join(f'{DIR_PATH}/dump', dump_file_name), 'w') as f:
            f.write(str(dump_contents))

    @property
    def relabel_data(self):
        return (
            f'relabelData("{self.file_name}", {self.n_factors}, {self.max_deg}, '
            f'RedundantNonsimplicialFacets => {self.redundant_facets}'
            ');'
        )

    @property
    def run(self):
        """Original entry point, now using certified reductions and real flag retries.

        The batch runner owns cross-flag retries. Within one flag this method tries
        nested generator term-count caps 4, 8, all, without changing degree/factors.
        """
        import ast,json,math
        F=self.facets
        if isinstance(F,str): F=ast.literal_eval(fix_m2_list(F))
        if not F:
            if not HAVE_SAGE:
                raise ValueError('Provide explicit facets when running without Sage')
            F,d,fl,ringS,S1,T=self.read_data_from_database()
            self.dimension=int(d)
        F=[sorted(int(v) for v in f) for f in F]
        if len(set(map(tuple,F)))!=len(F) or any(len(f)!=len(set(f)) for f in F):
            raise ValueError('Repeated facets or repeated vertices in a facet')
        vertices=sorted(set(chain.from_iterable(F)))
        if vertices!=list(range(len(vertices))):
            raise ValueError('Prepared input must have contiguous zero-based vertices')
        if str(self.load_data).lower()=='true':
            raise ValueError('Use explicit facets for the repaired construction; saved-reduction replay is disabled')
        if str(self.redundant_facets).lower()=='true':
            raise NotImplementedError('Redundant facet-basis expansion is not supported by this certified reduction')
        d=int(self.dimension)
        if any(len(f)<d for f in F): raise ValueError('Facet smaller than the stated dimension')
        self.original_facets=[f[:] for f in F]
        requested=_parse_indices(self.flag)
        rng=random.Random(int(self.random_seed))
        if requested and str(self.force_new_flag).lower()!='true':
            self.flag=list(requested)
            required={j for j,f in enumerate(F) if len(f)>d}
            if not required.issubset(self.flag) or certgeom.flag_witness(F,self.flag,d) is None:
                raise ValueError('Requested flag must contain all nonsimplicial facets and a dimension+1 rank witness')
        else:
            self.flag=certgeom.sample_flag(F,rng,dimension=d)
        self.selected_flag=list(self.flag)
        self.logger.info('Flag actually used: %s',self.flag)
        # A reproducible independent stream for the normalization forest.
        self.reduced_tokens=certgeom.normalized_matrix(F,self.flag,random.Random(int(self.random_seed)))
        certgeom.validate_reduction(F,self.flag,self.reduced_tokens)
        _,names=certgeom.matrix_encoding(self.reduced_tokens)
        if HAVE_SAGE:
            self.R=PolynomialRing(QQ,names=tuple(names))
            S1=matrix(self.R,[[self.R(x) for x in row] for row in self.reduced_tokens])
        else:
            self.R=ExactRing(names)
            S1=self.reduced_tokens
        self.logger.info('Polynomial backend: %s; matrix shape=%s x %s',
                         'Sage QQ' if HAVE_SAGE else 'exact sparse Python',len(F and vertices),len(self.flag))
        self.selected_rows=_parse_indices(self.selected_rows) or list(range(len(vertices)))
        self.selected_cols=_parse_indices(self.selected_cols) or list(range(len(F)))
        bases,constraints=self.get_contraints(F,d,S1)
        self.dump_to_file('reconstruction metadata',self.file_name_old+'_geometry.json',
                          json.dumps(self.geometry_metadata,indent=2))
        self.dump_to_file('original facets',self.file_name_old+'_facets.txt',repr(F))
        self.dump_to_file('validated facet bases',self.file_name_old+'_Fbases.txt',repr(bases))
        self.dump_to_file('reduced matrix',self.file_name_old+'_reducedSlackMatrix.txt',repr(S1))
        caps=[4,8,0]
        if os.getenv('PRISMATOID_GENERATOR_TERM_CAPS'):
            caps=[int(v) for v in os.environ['PRISMATOID_GENERATOR_TERM_CAPS'].split(',')]
            if not caps or caps[-1]!=0 or any(v<0 for v in caps):
                raise ValueError('Generator term caps must be nonnegative and end in 0 (=all)')
        budget=int(os.getenv('PRISMATOID_MAX_PRODUCTS','200000'))
        if budget<1: raise ValueError('Product budget must be positive')
        seen_sizes=set(); self.generator_stages=[]
        for cap in caps:
            stage={p:pr for p,pr in constraints.items() if cap==0 or p.number_of_terms()<=cap}
            if len(stage) in seen_sizes: continue
            seen_sizes.add(len(stage));self._generator_term_limit=cap
            bound=math.comb(len(stage)+int(self.n_factors),int(self.n_factors))-1
            rec={'term_limit':cap,'generators':len(stage),'product_upper_bound':bound}
            self.generator_stages.append(rec)
            if bound>budget:
                rec['status']='product_budget_exceeded';self.logger.info('Skipping oversized stage: %s',rec);continue
            self.logger.info('Generator stage: term cap=%s, %s generators',cap,len(stage))
            products=self.get_products(stage)
            self._batch_constraint_dict=products
            coefficient_matrix=self.get_coefficient_matrix(products)
            for suffix in ('_certificate_rows.txt','_certificate_verified.json'):
                path=self.full_file_name+suffix
                if os.path.isfile(path): os.remove(path)
            if self.gurobi_interface=='skip': return 1
            certificate,active=self.solve_lp(M=coefficient_matrix)
            if len(active):
                # The batch LP hook must call accept_exact_solution before returning.
                if not hasattr(self,'certificate_bundle'):
                    raise ArithmeticError('LP hook did not perform exact certificate verification')
                rec['status']='certificate_exact';return 0
            rec['status']='no_certificate_in_stage'
        return 1


    def accept_exact_solution(self, numeric_values):
        """Reject numerical-only success; save a reconstruction-checkable witness."""
        from fractions import Fraction
        from collections import defaultdict
        import hashlib,json
        active = [i for i,x in enumerate(numeric_values) if float(x)>1e-10]
        witness = None
        for bound in (10**3,10**6,10**9,10**12):
            weights=[Fraction(float(numeric_values[i])).limit_denominator(bound) for i in active]
            total=sum(weights)
            if total<=0 or any(w<=0 for w in weights): continue
            weights=[w/total for w in weights]
            residual=defaultdict(Fraction)
            for i,w in zip(active,weights):
                for m,c in self._stage_products[i][0]: residual[m]+=w*c
            if all(x==0 for x in residual.values()):
                witness=list(zip(active,weights)); break
        if witness is None:
            raise ArithmeticError('LP solution did not pass exact positive rational reconstruction')
        used=sorted({i for row,w in witness for i in self._stage_products[row][1]})
        remap={i:j for j,i in enumerate(used)}
        bundle={
            'format':'prismatoid-core-certificate-v1',
            'candidate_id':str(self.file_name_old),
            'metadata':self.geometry_metadata,
            'generators':[{'polynomial':self._stage_generators[i][0],
                           'provenance':self._stage_generators[i][1]} for i in used],
            'terms':[{'weight':str(w),'factors':[remap[i] for i in self._stage_products[row][1]]}
                     for row,w in witness],
            'search_attempt':{'flag':list(self.flag),'random_seed':int(self.random_seed),
                              'term_limit':self._generator_term_limit,
                              'source':'generated from input facets; no saved recipes'},
        }
        # Independent determinant/permutation checker covers the supplied type.
        if self.dimension == 5 and len(self.original_facets[0])>5 and len(self.original_facets[1])>5 \
           and set(self.original_facets[0]).isdisjoint(self.original_facets[1]):
            from modules.verify_certificate import verify_bundle
            bundle['verification']=verify_bundle(bundle,expected_facets=self.original_facets)
        else:
            bundle['verification']={'status':'exact_identity_verified',
                 'note':'Independent prismatoid verifier is restricted to dimension-five inputs with two bases first.'}
        self.certificate_bundle=bundle
        self.exact_weights={i:str(w) for i,w in witness}
        with open(self.full_file_name+'_certificate_verified.json','w') as f:
            json.dump(bundle,f,indent=2,sort_keys=True)
        with open(self.full_file_name+'_certificate_rows.txt','w') as f:
            f.write(' '.join(str(i) for i,w in witness)+'\n')
        self.logger.info('Accepted exact positive identity with %s terms; verification=%s',
                         len(witness),bundle['verification']['status'])
        return witness


if __name__ == "__main__":

    PARSER = argparse.ArgumentParser()

    PARSER.add_argument('--check_certificate_m2', '-ccm2', type=str, default="false")
    PARSER.add_argument('--deep_sign_check', '-deep', type=str, default="false")
    PARSER.add_argument('--dimension', '-d', type=int, default="4")
    PARSER.add_argument('--facets', '-f', default="{}")
    PARSER.add_argument('--file_name', '-n', type=str, default="Altshuler_N10_3574")
    PARSER.add_argument('--flag', '-fl', default="{}")
    PARSER.add_argument('--force_new_flag', '-nf', type=str, default="false")
    PARSER.add_argument('--gurobi_interface', '-g', type=str, default="sage")
    PARSER.add_argument('--include_rows', '-i', default="{}")
    PARSER.add_argument('--language', '-lang', type=str, default="m2")
    PARSER.add_argument('--load_data', '-data', type=str, default="false")
    PARSER.add_argument('--matrix_method', '-m', type=str, default="sphere_new")
    PARSER.add_argument('--max_deg', '-l', type=int, default=2)
    PARSER.add_argument('--n_factors', '-k', type=int, default=2)
    PARSER.add_argument('--oriented', '-o', type=str, default="false")
    PARSER.add_argument('--prismatoid', '-p', type=str, default="false")
    PARSER.add_argument('--random_seed', '-rs', type=int, default=0)
    PARSER.add_argument('--redundant_facets', '-rf', type=str, default="false")
    PARSER.add_argument('--selected_cols', '-c', default="{}")
    PARSER.add_argument('--selected_rows', '-r', default="{}")
    PARSER.add_argument('--shuffle_constraints', '-sc', type=str, default="false")
    PARSER.add_argument('--sleep', '-slp', type=int, default=3)
    PARSER.add_argument('--small_determinants', '-sd', type=str, default="false")
    PARSER.add_argument('--switch_to_sage', '-ss', type=str, default="true")
    PARSER.add_argument('--suffix', '-s', type=str, default="")

    ARGS = vars(PARSER.parse_args())

    raise SystemExit(NonRealizabilityTest(**ARGS).run)
