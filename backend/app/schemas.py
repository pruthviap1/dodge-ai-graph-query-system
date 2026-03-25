from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str = Field(..., description="Unique node identifier across all node types.")
    type: str = Field(..., description="Entity type (e.g. order, delivery, invoice, payment).")
    label: str | None = Field(None, description="Optional human-readable label for UI display.")
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    type: str | None = None
    label: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphQueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question from the user.")
    limit: int = Field(200, ge=1, le=5000)
    max_hops: int = Field(2, ge=0, le=6)


class StructuredGraphQuery(BaseModel):
    # Gemini is asked to return JSON matching this model.
    operation: str = Field(
        default="keyword_graph_lookup",
        description=(
            "High-level operation to execute. Examples: "
            "`trace_order`, `trace_delivery`, `trace_invoice`, `trace_customer`, "
            "`find_incomplete_orders`, `analyze_product_billing_volume`, "
            "`trace_billing_document_flow`, `keyword_graph_lookup`."
        ),
    )

    # Optional IDs for precise graph traversal (recommended).
    customer_id: str | None = None
    order_id: str | None = None
    delivery_id: str | None = None
    invoice_id: str | None = None
    accounting_document: str | None = Field(
        default=None,
        description="Invoice accounting document id used to link invoice -> payment.",
    )
    product_id: str | None = None

    entity_types: list[str] = Field(default_factory=list, description="Optional entity types to focus on.")
    keywords: list[str] = Field(default_factory=list, description="Keywords used to match node labels/fields.")
    limit: int = Field(200, ge=1, le=5000)
    max_hops: int = Field(2, ge=0, le=6)


class GraphQueryResponse(BaseModel):
    answer: str
    structured_query: StructuredGraphQuery
    graph: GraphSnapshot
    debug: dict[str, Any] = Field(default_factory=dict)


class GraphBuildResponse(BaseModel):
    ok: bool
    node_count: int
    edge_count: int
    sources: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"]

