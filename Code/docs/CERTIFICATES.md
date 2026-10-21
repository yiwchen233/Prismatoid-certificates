# Certificate field guide

This guide fixes the file conventions used with Gouveia–Macchia–Wiebe,
*General non-realizability certificates for spheres with linear programming*,
J. Symbolic Computation 114 (2023), 172–192,
[doi:10.1016/j.jsc.2022.04.013](https://doi.org/10.1016/j.jsc.2022.04.013).
It assumes familiarity with equation (3) and the reduced slack construction in
Section 4; it describes the stored data, not the background of the method.

## Labels and order

`F0, F1, ...` are **prepared facet** labels. The two recovered bases occupy F0
and F1; raw lateral facets follow in their original order. For the raw box,
the lower base consists of the used labels below 14 and the upper base of the
used labels at least 14. The used labels in each base are sorted, then relabelled
consecutively starting at zero. The last section of `geometry.txt` supplies the
inverse mapping to the raw vertex labels.

`v0, v1, ...` index vertices in this prepared ordering. All facet/vertex labels
are zero-based, unlike many one-based mathematical examples in the paper.

The `Selected facets` line lists six full facet labels in **column order**.
They determine the reduced matrix R, with one row per vertex. In a variable
`x_i_j`, i is the prepared vertex and j is the full prepared facet label. For
example, if selected facets are `0 1 19 65 73 90`, then `x_0_73` occurs in the
fifth displayed column, not in column 73 of the six-column matrix. Each surviving
symbol is an independent positive variable. Entries fixed to 1 were removed
by row/column scaling; zeros are vertex-facet incidences.

The variable-order list is only an ordering for the implementation. It does
not replace the named variables in any of the printed formulas. 

## Generator sources and provenance

In `geometry.txt`, **`[Reduced slack matrix R]`** contains R: the complete
rectangular table with rows `v0, v1, ...` and the six listed facet columns.
**`[Ordered facet bases B_j]`** lists the ordered five-element basis for each
facet: `B0` means B_0, `B1` means B_1, and so on. For example,
`B3 = 0 1 4 5 8` means B_3=(0,1,4,5,8), an ordered list of vertex indices
for facet F3. The `Fj` entries in `[Facets]` give the complete facet vertex
sets; they are distinct from these ordered bases.

With the six columns of R in their displayed order, define

\[
D(i,j)=\det R[B_j\mathbin{\|}(i),\,:].
\]

The notation means take the five basis rows **in the listed order**, followed
by row i. Do not sort the six rows after appending i. This is the transpose of
the column-vector determinant displayed on p. 177 of the paper, with the same
determinant value.

A source line such as

```text
g1 source: D(3,3); sign -1; content 1; monomial x_5_19*x_8_0
```

means exactly

\[
g_1=-D(3,3)/(x_{5,19}x_{8,0}).
\]

Here `sign` is the reconstructed column's orientation sign. `content` is a
positive integer divisor. `monomial` is a product of positive reduced variables
dividing every determinant term. If it is `1`, no monomial is divided out.
The polynomial above the source line is the resulting expanded generator.
A source `variable x_i_j` means that generator is the variable itself; a source
`constant 1` means the constant polynomial 1.

This source information is what older reports called **provenance**. The old
nested coordinate tuples are not needed: the complete ordered basis, reduced
matrix, sign, and divisor now specify each generator unambiguously.

In the extended search, common positive monomials and positive integer content
are removed before imposing the generator degree bound. For an unsimplified
certificate the source divisors are 1; the normalization line records that
choice. Orientation checks still use normalized determinants in either case.

## Orientation and scaling checks

In `orientations.txt`, put

\[
T(i,j)=s_jD(i,j)/(a_{ij}m_{ij}),
\]

where `a_ij` is the gcd of the absolute nonzero determinant coefficients and
`m_ij` is their common monomial factor. Both are positive. The file supplies
`s_j` and a row i for each justified column.

- `positive monomial` means this T(i,j) has a single monomial with positive
  coefficient, fixing the column sign.
- `equal T(r,k)` means the exact polynomial equality T(i,j)=T(r,k). Check
  this equality, then follow the parent column k to its anchor. File order
  need not follow dependency order. No cycle is permitted.

This gives the sign of an entire facet column under the hypothetical
realization. A generator's positive divisor preserves its sign. All determinant
incidences i in F_j must vanish; their verification includes the extra vertices
of the nonsimplicial bases, not just the selected five basis vertices.

For the scaling normalization, form the bipartite graph with reduced row and
column vertices and edges at unit entries of R. It must be a forest; positive
row/column scalings can set precisely those edges to 1. Compare every zero in R
with the listed facet incidences.

The reduced-rank pivots are pairs `(v_i,F_j)` using full facet labels. At each
step the pivot row has only that nonzero entry among remaining columns. Remove
the row and column and continue; the six pivots certify a nonzero triangular
minor. The facet-basis pivots use the analogous nonincidence matrix with facets
as rows and that facet's five basis vertices as columns. Their printed labels
are again actual facets/vertices, not opaque local indices.

## Products, weights, and the coefficient matrix

Only generators used by the final identity are retained. `g1` etc. are local
labels, not original LP row numbers. Each `P_k` is explicitly a product of
these generators, with repetitions allowed. Its `c_k` is a positive rational
number. The normalization is sum(c_k)=1; multiplying the entire identity by a
common positive denominator yields an equivalent integral-weight certificate.

Old `lambda_000000251` meant the LP variable for the 251st generated product
(index 250 in the implementation). The nine-digit padding had no mathematical
meaning. Such numbering depended on the flag, term cap, product enumeration,
and duplicate removal. The new local c_k labels directly identify their P_k,
so the old row number is unnecessary. These LP weights are not the column
scalings λ_j used in the paper's determinant discussion.

`coefficient-check.txt` is the **certificate-support coefficient matrix**.
Its columns are the displayed products P_k; its rows are ordinary monomials.
If A[m,k] is the printed entry, it is the integer coefficient of monomial m in
the expansion of P_k. The final column prints sum_k A[m,k]*c_k. Thus checking
the table is checking A*c=0, the coefficient equations from (3) restricted to
the nonzero certificate weights. Products with zero LP weight do not contribute
and are not retained. This table is intentionally much smaller than the search
LP. Together with the source polynomials it gives every coefficient needed to
verify the displayed identity; the full search LP is not needed.

## Example: 1039

Open [the certificate](../../Results/n14/certificates/1039.txt) and its
[supporting folder](../../Results/n14/intermediate/1039/).

The selected facets are `0 1 19 65 73 90`, and the certificate is

\[
\tfrac13 g_1g_6+\tfrac13 g_2g_4+\tfrac13 g_3g_5=0.
\]

In its coefficient table, the monomial `x_0_90^2*x_6_65` has coefficients
`-1, 0, 1` in P1, P2, P3. The weighted sum is
`(-1)/3 + 0/3 + 1/3 = 0`. Every remaining row is checked in the same way.
To check the displayed coefficients rather than trust the table, expand each
pair of generator polynomials from `generators.txt` and collect like monomials.

For g1, the line `B3 = 0 1 4 5 8` specifies B_3. Take rows
`v0, v1, v4, v5, v8, v3` of R, in that order, with all six displayed columns
`F0, F1, F19, F65, F73, F90`, and calculate the resulting 6-by-6 determinant. Negate it
and divide by `x_5_19*x_8_0`; the result must match the printed g1. Check the
sign of column F3 using `orientations.txt`. Repeat for the other five generators.

## Complete hand-check sequence

1. Compare the complete facets and vertex-label mapping with the raw input.
2. Check R's zero pattern, positive variable placement, and forest of ones.
3. Check the six reduced-rank pivots and each ordered facet-basis witness.
4. Reconstruct D(i,j) with the stated row/column orders; check all true
   incidences, then the orientation anchors and propagation equalities.
5. Compute the positive divisors and verify the printed generator polynomials.
6. Expand the listed products; compare each coefficient with the support matrix.
7. Check that every c_k is positive, their sum is 1, and every weighted row is zero.

These files preserve all geometric information checked by the independent
verifier. For larger candidates hand expansion can be lengthy, but it involves
only the explicitly supplied matrices and rational arithmetic. The command
`python Code/human_certificate.py Results/n14/certificates/1039.txt` performs
these checks automatically using permutation determinants and exact fractions.
