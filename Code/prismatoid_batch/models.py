from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class FacetComplex:
    path: Path
    facets: tuple[tuple[int, ...], ...]
    vertices: tuple[int, ...]
    base_facets: tuple[int, int] | None = None
    @property
    def n_vertices(self): return len(self.vertices)
    @property
    def n_facets(self): return len(self.facets)
