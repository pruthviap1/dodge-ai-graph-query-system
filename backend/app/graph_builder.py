from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.config import DATA_DIR
from backend.app.schemas import GraphEdge, GraphNode, GraphSnapshot
from backend.app.relational_graph_builder import build_relational_graph


def _safe_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _load_jsonl_files(folder: Path) -> list[tuple[str, dict[str, Any]]]:
    """
    Loads `*.jsonl` files from the dataset directory.
    Returns: [(filename, record_dict), ...]
    """
    if not folder.exists():
        return []

    rows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(folder.rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append((path.name, json.loads(line)))
        except Exception:
            continue
    return rows


def _infer_entity_type_from_filename(filename: str) -> str:
    # Example: sales_order_headers/part-... -> sales_order_headers
    lowered = filename.lower()
    # If filename itself doesn't include type, default to generic.
    return "dataset_row"


def _guess_id_from_record(record: dict[str, Any]) -> str | None:
    """
    Heuristically tries to find a stable id field.
    """
    candidate_keys = [
        "id",
        "ID",
        "uuid",
        "uuid_id",
        "order_id",
        "sales_order_id",
        "sales_order_header_id",
        "outbound_delivery_id",
        "delivery_id",
        "billing_document_id",
        "invoice_id",
        "payment_id",
        "receivable_id",
        "document_id",
        "vbeln",
        "belnr",
    ]
    for k in candidate_keys:
        if k in record:
            s = _safe_str(record.get(k))
            if s:
                return s
    # Some datasets use "*_header_id"/"*_*_id" variations.
    for k, v in record.items():
        if re.search(r"(id|_id)$", k) and isinstance(v, (str, int)):
            s = _safe_str(v)
            if s:
                return s
    return None


def _stringify_for_matching(record: dict[str, Any]) -> str:
    # Used for keyword matching later.
    parts: list[str] = []
    for k, v in record.items():
        if isinstance(v, (str, int, float)):
            parts.append(f"{k}:{v}")
    return " ".join(parts).lower()


@dataclass
class GraphBuildResult:
    snapshot: GraphSnapshot
    sources: list[str]


class GraphBuilder:
    """
    Builds a graph snapshot from unprocessed `data/` JSONL files.

    Note: because the exact dataset schema can vary, this starter implementation
    uses safe heuristics:
    - each dataset row becomes a node
    - edges are created when records share common id-like fields
    """

    def __init__(self) -> None:
        self.data_dir = DATA_DIR

    def build(self) -> GraphBuildResult:
        snapshot, sources = build_relational_graph(self.data_dir)
        return GraphBuildResult(snapshot=snapshot, sources=sources)

