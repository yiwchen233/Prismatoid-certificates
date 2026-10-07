from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import ast
import hashlib
import json
import re

from .models import FacetComplex

_INT_RE = re.compile(r"[-+]?\d+")
_ALLOWED_LINE_RE = re.compile(r"^[\s\d+\-,:;{}\[\]()]+$")
_NUMBERED_CANDIDATE_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class BoxPrismatoid:
    """One raw candidate in the Criado--Santos prismatoid box.

    The box files have a header ``dimension number_of_lateral_facets`` followed
    by one lateral facet per line.  Vertex labels belong to the fixed ambient
    ranges 0,...,13 and 14,...,27; the used labels in those two ranges are the
    two base vertex sets.  The two bases themselves are omitted from the file.
    """

    path: Path
    dimension: int
    declared_lateral_facets: int
    lateral_facets: tuple[tuple[int, ...], ...]
    lower_base_labels: tuple[int, ...]
    upper_base_labels: tuple[int, ...]

    @property
    def all_source_vertices(self) -> tuple[int, ...]:
        return self.lower_base_labels + self.upper_base_labels


def parse_facet_line(line: str) -> tuple[int, ...] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if not _ALLOWED_LINE_RE.fullmatch(stripped):
        raise ValueError(f"facet line contains non-numeric text: {stripped!r}")
    values = tuple(int(x) for x in _INT_RE.findall(stripped))
    return values or None


def _useful_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="strict").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_box_prismatoid(path: Path, *, base_split: int = 14) -> BoxPrismatoid:
    lines = _useful_lines(path)
    if len(lines) < 2:
        raise ValueError(f"{path}: expected a header and at least one lateral facet")
    header = tuple(int(x) for x in _INT_RE.findall(lines[0]))
    if len(header) != 2 or not re.fullmatch(r"\s*[-+]?\d+\s+[-+]?\d+\s*", lines[0]):
        raise ValueError(f"{path}: first line is not a 'dimension facet_count' header")
    dimension, declared = header
    lateral: list[tuple[int, ...]] = []
    for line_no, line in enumerate(lines[1:], 2):
        facet = parse_facet_line(line)
        if facet is None:
            continue
        if len(set(facet)) != len(facet):
            raise ValueError(f"{path}:{line_no}: repeated vertex in facet {facet}")
        lateral.append(facet)
    if len(lateral) != declared:
        raise ValueError(
            f"{path}: header declares {declared} lateral facets but {len(lateral)} were read"
        )
    vertices = sorted({v for facet in lateral for v in facet})
    lower = tuple(v for v in vertices if v < base_split)
    upper = tuple(v for v in vertices if v >= base_split)
    if not lower or not upper:
        raise ValueError(
            f"{path}: could not recover two nonempty bases using the fixed split at {base_split}"
        )
    return BoxPrismatoid(
        path=path,
        dimension=dimension,
        declared_lateral_facets=declared,
        lateral_facets=tuple(lateral),
        lower_base_labels=lower,
        upper_base_labels=upper,
    )


def looks_like_box_prismatoid(path: Path) -> bool:
    try:
        read_box_prismatoid(path)
        return True
    except Exception:
        return False


def _parse_python_facet_list(text: str) -> list[tuple[int, ...]] | None:
    stripped = text.strip()
    if not stripped.startswith("["):
        return None
    try:
        value = ast.literal_eval(stripped)
    except Exception:
        return None
    if not isinstance(value, (list, tuple)):
        return None
    facets: list[tuple[int, ...]] = []
    for item in value:
        if not isinstance(item, (list, tuple)):
            return None
        facets.append(tuple(int(v) for v in item))
    return facets


def read_facets(path: Path, *, require_prepared: bool = True) -> FacetComplex:
    """Read a prepared facet file.

    Both of the formats already used by the project are accepted:

    * one facet per line; and
    * one Python list containing all facets.

    Raw box files are also recognized.  In that case the two omitted bases are
    restored and the used source labels are relabelled base-by-base.  This is
    primarily for validation; ``prepare_candidate`` writes an explicit prepared
    copy before the solver is run.
    """
    text = path.read_text(encoding="utf-8", errors="strict")
    python_list = _parse_python_facet_list(text)
    if python_list is not None:
        facets = python_list
    elif looks_like_box_prismatoid(path):
        raw = read_box_prismatoid(path)
        order = raw.all_source_vertices
        relabel = {old: new for new, old in enumerate(order)}
        facets = [
            tuple(range(len(raw.lower_base_labels))),
            tuple(range(len(raw.lower_base_labels), len(order))),
        ]
        facets.extend(tuple(relabel[v] for v in facet) for facet in raw.lateral_facets)
    else:
        facets = []
        for line_no, line in enumerate(text.splitlines(), 1):
            facet = parse_facet_line(line)
            if facet is None:
                continue
            if len(set(facet)) != len(facet):
                raise ValueError(f"{path}:{line_no}: repeated vertex in facet {facet}")
            facets.append(facet)
    if not facets:
        raise ValueError(f"{path}: no facet lines found")
    for index, facet in enumerate(facets, 1):
        if len(set(facet)) != len(facet):
            raise ValueError(f"{path}: facet {index} repeats a vertex: {facet}")
        if require_prepared and tuple(sorted(facet)) != tuple(facet):
            raise ValueError(f"{path}: facet {index} is not increasingly sorted")
    vertices = tuple(sorted({v for facet in facets for v in facet}))
    if require_prepared:
        if not vertices or vertices[0] != 0:
            raise ValueError(f"{path}: prepared input must start at vertex 0")
        expected = tuple(range(vertices[-1] + 1))
        if vertices != expected:
            raise ValueError(f"{path}: vertex labels must be contiguous 0,...,n-1")
    bases = identify_base_facets(facets, vertices)
    return FacetComplex(path=path, facets=tuple(tuple(f) for f in facets), vertices=vertices, base_facets=bases)


def identify_base_facets(facets: Iterable[tuple[int, ...]], vertices: tuple[int, ...]) -> tuple[int, int] | None:
    facet_list = list(facets)
    all_vertices = set(vertices)
    # Prepared box inputs deliberately place the two bases first.  Recognizing
    # that contract avoids an unnecessary quadratic scan through hundreds of
    # lateral facets for every one of the 4,091 candidates.
    if len(facet_list) >= 2:
        left0, right0 = set(facet_list[0]), set(facet_list[1])
        if left0.isdisjoint(right0) and left0 | right0 == all_vertices:
            return (0, 1)
    choices: list[tuple[tuple[int, int, int], tuple[int, int]]] = []
    for i, left in enumerate(facet_list):
        L = set(left)
        for j in range(i + 1, len(facet_list)):
            R = set(facet_list[j])
            if L.isdisjoint(R) and L | R == all_vertices:
                key = (min(len(L), len(R)), len(L) + len(R), -(i + j))
                choices.append((key, (i, j)))
    return max(choices)[1] if choices else None


def permutation_sign(original: Iterable[int], sorted_values: Iterable[int]) -> int:
    original_list = list(original)
    target = list(sorted_values)
    position = {value: index for index, value in enumerate(original_list)}
    permutation = [position[value] for value in target]
    inversions = sum(
        permutation[i] > permutation[j]
        for i in range(len(permutation))
        for j in range(i + 1, len(permutation))
    )
    return -1 if inversions % 2 else 1


def prepare_box_prismatoid(
    source: Path,
    destination: Path,
    *,
    metadata_path: Path | None = None,
    base_split: int = 14,
) -> dict:
    """Restore the two bases and write the solver's zero-based/sorted format.

    The source file is never modified.  Relabelling is performed separately in
    the two fixed source base ranges, which reproduces the existing
    ``Pacos_P####`` prepared data for the five examples shipped with the legacy
    project (0554, 0821, 1293, 1377, and 1649).
    """
    raw = read_box_prismatoid(source, base_split=base_split)
    source_order = raw.all_source_vertices
    relabel = {old: new for new, old in enumerate(source_order)}

    source_facets: list[tuple[int, ...]] = [
        raw.lower_base_labels,
        raw.upper_base_labels,
        *raw.lateral_facets,
    ]
    prepared_facets: list[tuple[int, ...]] = []
    orientation_permutation_signs: list[list[int]] = []
    for index, facet in enumerate(source_facets):
        mapped_in_source_order = [relabel[v] for v in facet]
        ordered = tuple(sorted(mapped_in_source_order))
        prepared_facets.append(ordered)
        orientation_permutation_signs.append(
            [index, permutation_sign(mapped_in_source_order, ordered)]
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    # One facet per line is deliberately retained: it is the original solver's
    # simple facet-list contract, now with bases restored and labels contiguous.
    destination.write_text(
        "".join(" ".join(map(str, facet)) + "\n" for facet in prepared_facets),
        encoding="utf-8",
    )
    metadata = {
        "format_version": 2,
        "source_format": "box-prismatoid-header-plus-lateral-facets",
        "dimension": raw.dimension,
        "base_split": base_split,
        "declared_lateral_facets": raw.declared_lateral_facets,
        "prepared_total_facets": len(prepared_facets),
        "source_lower_base_labels": list(raw.lower_base_labels),
        "source_upper_base_labels": list(raw.upper_base_labels),
        "source_to_prepared_vertex": {str(k): v for k, v in relabel.items()},
        "base_facet_indices": [0, 1],
        "permutation_signs_after_sorting": orientation_permutation_signs,
        "orientation_note": (
            "These signs record only the parity of sorting each supplied facet, as in "
            "preprocess&findorientation.py.  The raw box facets are already sorted, so "
            "the legacy solver is run with oriented=false and determines a coherent "
            "column orientation itself."
        ),
    }
    target_metadata = metadata_path or destination.with_suffix(destination.suffix + ".meta.json")
    target_metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    # Assert the written artifact satisfies the unchanged downstream contract.
    read_facets(destination, require_prepared=True)
    return metadata


def normalize_facet_file(source: Path, destination: Path) -> FacetComplex:
    raw = read_facets(source, require_prepared=False)
    vertices = sorted(raw.vertices)
    relabel = {old: new for new, old in enumerate(vertices)}
    facets = [tuple(sorted(relabel[v] for v in facet)) for facet in raw.facets]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(" ".join(map(str, facet)) + "\n" for facet in facets), encoding="utf-8")
    return read_facets(destination, require_prepared=True)


def looks_like_facet_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    if path.name.lower() in {"index", "index.txt", "readme", "readme.txt", "license", "copying"}:
        return False
    if path.suffix.lower() in {".py", ".pyc", ".sage", ".ipynb", ".md", ".json", ".csv", ".tsv", ".zip"}:
        return False
    if looks_like_box_prismatoid(path):
        return True
    try:
        read_facets(path, require_prepared=False)
        return True
    except Exception:
        return False


def natural_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.as_posix())
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


def enumerate_candidates(root: Path) -> list[Path]:
    """Enumerate the numbered archive candidates, excluding auxiliary duplicates.

    The uploaded archive contains 4091 root-level files named 0001,...,4091 and
    four duplicate ``frightful_four/sol####`` files.  When numbered root files
    exist, they are the data set and are selected exclusively.
    """
    numbered = [
        path for path in root.iterdir()
        if path.is_file() and _NUMBERED_CANDIDATE_RE.fullmatch(path.name) and looks_like_box_prismatoid(path)
    ] if root.is_dir() else []
    if numbered:
        return sorted(numbered, key=natural_key)
    candidates = [path for path in root.rglob("*") if looks_like_facet_file(path)]
    return sorted(candidates, key=natural_key)


def candidate_vertex_count(path: Path) -> int:
    """Return the number of vertices used by one candidate.

    Raw files from the prismatoid box omit the two bases, but every base vertex
    still occurs in a lateral facet.  Hence ``all_source_vertices`` gives the
    correct count without preparing the candidate or constructing a sandbox.
    Prepared/other supported facet files are handled by the ordinary parser.
    """
    try:
        raw = read_box_prismatoid(path)
    except Exception:
        return len(read_facets(path, require_prepared=False).vertices)
    return len(raw.all_source_vertices)


def candidate_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel)
    return safe.rsplit(".", 1)[0] if "." in safe else safe


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
