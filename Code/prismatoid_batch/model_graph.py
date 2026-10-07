from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
import math
from typing import Any

from .models import CapturedModel, ExactWitness, TemplateRecord, fraction_from_text, fraction_to_text


def _f(value: str) -> Fraction:
    try:
        return Fraction(str(value))
    except Exception:
        return Fraction(float(value)).limit_denominator(10**9)


def _normalize_row(coeffs: dict[str, str], rhs: str, sense: str) -> tuple[dict[str, str], str, str]:
    values = [_f(v) for v in coeffs.values()] + [_f(rhs)]
    nonzero = [abs(v) for v in values if v]
    if not nonzero:
        return {k: "0" for k in coeffs}, "0", sense
    # Rational row scaling: multiply by lcm denominators, divide by gcd numerators.
    from math import gcd
    from functools import reduce
    def lcm(a, b): return abs(a*b) // gcd(a, b) if a and b else 0
    den = reduce(lcm, (v.denominator for v in values), 1)
    ints = [int(v * den) for v in values]
    g = reduce(gcd, (abs(i) for i in ints if i), 0) or 1
    ints = [i // g for i in ints]
    # Equality rows can be negated freely. Inequality rows require sense reversal.
    first = next((i for i in ints if i), 1)
    out_sense = sense
    if first < 0:
        ints = [-i for i in ints]
        if sense in {"<", "<=", "L"}: out_sense = ">"
        elif sense in {">", ">=", "G"}: out_sense = "<"
    keys = list(coeffs)
    return ({k: str(ints[i]) for i, k in enumerate(keys)}, str(ints[-1]), out_sense)


def build_support_graph(model: CapturedModel, active_variables: list[str] | None = None) -> dict[str, Any]:
    active = set(active_variables or [v.name for v in model.variables])
    var_lookup = {v.name: v for v in model.variables}
    touched_rows = [c for c in model.constraints if any(name in active and _f(coef) != 0 for name, coef in c.coefficients.items())]
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    var_ids = {name: f"v{i}" for i, name in enumerate(sorted(active))}
    for name in sorted(active):
        v = var_lookup[name]
        lb_sign = "-" if _f(v.lb) < 0 else "+" if _f(v.lb) > 0 else "0"
        try: ub_val = _f(v.ub); ub_kind = "finite" if abs(ub_val) < 10**90 else "inf"
        except Exception: ub_kind = "inf"
        nodes.append({"id": var_ids[name], "kind": "variable", "color": f"variable|{v.vtype}|lb:{lb_sign}|ub:{ub_kind}"})
    for rindex, constraint in enumerate(touched_rows):
        norm_all, rhs, sense = _normalize_row(constraint.coefficients, constraint.rhs, constraint.sense)
        norm = {name: coef for name, coef in norm_all.items() if name in active and _f(coef) != 0}
        rid = f"r{rindex}"
        nodes.append({"id": rid, "kind": "constraint", "color": f"constraint|{sense}|rhs:{rhs}"})
        for name, coef in norm.items():
            if coef != "0":
                edges.append({"u": rid, "v": var_ids[name], "color": coef})
    return {"nodes": nodes, "edges": edges, "variable_names": {var_ids[n]: n for n in var_ids}}


def _to_networkx(graph_data: dict[str, Any]):
    import networkx as nx
    graph = nx.Graph()
    for node in graph_data["nodes"]:
        graph.add_node(node["id"], kind=node["kind"], color=node["color"])
    for edge in graph_data["edges"]:
        graph.add_edge(edge["u"], edge["v"], color=edge["color"])
    return graph


def canonical_hash(graph_data: dict[str, Any]) -> str:
    try:
        import networkx as nx
        graph = _to_networkx(graph_data)
        value = nx.weisfeiler_lehman_graph_hash(graph, node_attr="color", edge_attr="color", iterations=5)
        payload = f"{len(graph.nodes)}|{len(graph.edges)}|{value}"
    except Exception:
        node_colors = sorted(n["color"] for n in graph_data["nodes"])
        edge_colors = sorted(e["color"] for e in graph_data["edges"])
        payload = json.dumps([node_colors, edge_colors], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def graphs_isomorphic(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if len(left["nodes"]) != len(right["nodes"]) or len(left["edges"]) != len(right["edges"]):
        return False
    try:
        import networkx as nx
        gm = nx.algorithms.isomorphism.GraphMatcher(
            _to_networkx(left), _to_networkx(right),
            node_match=lambda a, b: a.get("color") == b.get("color") and a.get("kind") == b.get("kind"),
            edge_match=lambda a, b: a.get("color") == b.get("color"),
        )
        return gm.is_isomorphic()
    except Exception:
        return canonical_hash(left) == canonical_hash(right)


def match_template_to_model(template: TemplateRecord, model: CapturedModel, max_nodes: int = 180, max_matches: int = 1) -> list[list[str]]:
    """Return candidate variable-name supports realizing a template monomorphism.

    The returned support is only a solver restriction/hint. A fresh exact witness is
    required before the candidate is marked covered.
    """
    template_graph = template.graph
    if len(template_graph.get("nodes", [])) > max_nodes:
        return []
    candidate_data = build_support_graph(model, None)
    try:
        import networkx as nx
        candidate = _to_networkx(candidate_data)
        target = _to_networkx(template_graph)
        gm = nx.algorithms.isomorphism.GraphMatcher(
            candidate, target,
            node_match=lambda a, b: a.get("color") == b.get("color") and a.get("kind") == b.get("kind"),
            edge_match=lambda a, b: a.get("color") == b.get("color"),
        )
        output: list[list[str]] = []
        reverse_names = candidate_data["variable_names"]
        for mapping in gm.subgraph_monomorphisms_iter():
            # mapping maps candidate graph nodes to template graph nodes.
            support = sorted(reverse_names[node] for node, target_node in mapping.items() if node in reverse_names and target.nodes[target_node].get("kind") == "variable")
            if len(support) == template.active_count:
                output.append(support)
                if len(output) >= max_matches:
                    break
        return output
    except Exception:
        return []


def make_template(template_id: str, candidate_id: str, model: CapturedModel, witness: ExactWitness, creation_order: int) -> TemplateRecord:
    graph = build_support_graph(model, witness.active_variables)
    active_descriptions = dict(model.metadata.get("active_row_descriptions", {}))
    return TemplateRecord(
        template_id=template_id,
        canonical_hash=canonical_hash(graph),
        representative_candidate=candidate_id,
        graph=graph,
        active_count=len(witness.active_variables),
        witness_values={k: v for k, v in witness.values.items() if v != "0"},
        representative_variable_names=list(witness.active_variables),
        covered_candidates=[candidate_id],
        creation_order=creation_order,
        notes={
            "template_semantics": (
                "exact active-row support of the normalized positive certificate LP; "
                "equivalent supports are grouped only after each candidate receives its own "
                "rationally verified witness"
            ),
            "representative_active_rows": {
                name: active_descriptions.get(name, {}) for name in witness.active_variables
            },
            "search_variant": model.metadata.get("search_variant", "legacy"),
            "monomial_simplification": model.metadata.get("monomial_simplification", False),
            "all_variable_products": model.metadata.get("all_variable_products", False),
            "generator_statistics": model.metadata.get("generator_statistics", {}),
        },
    )
