from __future__ import annotations

"""Deterministic sampling and validation of alternate facet flags.

For a simplicial facet ``F_0`` of a ``d``-polytope, an ordered tuple of
``d+1`` facets is a facet flag whenever the successive intersections have
sizes ``d, d-1, ..., 1, 0``.  Every intersection is then a face of the
simplex ``F_0``, so these cardinalities give exactly the required maximal
chain in the dual face lattice.

When the prepared complex has simplicial facets, this test can supply many
valid flags without asking the legacy Macaulay2 code to validate arbitrary
subsets.  Inputs with too few such flags use the legacy fresh-flag fallback.
"""

from collections.abc import Iterable, Sequence
import ast
import hashlib
import random


def parse_flag_indices(value: object) -> tuple[int, ...] | None:
    """Best-effort conversion of legacy flag metadata to integer indices."""

    if value is None:
        return None
    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "{}":
            return None
        # The legacy wrapper follows Macaulay2 syntax, whose list literals use
        # braces.  Convert to a Python list before literal evaluation so order is
        # retained; evaluating ``{...}`` directly would create an unordered set.
        if text.startswith("{") and text.endswith("}"):
            text = "[" + text[1:-1] + "]"
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(parsed, (list, tuple, set, frozenset)):
        return None
    try:
        result = tuple(int(item) for item in parsed)
    except (TypeError, ValueError):
        return None
    return result or None



def flag_intersection_cardinalities(
    facets: Sequence[Sequence[int]], indices: Sequence[int]
) -> tuple[int, ...]:
    """Return cardinalities of the successive selected-facet intersections."""

    normalized = tuple(int(index) for index in indices)
    if not normalized:
        return ()
    if any(index < 0 or index >= len(facets) for index in normalized):
        raise IndexError("flag index is outside the facet list")
    intersection = set(facets[normalized[0]])
    sizes = [len(intersection)]
    for index in normalized[1:]:
        intersection.intersection_update(facets[index])
        sizes.append(len(intersection))
    return tuple(sizes)

def is_simplicial_facet_flag(
    facets: Sequence[Sequence[int]],
    indices: Sequence[int],
    dimension: int,
) -> bool:
    """Check a sufficient, combinatorial facet-flag criterion.

    Indices are zero based, matching the Python list passed to the legacy
    ``NonRealizabilityTest`` class.  The first selected facet must be a
    simplex with ``dimension`` vertices.  Intersecting it successively with
    the remaining selected facets must then leave ``dimension-1`` vertices,
    ``dimension-2`` vertices, and so on down to the empty face.
    """

    if dimension <= 0 or len(indices) != dimension + 1:
        return False
    try:
        normalized = tuple(int(index) for index in indices)
    except (TypeError, ValueError):
        return False
    if len(set(normalized)) != len(normalized):
        return False
    if any(index < 0 or index >= len(facets) for index in normalized):
        return False

    intersection = set(facets[normalized[0]])
    if len(intersection) != dimension:
        return False
    for position, index in enumerate(normalized[1:], start=1):
        intersection.intersection_update(facets[index])
        if len(intersection) != dimension - position:
            return False
    return True


def _candidate_seed(random_seed: int, candidate_id: str) -> int:
    payload = f"{int(random_seed)}\0{candidate_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _sample_one_flag(
    facets: Sequence[Sequence[int]],
    dimension: int,
    rng: random.Random,
    *,
    node_budget: int,
) -> tuple[int, ...] | None:
    facet_sets = [frozenset(facet) for facet in facets]
    first_choices = [
        index for index, facet in enumerate(facet_sets) if len(facet) == dimension
    ]
    rng.shuffle(first_choices)
    visited = 0

    def extend(
        selected: tuple[int, ...],
        intersection: frozenset[int],
    ) -> tuple[int, ...] | None:
        nonlocal visited
        if len(selected) == dimension + 1:
            return selected
        expected_size = dimension - len(selected)
        candidates = [
            index
            for index, facet in enumerate(facet_sets)
            if index not in selected
            and len(intersection.intersection(facet)) == expected_size
        ]
        rng.shuffle(candidates)
        for index in candidates:
            visited += 1
            if visited > node_budget:
                return None
            next_intersection = frozenset(intersection.intersection(facet_sets[index]))
            result = extend(selected + (index,), next_intersection)
            if result is not None:
                return result
        return None

    for first in first_choices:
        visited += 1
        if visited > node_budget:
            break
        result = extend((first,), facet_sets[first])
        if result is not None and is_simplicial_facet_flag(
            facets, result, dimension
        ):
            return result
    return None


def sample_simplicial_facet_flags(
    facets: Sequence[Sequence[int]],
    dimension: int,
    count: int,
    *,
    random_seed: int,
    candidate_id: str,
    exclude: Iterable[Sequence[int]] = (),
) -> list[tuple[int, ...]]:
    """Sample distinct, checked facet flags reproducibly.

    Distinctness is by the *set* of selected columns, not merely their order,
    because reordering the same reduced-slack columns is not a genuinely new
    flag choice for this search.
    """

    if count <= 0:
        return []
    if dimension <= 0:
        raise ValueError("dimension must be positive")

    seen = {
        frozenset(int(index) for index in item)
        for item in exclude
        if item is not None
    }
    rng = random.Random(_candidate_seed(random_seed, candidate_id))
    results: list[tuple[int, ...]] = []
    attempts = 0
    max_attempts = max(100, 50 * count)
    node_budget = max(10_000, 100 * len(facets))

    while len(results) < count and attempts < max_attempts:
        attempts += 1
        flag = _sample_one_flag(
            facets,
            dimension,
            rng,
            node_budget=node_budget,
        )
        if flag is None:
            break
        key = frozenset(flag)
        if key in seen:
            continue
        seen.add(key)
        results.append(flag)
    return results


def flag_literal(indices: Sequence[int]) -> str:
    """Return the Macaulay2 list literal expected by the legacy constructor."""

    return "{" + ", ".join(str(int(index)) for index in indices) + "}"


def _triangular_rank_witness(pattern):
    """Sufficient rank test: an isolated nonzero pivot for every column."""
    remaining=set(range(len(pattern[0]))) if pattern else set()
    used=set();pivots=[]
    while remaining:
        hit=None
        for i,row in enumerate(pattern):
            if i in used: continue
            support=[j for j in sorted(remaining) if row[j]]
            if len(support)==1:
                hit=(i,support[0]);break
        if hit is None: return None
        i,j=hit;pivots.append((i,j));used.add(i);remaining.remove(j)
    return pivots


def sample_rank_certified_facet_flags(facets, dimension, count, *, random_seed,
                                      candidate_id, exclude=()):
    """Include every nonsimplicial facet among exactly d+1 selected columns.

    Candidate ID is only a reproducible RNG stream label, not a recipe lookup.
    A different ordering of the same columns is not counted as a new flag.
    """
    if count<=0: return []
    required=[j for j,f in enumerate(facets) if len(f)>dimension]
    needed=dimension+1-len(required)
    if needed<0: raise ValueError('Too many nonsimplicial facets for this reduction')
    choices=[j for j in range(len(facets)) if j not in required]
    vertices=sorted(set(v for f in facets for v in f))
    sets=list(map(set,facets))
    rng=random.Random(_candidate_seed(random_seed,candidate_id))
    seen={frozenset(f) for f in exclude};found=[]
    for _ in range(50000*count):
        selected=tuple(required+sorted(rng.sample(choices,needed)))
        key=frozenset(selected)
        if key in seen: continue
        pattern=[[v not in sets[j] for j in selected] for v in vertices]
        if _triangular_rank_witness(pattern) is None: continue
        found.append(selected);seen.add(key)
        if len(found)==count: break
    return found
