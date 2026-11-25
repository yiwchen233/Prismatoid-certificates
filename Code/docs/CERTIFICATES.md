# Certificate field guide

This guide describes the file conventions used with Gouveia–Macchia–Wiebe,
*General non-realizability certificates for spheres with linear programming*,
J. Symbolic Computation 114 (2023), 172–192,
[doi:10.1016/j.jsc.2022.04.013](https://doi.org/10.1016/j.jsc.2022.04.013).

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

The variable-order list specifies the ordering used by the implementation.

## Generator sources

In `geometry.txt`, **`[Reduced slack matrix R]`** contains R: the complete
rectangular table with rows `v0, v1, ...` and the six listed facet columns.
**`[Ordered facet bases B_j]`** lists the ordered five-element basis for each
facet: `B0` means $B_0$, `B1` means $B_1$, and so on. For example,
`B3 = 0 1 4 5 8` means $B_3=(0,1,4,5,8)$, an ordered list of vertex indices
for facet F3. The `Fj` entries in `[Facets]` give the complete facet vertex
sets; they are distinct from these ordered bases.

Write $B_j=(b_1,b_2,b_3,b_4,b_5)$. With the six columns of R in their
displayed order, define

$$
D(i,j)=\det R[(b_1,b_2,b_3,b_4,b_5,i),:].
$$

The colon selects all six columns. Take the five basis rows **in the listed
order**, followed by row i. Do not sort the six rows after appending i. This is the transpose of
the column-vector determinant displayed on p. 177 of the paper, with the same
determinant value.

A source line such as

```text
g1 source: D(3,3); sign -1; content 1; monomial x_5_19*x_8_0
```

means exactly

$$
g_1=-D(3,3)/(x_{5,19}x_{8,0}).
$$

Here `sign` is the reconstructed column's orientation sign. `content` is a
positive integer divisor. `monomial` is a product of positive reduced variables
dividing every determinant term. If it is `1`, no monomial is divided out.
The polynomial above the source line is the resulting expanded generator.
A source `variable x_i_j` means that generator is the variable itself; a source
`constant 1` means the constant polynomial 1.

In the extended search, common positive monomials and positive integer content
are removed before imposing the generator degree bound. For an unsimplified
certificate the source divisors are 1; the normalization line records that
choice. Orientation checks still use normalized determinants in either case.

## Orientation checks (orientations.txt)

In `orientations.txt`, put

$$
T(i,j)=s_jD(i,j)/(a_{ij}m_{ij}),
$$

where `a_ij` is the gcd of the absolute nonzero determinant coefficients and
`m_ij` is their common monomial factor. Both are positive. For each listed
facet, the file supplies `s_j` and a **test vertex vi**: row i of R
used to establish the column's sign. It can differ from a generator's row.

- `T(i,j) is a positive monomial` means it has one monomial with positive
  coefficient, establishing the column sign directly.
- `T(i,j) = T(r,k)` establishes the sign by exact equality with an entry in
  column F_k, whose sign appears earlier in the file. Vertex v_r need not be
  F_k's own test vertex.

Under a hypothetical realization, the sign at one nonincident vertex fixes
the entire facet column's sign. Positive divisors preserve that sign.

## Geometry checks (geometry.txt)

In `geometry.txt`, `[Facets]` supplies the vertex–facet incidences that determine
R's zero pattern. The matrix and ordered bases determine D(i,j). The incidence
condition D(i,j)=0 applies whenever i belongs to F_j, including vertices outside
the chosen five-element basis of a nonsimplicial base.

The entries set to 1 specify the scaling normalization. Their positions define
an acyclic bipartite graph, with R's rows and columns as nodes and one edge per
unit entry. This permits positive row/column scalings to set these entries to 1
without additional constraints.

`[Why R has rank 6]` lists six `(v_i, F_j)` pairs identifying selected rows and
columns of R. In listed pair order, each pair identifies a diagonal entry of
a lower-triangular 6-by-6 submatrix: its diagonal entries are nonzero and all
entries above the diagonal are zero. Its nonzero determinant establishes rank 6.

`[Why the chosen facet vertices are affinely independent]` lists five
`(F_k, v_i)` pairs for each B_j. These identify selected facet rows and vertex
columns, both ordered by the pairs. Here 0 denotes an incidence and `*` an
unknown positive slack entry. The selected 5-by-5 submatrix has `*` on the
diagonal and zeros above it. Its nonzero determinant establishes affine
independence under a hypothetical realization.

## Products, weights, and the coefficient matrix

The generators used by the identity are labeled `g1`, `g2`, and so on.
Each `P_k` is explicitly a product of
these generators, with repetitions allowed. Its `c_k` is a positive rational
number. The normalization is sum(c_k)=1; multiplying the entire identity by a
common positive denominator yields an equivalent integral-weight certificate.

`coefficient-check.txt` presents the coefficient matrix as **one block per
monomial**, with product definitions and weights at the top. Each block lists
the nonzero coefficients, their weights, and weighted contributions; omitted
products have coefficient zero. Its `Sum` line must equal zero.

If A[m,k] is the coefficient of monomial m in P_k, each block checks
sum_k A[m,k]*c_k=0. These are the coefficient equations A*c=0 from (3),
restricted to the displayed products. All coefficients needed to verify the
identity are supplied.

## Example: 1039

Open [the certificate](../../Results/n14/certificates/1039.txt) and its
[supporting folder](../../Results/n14/intermediate/1039/).

The selected facets are `0 1 19 65 73 90`, and the certificate is

$$
\tfrac13 g_1g_6+\tfrac13 g_2g_4+\tfrac13 g_3g_5=0.
$$

For the monomial `x_0_90^2*x_6_65`, the cancellation block lists coefficients
-1 in P1 and 1 in P3; P2 is omitted because its coefficient is zero. The
weighted sum is `-1/3 + 1/3 = 0`. Check every block in the same way.
To verify the coefficients, expand the products of generator polynomials from
`generators.txt` and collect like monomials.

For g1, the line `B3 = 0 1 4 5 8` specifies $B_3$. Take rows
`v0, v1, v4, v5, v8, v3` of R, in that order, with all six displayed columns
`F0, F1, F19, F65, F73, F90`, and calculate the resulting 6-by-6 determinant. Negate it
and divide by `x_5_19*x_8_0`; the result must match the printed g1. Check the
sign of column F3 using `orientations.txt`. Repeat for the other five generators.

## Complete hand-check sequence

1. Compare the complete facets and vertex-label mapping with the raw input.
2. Check R's zero pattern, positive variable placement, and forest of ones.
3. Check rank 6 and affine independence using the row/column pairs in `geometry.txt`.
4. Reconstruct D(i,j) with the stated row/column orders; check all true
   incidences, then the sign checks in `orientations.txt`, in their listed order.
5. Compute the positive divisors and verify the printed generator polynomials.
6. Expand the products; check each monomial block, including zeros for omitted products.
7. Check that every c_k is positive, their sum is 1, and every block sums to zero.

The certificate and its four supporting text files contain all data needed
for the exact checks performed by `Code/human_certificate.py`. For larger
candidates, hand expansion can be lengthy, but it involves only the explicitly
supplied matrices and rational arithmetic. The command
`python Code/human_certificate.py Results/n14/certificates/1039.txt` performs
these checks automatically using permutation determinants and exact fractions.
