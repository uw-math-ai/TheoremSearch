#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

EXAMPLE_NODE_RE = re.compile(r"^Example\b")


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    label: str


@dataclass
class GraphData:
    path: Path
    nodes: set[str]
    edges: set[tuple[str, str]]
    labels: dict[str, str]
    skipped_entries: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two directed dependency graphs stored in JSON and compute "
            "several distance metrics."
        )
    )
    parser.add_argument("graph_a", type=Path, help="Path to the first graph JSON file.")
    parser.add_argument("graph_b", type=Path, help="Path to the second graph JSON file.")
    parser.add_argument(
        "--exclude-interpaper",
        action="store_true",
        help="Ignore dependency entries marked with interpaper=true.",
    )
    parser.add_argument(
        "--node-identity",
        choices=("auto", "name", "id"),
        default="auto",
        help=(
            "How to align nodes across graphs. 'auto' and 'name' use "
            "src_name/dep_name for dependency-style JSON; 'id' prefers stable IDs."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the comparison result.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file to write the result to. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        graph_a = load_graph(
            args.graph_a.resolve(),
            include_interpaper=not args.exclude_interpaper,
            node_identity_mode=args.node_identity,
        )
        graph_b = load_graph(
            args.graph_b.resolve(),
            include_interpaper=not args.exclude_interpaper,
            node_identity_mode=args.node_identity,
        )
        result = compare_graphs(graph_a, graph_b, node_identity_mode=args.node_identity)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_text = format_result(result, output_format=args.format)
    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text)
    return 0


def load_graph(path: Path, include_interpaper: bool, node_identity_mode: str) -> GraphData:
    if not path.exists():
        raise FileNotFoundError(f"Graph file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = extract_entries(payload)

    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    labels: dict[str, str] = {}
    skipped_entries = 0
    unnamed_dependency_counts: dict[str, int] = defaultdict(int)

    for entry in entries:
        if not isinstance(entry, Mapping):
            skipped_entries += 1
            continue
        if not include_interpaper and entry.get("interpaper"):
            continue

        source = extract_source_node(entry, node_identity_mode=node_identity_mode)
        if is_example_node(source):
            continue
        target = extract_target_node(entry, node_identity_mode=node_identity_mode)
        if is_example_node(target):
            continue
        if target is None:
            target = synthesize_missing_dependency_target(
                entry,
                source=source,
                node_identity_mode=node_identity_mode,
                unnamed_dependency_counts=unnamed_dependency_counts,
            )
        if is_example_node(target):
            continue
        if source is None or target is None:
            skipped_entries += 1
            continue

        nodes.add(source.node_id)
        nodes.add(target.node_id)
        labels.setdefault(source.node_id, source.label)
        labels.setdefault(target.node_id, target.label)
        edges.add((source.node_id, target.node_id))

    return GraphData(
        path=path,
        nodes=nodes,
        edges=edges,
        labels=labels,
        skipped_entries=skipped_entries,
    )


def is_example_node(node: NodeRef | None) -> bool:
    if node is None:
        return False
    return bool(EXAMPLE_NODE_RE.match(node.label))


def synthesize_missing_dependency_target(
    entry: Mapping[str, Any],
    source: NodeRef | None,
    node_identity_mode: str,
    unnamed_dependency_counts: dict[str, int],
) -> NodeRef | None:
    if source is None or node_identity_mode not in {"auto", "name"}:
        return None
    if entry.get("interpaper"):
        return None
    if not any(key.startswith("dep_") for key in entry):
        return None
    if first_present(entry.get("dep_name")) is not None:
        return None

    source_name = first_present(entry.get("src_name"), source.label)
    if source_name is None:
        return None

    unnamed_dependency_counts[source_name] += 1
    occurrence = unnamed_dependency_counts[source_name]
    token = f"[unnamed dependency {occurrence} from {source_name}]"
    return NodeRef(
        node_id=f"generated::{token}",
        label=token,
    )


def extract_entries(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        if isinstance(payload.get("dependencies"), list):
            return list(payload["dependencies"])
        if isinstance(payload.get("edges"), list):
            return list(payload["edges"])
    raise ValueError(
        "Unsupported graph JSON format. Expected a top-level list or a dict with "
        "'dependencies' or 'edges'."
    )


def extract_source_node(entry: Mapping[str, Any], node_identity_mode: str) -> NodeRef | None:
    if any(key.startswith("src_") for key in entry):
        prefer_names = node_identity_mode in {"auto", "name"}
        if prefer_names:
            token = first_present(entry.get("src_name"))
            label = first_present(entry.get("src_name"))
        else:
            token = first_present(
                entry.get("src_statement_id"),
                entry.get("src_key"),
                entry.get("src_name"),
            )
            label = first_present(
                entry.get("src_name"),
                entry.get("src_statement_id"),
                entry.get("src_key"),
            )
        if token is None or label is None:
            return None
        return NodeRef(node_id=f"local::{token}", label=label)

    generic_source = entry.get("source", entry.get("src"))
    if generic_source is None:
        return None
    return generic_node_ref(generic_source, default_namespace="node")


def extract_target_node(entry: Mapping[str, Any], node_identity_mode: str) -> NodeRef | None:
    if "interpaper" in entry or any(key.startswith("dep_") for key in entry):
        prefer_names = node_identity_mode in {"auto", "name"}
        if entry.get("interpaper"):
            if prefer_names:
                statement_token = first_present(
                    entry.get("dep_name"),
                    entry.get("cited_paper_key"),
                    entry.get("dep_paper_title"),
                    entry.get("dep_paper_ext_id"),
                )
                label = first_present(
                    entry.get("dep_name"),
                    entry.get("cited_paper_key"),
                    entry.get("dep_paper_title"),
                    entry.get("dep_paper_ext_id"),
                )
                if statement_token is None or label is None:
                    return None
                return NodeRef(
                    node_id=f"external::{statement_token}",
                    label=label,
                )

            paper_token = first_present(
                entry.get("cited_arxiv_id"),
                entry.get("cited_paper_key"),
                "unknown-paper",
            )
            statement_token = first_present(
                entry.get("dep_statement_id"),
                entry.get("dep_key"),
                entry.get("dep_name"),
                "unknown-statement",
            )
            label = first_present(
                entry.get("dep_name"),
                entry.get("dep_key"),
                statement_token,
            )
            return NodeRef(
                node_id=f"external::{paper_token}::{statement_token}",
                label=label,
            )

        if prefer_names:
            token = first_present(entry.get("dep_name"))
            label = first_present(entry.get("dep_name"))
        else:
            token = first_present(
                entry.get("dep_statement_id"),
                entry.get("dep_key"),
                entry.get("dep_name"),
            )
            label = first_present(
                entry.get("dep_name"),
                entry.get("dep_key"),
                entry.get("dep_statement_id"),
            )
        if token is None or label is None:
            return None
        return NodeRef(node_id=f"local::{token}", label=label)

    generic_target = entry.get("target", entry.get("dst", entry.get("dep")))
    if generic_target is None:
        return None
    return generic_node_ref(generic_target, default_namespace="node")


def generic_node_ref(value: Any, default_namespace: str) -> NodeRef | None:
    if isinstance(value, Mapping):
        namespace = first_present(
            value.get("namespace"),
            value.get("kind"),
            default_namespace,
        )
        token = first_present(
            value.get("id"),
            value.get("statement_id"),
            value.get("key"),
            value.get("name"),
            value.get("label"),
        )
        label = first_present(
            value.get("name"),
            value.get("label"),
            token,
        )
        if token is None or label is None:
            token = normalize_text(json.dumps(value, sort_keys=True, ensure_ascii=False))
            label = token
        return NodeRef(node_id=f"{namespace}::{token}", label=label)

    token = normalize_text(value)
    if token is None:
        return None
    return NodeRef(node_id=f"{default_namespace}::{token}", label=token)


def compare_graphs(
    graph_a: GraphData,
    graph_b: GraphData,
    node_identity_mode: str,
) -> dict[str, Any]:
    all_nodes = sorted(graph_a.nodes | graph_b.nodes)
    node_count = len(all_nodes)

    edge_symmetric_difference = graph_a.edges ^ graph_b.edges
    node_symmetric_difference = graph_a.nodes ^ graph_b.nodes

    edge_hamming_distance = len(edge_symmetric_difference)
    normalized_edge_hamming_distance = (
        edge_hamming_distance / (node_count * node_count) if node_count else 0.0
    )
    frobenius_norm = math.sqrt(edge_hamming_distance)
    l1_matrix_difference = edge_hamming_distance

    adjacency_a = adjacency_matrix(all_nodes, graph_a.edges)
    adjacency_b = adjacency_matrix(all_nodes, graph_b.edges)
    singular_values_a = singular_values(adjacency_a)
    singular_values_b = singular_values(adjacency_b)
    spectral_distance = euclidean_distance(singular_values_a, singular_values_b)

    graph_edit_distance = len(node_symmetric_difference) + edge_hamming_distance

    return {
        "graph_a": summarize_graph(graph_a),
        "graph_b": summarize_graph(graph_b),
        "alignment": {
            "node_identity_mode": node_identity_mode,
            "union_node_count": node_count,
            "shared_node_count": len(graph_a.nodes & graph_b.nodes),
            "node_symmetric_difference_count": len(node_symmetric_difference),
            "edge_symmetric_difference_count": edge_hamming_distance,
        },
        "metrics": {
            "edge_hamming_distance": edge_hamming_distance,
            "normalized_edge_hamming_distance": normalized_edge_hamming_distance,
            "frobenius_norm_adjacency_difference": frobenius_norm,
            "l1_matrix_difference": l1_matrix_difference,
            "graph_edit_distance": graph_edit_distance,
            "spectral_distance": spectral_distance,
        },
        "definitions": {
            "edge_hamming_distance": (
                "Number of differing entries in the binary adjacency matrices over "
                "the union of node IDs."
            ),
            "normalized_edge_hamming_distance": (
                "Edge/Hamming distance divided by n^2, where n is the union-node count."
            ),
            "graph_edit_distance": (
                "Label-preserving edit distance with unit costs for node and edge "
                "insertions/deletions under the current node-ID alignment."
            ),
            "spectral_distance": (
                "Euclidean distance between the singular value spectra of the two "
                "adjacency matrices."
            ),
            "node_identity_mode": (
                "Node alignment rule used while building the vertex and edge sets."
            ),
        },
    }


def summarize_graph(graph: GraphData) -> dict[str, Any]:
    return {
        "path": str(graph.path),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "skipped_entries": graph.skipped_entries,
    }


def adjacency_matrix(nodes: list[str], edges: Iterable[tuple[str, str]]) -> list[list[float]]:
    node_to_index = {node_id: index for index, node_id in enumerate(nodes)}
    size = len(nodes)
    matrix = [[0.0] * size for _ in range(size)]
    for source, target in edges:
        source_index = node_to_index[source]
        target_index = node_to_index[target]
        matrix[source_index][target_index] = 1.0
    return matrix


def singular_values(matrix: list[list[float]]) -> list[float]:
    if not matrix:
        return []
    transposed = transpose(matrix)
    gram_matrix = multiply_matrices(transposed, matrix)
    eigenvalues = jacobi_eigenvalues_symmetric(gram_matrix)
    values = [math.sqrt(max(eigenvalue, 0.0)) for eigenvalue in eigenvalues]
    return sorted(values, reverse=True)


def transpose(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    row_count = len(matrix)
    col_count = len(matrix[0])
    return [[matrix[row][col] for row in range(row_count)] for col in range(col_count)]


def multiply_matrices(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    if not left or not right:
        return []
    shared_dim = len(right)
    if len(left[0]) != shared_dim:
        raise ValueError("Matrix shapes are incompatible for multiplication.")

    result_rows = len(left)
    result_cols = len(right[0])
    result = [[0.0] * result_cols for _ in range(result_rows)]

    for row in range(result_rows):
        for pivot in range(shared_dim):
            left_value = left[row][pivot]
            if left_value == 0.0:
                continue
            for col in range(result_cols):
                result[row][col] += left_value * right[pivot][col]
    return result


def jacobi_eigenvalues_symmetric(
    matrix: list[list[float]],
    tolerance: float = 1e-12,
    max_sweeps: int = 50,
) -> list[float]:
    size = len(matrix)
    if size == 0:
        return []
    if size == 1:
        return [matrix[0][0]]

    working = [row[:] for row in matrix]

    for _ in range(max_sweeps):
        changed = False
        for left in range(size - 1):
            for right in range(left + 1, size):
                off_diagonal = working[left][right]
                if abs(off_diagonal) <= tolerance:
                    continue

                changed = True
                left_diag = working[left][left]
                right_diag = working[right][right]

                tau = (right_diag - left_diag) / (2.0 * off_diagonal)
                tangent_sign = 1.0 if tau >= 0.0 else -1.0
                tangent = tangent_sign / (abs(tau) + math.sqrt(1.0 + tau * tau))
                cosine = 1.0 / math.sqrt(1.0 + tangent * tangent)
                sine = tangent * cosine

                for index in range(size):
                    if index == left or index == right:
                        continue
                    left_value = working[index][left]
                    right_value = working[index][right]
                    rotated_left = cosine * left_value - sine * right_value
                    rotated_right = sine * left_value + cosine * right_value
                    working[index][left] = rotated_left
                    working[left][index] = rotated_left
                    working[index][right] = rotated_right
                    working[right][index] = rotated_right

                new_left_diag = (
                    cosine * cosine * left_diag
                    - 2.0 * sine * cosine * off_diagonal
                    + sine * sine * right_diag
                )
                new_right_diag = (
                    sine * sine * left_diag
                    + 2.0 * sine * cosine * off_diagonal
                    + cosine * cosine * right_diag
                )
                working[left][left] = new_left_diag
                working[right][right] = new_right_diag
                working[left][right] = 0.0
                working[right][left] = 0.0

        if not changed or off_diagonal_energy(working) <= tolerance * tolerance:
            break

    return [working[index][index] for index in range(size)]


def off_diagonal_energy(matrix: list[list[float]]) -> float:
    energy = 0.0
    size = len(matrix)
    for row in range(size - 1):
        for col in range(row + 1, size):
            value = matrix[row][col]
            energy += value * value
    return energy


def euclidean_distance(values_a: list[float], values_b: list[float]) -> float:
    max_length = max(len(values_a), len(values_b))
    total = 0.0
    for index in range(max_length):
        left = values_a[index] if index < len(values_a) else 0.0
        right = values_b[index] if index < len(values_b) else 0.0
        difference = left - right
        total += difference * difference
    return math.sqrt(total)


def first_present(*values: Any) -> str | None:
    for value in values:
        normalized = normalize_text(value)
        if normalized is not None:
            return normalized
    return None


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = " ".join(value.split())
    else:
        normalized = str(value).strip()
    return normalized or None


def format_result(result: Mapping[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)

    graph_a = result["graph_a"]
    graph_b = result["graph_b"]
    alignment = result["alignment"]
    metrics = result["metrics"]

    lines = [
        f"Graph A: {graph_a['path']}",
        f"  nodes={graph_a['node_count']} edges={graph_a['edge_count']} skipped_entries={graph_a['skipped_entries']}",
        f"Graph B: {graph_b['path']}",
        f"  nodes={graph_b['node_count']} edges={graph_b['edge_count']} skipped_entries={graph_b['skipped_entries']}",
        "Alignment:",
        f"  node_identity_mode={alignment['node_identity_mode']}",
        f"  union_nodes={alignment['union_node_count']}",
        f"  shared_nodes={alignment['shared_node_count']}",
        f"  node_symmetric_difference={alignment['node_symmetric_difference_count']}",
        f"  edge_symmetric_difference={alignment['edge_symmetric_difference_count']}",
        "Metrics:",
        f"  edge_hamming_distance={metrics['edge_hamming_distance']}",
        f"  normalized_edge_hamming_distance={metrics['normalized_edge_hamming_distance']:.12f}",
        f"  frobenius_norm_adjacency_difference={metrics['frobenius_norm_adjacency_difference']:.12f}",
        f"  l1_matrix_difference={metrics['l1_matrix_difference']}",
        f"  graph_edit_distance={metrics['graph_edit_distance']}",
        f"  spectral_distance={metrics['spectral_distance']:.12f}",
        "Notes:",
        "  graph_edit_distance uses fixed node IDs with unit node/edge insertion/deletion costs.",
        "  spectral_distance compares adjacency singular values, which works naturally for directed graphs.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
