from __future__ import annotations

from pathlib import Path
from typing import Iterable
import json

from .models import CapturedModel, ExactWitness, TemplateRecord
from .model_graph import canonical_hash, graphs_isomorphic, make_template, match_template_to_model


class TemplateLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.templates: list[TemplateRecord] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.templates = []
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.templates = [TemplateRecord.from_dict(item) for item in data.get("templates", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": 1,
            "meaning": "algebraic certificate-support templates; an embedding is a search restriction, not by itself a proof",
            "templates": [template.to_dict() for template in self.templates],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def ordered(self) -> list[TemplateRecord]:
        return sorted(self.templates, key=lambda t: (-len(t.covered_candidates), t.active_count, t.creation_order, t.template_id))

    def find_equivalent(self, model: CapturedModel, witness: ExactWitness) -> TemplateRecord | None:
        from .model_graph import build_support_graph
        graph = build_support_graph(model, witness.active_variables)
        h = canonical_hash(graph)
        for template in self.templates:
            if template.canonical_hash == h and graphs_isomorphic(template.graph, graph):
                return template
        return None

    def add_or_cover(self, candidate_id: str, model: CapturedModel, witness: ExactWitness) -> tuple[TemplateRecord, bool]:
        existing = self.find_equivalent(model, witness)
        if existing is not None:
            if candidate_id not in existing.covered_candidates:
                existing.covered_candidates.append(candidate_id)
                existing.covered_candidates.sort()
            self.save()
            return existing, False
        template_id = f"T{len(self.templates) + 1:04d}"
        template = make_template(template_id, candidate_id, model, witness, len(self.templates) + 1)
        self.templates.append(template)
        self.save()
        return template, True

    def candidate_supports(self, model: CapturedModel, max_templates: int | None = None) -> Iterable[tuple[TemplateRecord, list[str]]]:
        templates = self.ordered()
        if max_templates is not None:
            templates = templates[:max_templates]
        for template in templates:
            for support in match_template_to_model(template, model):
                yield template, support

    def write_human_report(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "FINAL CERTIFICATE TEMPLATE LIBRARY",
            "==================================",
            "",
            "A template is the exact active-row support graph of a rationally verified",
            "positive certificate LP witness. Candidates are grouped only after each one",
            "has received its own exactly verified witness. With --template-first, a match",
            "may also be used as a search restriction, but graph containment alone is never",
            "counted as a non-realizability proof.",
            "",
            f"number_of_templates: {len(self.templates)}",
            f"number_of_covered_candidates: {len({c for t in self.templates for c in t.covered_candidates})}",
            "",
        ]
        for template in self.ordered():
            lines += [
                f"[{template.template_id}]",
                f"canonical_hash: {template.canonical_hash}",
                f"representative: {template.representative_candidate}",
                f"search_variant: {template.notes.get('search_variant', 'legacy')}",
                f"monomial_simplification: {template.notes.get('monomial_simplification', False)}",
                f"all_variable_products: {template.notes.get('all_variable_products', False)}",
                f"active_variables: {template.active_count}",
                f"coverage_count: {len(template.covered_candidates)}",
                "covered_candidates: " + " ".join(template.covered_candidates),
                "representative_coefficients:",
            ]
            for name, value in sorted(template.witness_values.items()):
                lines.append(f"  {name} = {value}")
            active_rows = dict(template.notes.get("representative_active_rows", {}))
            if active_rows:
                lines.append("representative_positive_identity:")
                for name in template.representative_variable_names:
                    description = active_rows.get(name, {})
                    value = template.witness_values.get(name, "0")
                    polynomial = description.get("positive_polynomial", "<description unavailable>")
                    provenance = description.get("provenance", "")
                    row_index = description.get("row_index_zero_based", "?")
                    lines.append(f"  {value} * ({polynomial})    # LP row {row_index}")
                    if provenance:
                        lines.append(f"      provenance: {provenance}")
            lines.append("")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        tmp.replace(path)
        individual = path.parent / "individual"
        individual.mkdir(parents=True, exist_ok=True)
        for template in self.templates:
            detail = [
                f"template: {template.template_id}",
                f"canonical_hash: {template.canonical_hash}",
                f"representative: {template.representative_candidate}",
                f"search_variant: {template.notes.get('search_variant', 'legacy')}",
                f"monomial_simplification: {template.notes.get('monomial_simplification', False)}",
                f"all_variable_products: {template.notes.get('all_variable_products', False)}",
                f"active_variables: {template.active_count}",
                f"coverage_count: {len(template.covered_candidates)}",
                "covered_candidates: " + " ".join(template.covered_candidates),
                "",
                "coefficients:",
            ]
            detail += [f"  {name} = {value}" for name, value in sorted(template.witness_values.items())]
            active_rows = dict(template.notes.get("representative_active_rows", {}))
            if active_rows:
                detail += ["", "representative_positive_identity:"]
                for name in template.representative_variable_names:
                    description = active_rows.get(name, {})
                    value = template.witness_values.get(name, "0")
                    polynomial = description.get("positive_polynomial", "<description unavailable>")
                    provenance = description.get("provenance", "")
                    row_index = description.get("row_index_zero_based", "?")
                    detail.append(f"  {value} * ({polynomial})    # LP row {row_index}")
                    if provenance:
                        detail.append(f"      provenance: {provenance}")
            detail += ["", "notes:", json.dumps(template.notes, indent=2, sort_keys=True), "", "support_graph:", json.dumps(template.graph, indent=2, sort_keys=True), ""]
            target = individual / f"{template.template_id}.txt"
            target.write_text("\n".join(detail), encoding="utf-8")
