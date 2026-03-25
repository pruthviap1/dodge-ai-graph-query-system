from __future__ import annotations

import re
from typing import Any

from backend.app.gemini import GeminiClient
from backend.app.graph_builder import GraphBuilder
from backend.app.schemas import (
    GraphEdge,
    GraphNode,
    GraphQueryRequest,
    GraphQueryResponse,
    GraphSnapshot,
    StructuredGraphQuery,
)


def _keywords_from_question(question: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9_-]{3,}", question.lower()) if w]


def _node_text(node: GraphNode) -> str:
    label = node.label or ""
    search_text = (node.data or {}).get("search_text", "")
    return f"{label} {search_text}".lower()


def _looks_like_domain_question(question: str, sq: StructuredGraphQuery) -> bool:
    q = question.lower()
    domain_tokens = [
        "order",
        "delivery",
        "invoice",
        "payment",
        "customer",
        "product",
        "sales order",
        "outbound delivery",
        "billing document",
        "accounts receivable",
    ]
    has_domain_word = any(t in q for t in domain_tokens)
    has_any_id = bool(
        sq.customer_id
        or sq.order_id
        or sq.delivery_id
        or sq.invoice_id
        or sq.accounting_document
        or sq.product_id
    )
    return has_any_id or has_domain_word


def _match_nodes(graph_nodes: list[GraphNode], keywords: list[str], entity_types: list[str]) -> list[GraphNode]:
    if not graph_nodes:
        return []

    lowered_entity_types = {t.lower() for t in entity_types if t}
    use_entity_filter = bool(lowered_entity_types)

    selected: list[GraphNode] = []
    for node in graph_nodes:
        if use_entity_filter and node.type.lower() not in lowered_entity_types:
            continue
        text = _node_text(node)
        if any(k in text for k in keywords):
            selected.append(node)
    return selected


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    try:
        return float(v)
    except Exception:
        return None


def _sum_numbers(values: list[Any]) -> float:
    total = 0.0
    for v in values:
        f = _to_float(v)
        if f is not None:
            total += f
    return total


def _fmt_float(v: float) -> str:
    # Round for clean UI output; trim trailing ".00".
    s = f"{v:.2f}"
    if s.endswith(".00"):
        return s[:-3]
    return s


def _graph_from_selected(graph_edges: list[GraphEdge], selected_ids: set[str], limit_edges: int = 2000) -> tuple[list[GraphNode], list[GraphEdge]]:
    selected_edges: list[GraphEdge] = []
    for e in graph_edges:
        if e.from_id in selected_ids or e.to_id in selected_ids:
            # include edges touching selected subgraph
            selected_edges.append(e)
        if len(selected_edges) >= limit_edges:
            break

    # Nodes are inferred from selected ids appearing in edges.
    nodes_ids_in_edges = set()
    for e in selected_edges:
        nodes_ids_in_edges.add(e.from_id)
        nodes_ids_in_edges.add(e.to_id)

    # Caller will provide nodes; we only return edge-filtered nodes later.
    return [], selected_edges


class QueryService:
    def __init__(self) -> None:
        self.gemini = GeminiClient()
        self.graph_builder = GraphBuilder()

        self._graph_snapshot = None
        self._node_by_id: dict[str, GraphNode] = {}
        self._out_edges: dict[str, list[GraphEdge]] = {}
        self._in_edges: dict[str, list[GraphEdge]] = {}

    @property
    def graph_snapshot(self):
        return self._graph_snapshot

    def build_graph(self):
        built = self.graph_builder.build()
        self._graph_snapshot = built.snapshot
        self._index_graph(built.snapshot)
        return built

    def _index_graph(self, graph) -> None:
        self._node_by_id = {n.id: n for n in graph.nodes}
        out_edges: dict[str, list[GraphEdge]] = {}
        in_edges: dict[str, list[GraphEdge]] = {}
        for e in graph.edges:
            out_edges.setdefault(e.from_id, []).append(e)
            in_edges.setdefault(e.to_id, []).append(e)
        self._out_edges = out_edges
        self._in_edges = in_edges

    def _collect_subgraph(
        self,
        start_ids: set[str],
        *,
        max_edge_steps: int,
        node_cap: int | None = None,
        edge_cap: int | None = 5000,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        visited = set(start_ids)
        frontier = set(start_ids)
        edges: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str | None]] = set()

        for _ in range(max_edge_steps):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for node_id in frontier:
                for e in self._out_edges.get(node_id, []):
                    ek = (e.from_id, e.to_id, e.type)
                    if ek not in seen_edges:
                        edges.append(e)
                        seen_edges.add(ek)
                        if edge_cap is not None and len(edges) >= edge_cap:
                            # Stop collecting more edges; traversal might still end due to node_cap.
                            edge_cap = len(edges)
                    if e.to_id not in visited:
                        if node_cap is None or len(visited) < node_cap:
                            visited.add(e.to_id)
                            next_frontier.add(e.to_id)
            frontier = next_frontier

        nodes = [self._node_by_id[nid] for nid in visited if nid in self._node_by_id]
        return nodes, edges

    def _trace_order(
        self,
        order_id: str,
        *,
        max_hops: int,
        node_cap: int,
        edge_cap: int = 5000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        order_node_id = f"order:{order_id}"
        if order_node_id not in self._node_by_id:
            return [], [], {"reason": "order_not_found", "order_id": order_id}
        # Deterministic, strict chain selection:
        # Always prioritize Order -> Delivery -> Invoice -> Payment
        # and only then add a limited set of product edges.
        #
        # max_hops mapping:
        # - max_hops >= 0: include order_to_delivery
        # - max_hops >= 1: include delivery_to_invoice
        # - max_hops >= 2: include invoice_to_payment

        edges: list[GraphEdge] = []
        node_ids: set[str] = {order_node_id}

        # 1) Customer -> Order (incoming)
        customer_edges = [e for e in self._in_edges.get(order_node_id, []) if e.type == "customer_to_order"]
        edges.extend(customer_edges[:5])
        node_ids.update({e.from_id for e in customer_edges[:5]})

        # 2) Order -> Delivery
        order_delivery_edges = [e for e in self._out_edges.get(order_node_id, []) if e.type == "order_to_delivery"]
        delivery_ids = sorted({e.to_id for e in order_delivery_edges})
        delivery_cap = min(len(delivery_ids), max(1, min(50, node_cap // 3)))
        delivery_ids = delivery_ids[:delivery_cap]
        edges.extend([e for e in order_delivery_edges if e.to_id in set(delivery_ids)])
        node_ids.update(delivery_ids)

        # 3) Delivery -> Invoice
        invoice_ids: list[str] = []
        delivery_to_invoice_edges: list[GraphEdge] = []
        if max_hops >= 1 and delivery_ids:
            delivery_set = set(delivery_ids)
            # Gather invoice edges by scanning all delivery nodes (still cheap at this scale).
            delivery_to_invoice_edges = []
            for did in delivery_ids:
                delivery_to_invoice_edges.extend([e for e in self._out_edges.get(did, []) if e.type == "delivery_to_invoice"])
            invoice_ids = sorted({e.to_id for e in delivery_to_invoice_edges})
            invoice_cap = min(len(invoice_ids), max(1, min(50, node_cap // 3)))
            invoice_ids = invoice_ids[:invoice_cap]
            edges.extend([e for e in delivery_to_invoice_edges if e.to_id in set(invoice_ids)])
            node_ids.update(invoice_ids)

        # 4) Invoice -> Payment
        payment_ids: list[str] = []
        invoice_to_payment_edges: list[GraphEdge] = []
        if max_hops >= 2 and invoice_ids:
            invoice_set = set(invoice_ids)
            invoice_to_payment_edges = []
            for iid in invoice_ids:
                invoice_to_payment_edges.extend([e for e in self._out_edges.get(iid, []) if e.type == "invoice_to_payment"])
            payment_ids = sorted({e.to_id for e in invoice_to_payment_edges})
            payment_cap = min(len(payment_ids), max(1, min(50, node_cap // 3)))
            payment_ids = payment_ids[:payment_cap]
            edges.extend([e for e in invoice_to_payment_edges if e.to_id in set(payment_ids)])
            node_ids.update(payment_ids)

        # 5) Order -> Product (optional, limited)
        product_edges_all = [e for e in self._out_edges.get(order_node_id, []) if e.type == "order_to_product"]
        remaining = max(0, node_cap - len(node_ids))
        product_node_ids: list[str] = []
        if remaining > 0 and product_edges_all:
            product_node_ids = []
            seen_product_nodes: set[str] = set()
            for e in product_edges_all:
                if e.to_id in seen_product_nodes:
                    edges.append(e)
                    continue
                if len(seen_product_nodes) >= remaining:
                    break
                seen_product_nodes.add(e.to_id)
                product_node_ids.append(e.to_id)
                edges.append(e)
                node_ids.add(e.to_id)

        # Enforce edge cap by truncating edges after deterministic ordering.
        if edge_cap is not None and len(edges) > edge_cap:
            edges = edges[:edge_cap]

        nodes = [self._node_by_id[nid] for nid in node_ids if nid in self._node_by_id]

        # Data-backed summary
        invoice_nodes = [self._node_by_id[iid] for iid in set(invoice_ids) if iid in self._node_by_id]
        payment_nodes = [self._node_by_id[pid] for pid in set(payment_ids) if pid in self._node_by_id]
        invoice_amount_total = _sum_numbers([n.data.get("total_net_amount") for n in invoice_nodes if n.data])
        payment_amount_total = _sum_numbers([n.data.get("amount") for n in payment_nodes if n.data])
        payment_currency = None
        for pn in payment_nodes:
            cur = (pn.data or {}).get("currency")
            if cur:
                payment_currency = cur
                break

        debug = {
            "order_node_id": order_node_id,
            "delivery_count": len(set(delivery_ids)),
            "invoice_count": len(set(invoice_ids)),
            "payment_count": len(set(payment_ids)),
            "product_count": len(set(product_node_ids)),
            "invoice_amount_total": invoice_amount_total,
            "payment_amount_total": payment_amount_total,
            "payment_currency": payment_currency,
        }

        return nodes, edges, debug

    def _trace_delivery(
        self,
        delivery_id: str,
        *,
        max_hops: int,
        node_cap: int,
        edge_cap: int = 5000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        delivery_node_id = f"delivery:{delivery_id}"
        if delivery_node_id not in self._node_by_id:
            return [], [], {"reason": "delivery_not_found", "delivery_id": delivery_id}
        # Strict chain priority:
        # Orders -> Delivery -> Invoice -> Payment
        # max_hops mapping:
        # - max_hops >= 0: include delivery_to_invoice
        # - max_hops >= 1: include invoice_to_payment

        edges: list[GraphEdge] = []
        node_ids: set[str] = {delivery_node_id}

        # Incoming orders (order_to_delivery edges)
        incoming_order_edges = [e for e in self._in_edges.get(delivery_node_id, []) if e.type == "order_to_delivery"]
        order_ids = sorted({e.from_id for e in incoming_order_edges})
        order_cap = min(len(order_ids), max(1, min(50, node_cap // 3)))
        order_ids = order_ids[:order_cap]
        order_edge_set = set(order_ids)
        edges.extend([e for e in incoming_order_edges if e.from_id in order_edge_set][:edge_cap])
        node_ids.update(order_ids)

        # Customer context (customer_to_order for included orders)
        customer_edges: list[GraphEdge] = []
        for oid in order_ids:
            customer_edges.extend([e for e in self._in_edges.get(oid, []) if e.type == "customer_to_order"])
        customer_edges = customer_edges[: min(len(customer_edges), 50)]
        edges.extend(customer_edges)
        node_ids.update({e.from_id for e in customer_edges})

        # Forward invoices (delivery_to_invoice)
        invoice_ids: list[str] = []
        delivery_to_invoice_edges: list[GraphEdge] = []
        if max_hops >= 0:
            delivery_to_invoice_edges = [e for e in self._out_edges.get(delivery_node_id, []) if e.type == "delivery_to_invoice"]
            invoice_ids = sorted({e.to_id for e in delivery_to_invoice_edges})
            invoice_cap = min(len(invoice_ids), max(1, min(50, node_cap // 3)))
            invoice_ids = invoice_ids[:invoice_cap]
            invoice_set = set(invoice_ids)
            edges.extend([e for e in delivery_to_invoice_edges if e.to_id in invoice_set])
            node_ids.update(invoice_ids)

        # Forward payments (invoice_to_payment)
        payment_ids: list[str] = []
        invoice_to_payment_edges: list[GraphEdge] = []
        if max_hops >= 1 and invoice_ids:
            for iid in invoice_ids:
                invoice_to_payment_edges.extend(
                    [e for e in self._out_edges.get(iid, []) if e.type == "invoice_to_payment"]
                )
            payment_ids = sorted({e.to_id for e in invoice_to_payment_edges})
            payment_cap = min(len(payment_ids), max(1, min(50, node_cap // 3)))
            payment_ids = payment_ids[:payment_cap]
            payment_set = set(payment_ids)
            edges.extend([e for e in invoice_to_payment_edges if e.to_id in payment_set])
            node_ids.update(payment_ids)

        # Add limited products from included orders
        product_edges_all: list[GraphEdge] = []
        for oid in order_ids:
            product_edges_all.extend([e for e in self._out_edges.get(oid, []) if e.type == "order_to_product"])

        remaining = max(0, node_cap - len(node_ids))
        seen_product_nodes: set[str] = set()
        for e in product_edges_all:
            if remaining <= 0:
                break
            if e.to_id not in seen_product_nodes:
                if len(seen_product_nodes) >= remaining:
                    break
                seen_product_nodes.add(e.to_id)
                node_ids.add(e.to_id)
            edges.append(e)

        if edge_cap is not None and len(edges) > edge_cap:
            edges = edges[:edge_cap]

        nodes = [self._node_by_id[nid] for nid in node_ids if nid in self._node_by_id]

        invoice_nodes = [self._node_by_id[iid] for iid in set(invoice_ids) if iid in self._node_by_id]
        payment_nodes = [self._node_by_id[pid] for pid in set(payment_ids) if pid in self._node_by_id]
        invoice_amount_total = _sum_numbers([n.data.get("total_net_amount") for n in invoice_nodes if n.data])
        payment_amount_total = _sum_numbers([n.data.get("amount") for n in payment_nodes if n.data])
        payment_currency = None
        for pn in payment_nodes:
            cur = (pn.data or {}).get("currency")
            if cur:
                payment_currency = cur
                break

        debug = {
            "delivery_node_id": delivery_node_id,
            "delivery_count": 1,
            "order_count": len(set(order_ids)),
            "invoice_count": len(set(invoice_ids)),
            "payment_count": len(set(payment_ids)),
            "product_count": len(set(seen_product_nodes)),
            "invoice_amount_total": invoice_amount_total,
            "payment_amount_total": payment_amount_total,
            "payment_currency": payment_currency,
        }

        return nodes, edges, debug

    def _trace_invoice(
        self,
        invoice_id: str,
        *,
        max_hops: int,
        node_cap: int,
        edge_cap: int = 5000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        invoice_node_id = f"invoice:{invoice_id}"
        if invoice_node_id not in self._node_by_id:
            return [], [], {"reason": "invoice_not_found", "invoice_id": invoice_id}
        # Strict chain priority:
        # Order -> Delivery -> Invoice -> Payment
        #
        # max_hops mapping:
        # - max_hops >= 0: include invoice_to_payment

        edges: list[GraphEdge] = []
        node_ids: set[str] = {invoice_node_id}

        # Incoming deliveries (delivery_to_invoice)
        incoming_delivery_edges = [e for e in self._in_edges.get(invoice_node_id, []) if e.type == "delivery_to_invoice"]
        delivery_ids = sorted({e.from_id for e in incoming_delivery_edges})
        delivery_cap = min(len(delivery_ids), max(1, min(50, node_cap // 3)))
        delivery_ids = delivery_ids[:delivery_cap]
        delivery_set = set(delivery_ids)
        edges.extend([e for e in incoming_delivery_edges if e.from_id in delivery_set])
        node_ids.update(delivery_ids)

        # Orders (order_to_delivery) for included deliveries
        incoming_order_edges: list[GraphEdge] = []
        for did in delivery_ids:
            incoming_order_edges.extend([e for e in self._in_edges.get(did, []) if e.type == "order_to_delivery"])
        order_ids = sorted({e.from_id for e in incoming_order_edges})
        order_cap = min(len(order_ids), max(1, min(50, node_cap // 3)))
        order_ids = order_ids[:order_cap]
        order_set = set(order_ids)
        edges.extend([e for e in incoming_order_edges if e.from_id in order_set])
        node_ids.update(order_ids)

        # Customers for orders (customer_to_order)
        customer_edges: list[GraphEdge] = []
        for oid in order_ids:
            customer_edges.extend([e for e in self._in_edges.get(oid, []) if e.type == "customer_to_order"])
        customer_edges = customer_edges[:50]
        edges.extend(customer_edges)
        node_ids.update({e.from_id for e in customer_edges})

        # Forward payments (invoice_to_payment)
        payment_ids: list[str] = []
        if max_hops >= 0:
            payment_edges = [e for e in self._out_edges.get(invoice_node_id, []) if e.type == "invoice_to_payment"]
            payment_ids = sorted({e.to_id for e in payment_edges})
            payment_cap = min(len(payment_ids), max(1, min(50, node_cap // 3)))
            payment_ids = payment_ids[:payment_cap]
            payment_set = set(payment_ids)
            edges.extend([e for e in payment_edges if e.to_id in payment_set])
            node_ids.update(payment_ids)

        # Products from included orders (limited)
        product_edges_all: list[GraphEdge] = []
        for oid in order_ids:
            product_edges_all.extend([e for e in self._out_edges.get(oid, []) if e.type == "order_to_product"])

        remaining = max(0, node_cap - len(node_ids))
        seen_product_nodes: set[str] = set()
        for e in product_edges_all:
            if remaining <= 0:
                break
            if e.to_id not in seen_product_nodes:
                if len(seen_product_nodes) >= remaining:
                    break
                seen_product_nodes.add(e.to_id)
                node_ids.add(e.to_id)
            edges.append(e)

        if edge_cap is not None and len(edges) > edge_cap:
            edges = edges[:edge_cap]

        nodes = [self._node_by_id[nid] for nid in node_ids if nid in self._node_by_id]

        invoice_nodes = [self._node_by_id[invoice_node_id]] if invoice_node_id in self._node_by_id else []
        payment_nodes = [self._node_by_id[pid] for pid in set(payment_ids) if pid in self._node_by_id]
        invoice_amount_total = _sum_numbers([n.data.get("total_net_amount") for n in invoice_nodes if n.data])
        payment_amount_total = _sum_numbers([n.data.get("amount") for n in payment_nodes if n.data])
        payment_currency = None
        for pn in payment_nodes:
            cur = (pn.data or {}).get("currency")
            if cur:
                payment_currency = cur
                break

        debug = {
            "invoice_node_id": invoice_node_id,
            "invoice_count": 1,
            "order_count": len(set(order_ids)),
            "payment_count": len(set(payment_ids)),
            "product_count": len(set(seen_product_nodes)),
            "invoice_amount_total": invoice_amount_total,
            "payment_amount_total": payment_amount_total,
            "payment_currency": payment_currency,
        }

        return nodes, edges, debug

    def _trace_customer(
        self,
        customer_id: str,
        *,
        max_hops: int,
        node_cap: int,
        edge_cap: int = 5000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        customer_node_id = f"customer:{customer_id}"
        if customer_node_id not in self._node_by_id:
            return [], [], {"reason": "customer_not_found", "customer_id": customer_id}

        max_edge_steps = max(1, max_hops + 1)
        nodes, edges = self._collect_subgraph(
            {customer_node_id},
            max_edge_steps=max_edge_steps,
            node_cap=node_cap,
            edge_cap=edge_cap,
        )

        by_type = {
            "customer": [n for n in nodes if n.type == "customer"],
            "order": [n for n in nodes if n.type == "order"],
            "delivery": [n for n in nodes if n.type == "delivery"],
            "invoice": [n for n in nodes if n.type == "invoice"],
            "payment": [n for n in nodes if n.type == "payment"],
            "product": [n for n in nodes if n.type == "product"],
        }

        invoice_amount_total = _sum_numbers([n.data.get("total_net_amount") for n in by_type["invoice"] if n.data])
        payment_amount_total = _sum_numbers([n.data.get("amount") for n in by_type["payment"] if n.data])
        payment_currency = None
        for pn in by_type["payment"]:
            cur = (pn.data or {}).get("currency")
            if cur:
                payment_currency = cur
                break

        debug = {
            "customer_node_id": customer_node_id,
            "order_count": len(by_type["order"]),
            "delivery_count": len(by_type["delivery"]),
            "invoice_count": len(by_type["invoice"]),
            "payment_count": len(by_type["payment"]),
            "product_count": len(by_type["product"]),
            "invoice_amount_total": invoice_amount_total,
            "payment_amount_total": payment_amount_total,
            "payment_currency": payment_currency,
        }

        return nodes, edges, debug

    def answer_question(self, req: GraphQueryRequest) -> GraphQueryResponse:
        if self._graph_snapshot is None:
            # Build automatically for first run.
            self.build_graph()

        graph = self._graph_snapshot
        if not graph.nodes:
            return GraphQueryResponse(
                answer="No graph data found yet. Build the graph first (POST /api/graph/build).",
                structured_query=StructuredGraphQuery(),
                graph=graph,
                debug={"reason": "empty_graph"},
            )

        structured_query, gemini_raw = self.gemini.generate_structured_query(req.question)

        # Guardrails: refuse unrelated queries (unless the model/heuristic extracted IDs).
        if not _looks_like_domain_question(req.question, structured_query):
            return GraphQueryResponse(
                answer="I can only help with orders, deliveries, invoices, payments, customers, and products from your dataset.",
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=[], edges=[]),
                debug={
                    "gemini_raw": gemini_raw,
                    "reason": "unrelated_query_guardrail",
                },
            )

        node_cap = min(req.limit, 300)

        # Prefer ID-based operations when possible (data-backed).
        if structured_query.operation == "trace_order" and structured_query.order_id:
            nodes, edges, dbg = self._trace_order(
                structured_query.order_id,
                max_hops=req.max_hops,
                node_cap=node_cap,
            )
            if not nodes:
                return GraphQueryResponse(
                    answer=f"Order {structured_query.order_id} was not found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            order_node = self._node_by_id.get(f"order:{structured_query.order_id}")
            order_total = (order_node.data or {}).get("total_net_amount") if order_node else None
            currency = (order_node.data or {}).get("currency") if order_node else None
            cust_id = (order_node.data or {}).get("customer_id") if order_node else None

            answer_lines = [
                f"Trace for Order {structured_query.order_id}:",
                f"- Customer: {cust_id}" if cust_id else "- Customer: (unknown)",
                f"- Order total: {order_total} {currency}" if order_total and currency else "- Order total: (unknown)",
                f"- Deliveries: {dbg.get('delivery_count', 0)}",
                f"- Invoices: {dbg.get('invoice_count', 0)}",
                f"- Payments: {dbg.get('payment_count', 0)}",
                f"- Products (line items): {dbg.get('product_count', 0)}",
            ]

            invoice_amount_total = dbg.get("invoice_amount_total")
            payment_amount_total = dbg.get("payment_amount_total")
            payment_currency = dbg.get("payment_currency")
            if dbg.get("invoice_count", 0) > 0:
                answer_lines.append(f"- Invoice total (sum): {_fmt_float(invoice_amount_total)}")
            if dbg.get("payment_count", 0) > 0:
                cur_part = f" {payment_currency}" if payment_currency else ""
                answer_lines.append(f"- Payment total (sum): {_fmt_float(payment_amount_total)}{cur_part}")

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )
        if structured_query.operation == "trace_delivery" and structured_query.delivery_id:
            nodes, edges, dbg = self._trace_delivery(
                structured_query.delivery_id,
                max_hops=req.max_hops,
                node_cap=node_cap,
            )
            if not nodes:
                return GraphQueryResponse(
                    answer=f"Delivery {structured_query.delivery_id} was not found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            delivery_node = self._node_by_id.get(f"delivery:{structured_query.delivery_id}")
            answer_lines = [
                f"Trace for Delivery {structured_query.delivery_id}:",
                f"- Invoices: {dbg.get('invoice_count', 0)}",
                f"- Payments: {dbg.get('payment_count', 0)}",
                f"- Orders: {dbg.get('order_count', 0)}",
            ]
            if dbg.get("invoice_count", 0) > 0:
                answer_lines.append(f"- Invoice total (sum): {_fmt_float(dbg.get('invoice_amount_total', 0.0))}")
            if dbg.get("payment_count", 0) > 0:
                cur = dbg.get("payment_currency")
                cur_part = f" {cur}" if cur else ""
                answer_lines.append(f"- Payment total (sum): {_fmt_float(dbg.get('payment_amount_total', 0.0))}{cur_part}")

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )
        if structured_query.operation == "trace_invoice" and structured_query.invoice_id:
            nodes, edges, dbg = self._trace_invoice(
                structured_query.invoice_id,
                max_hops=req.max_hops,
                node_cap=node_cap,
            )
            if not nodes:
                return GraphQueryResponse(
                    answer=f"Invoice {structured_query.invoice_id} was not found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            answer_lines = [
                f"Trace for Invoice {structured_query.invoice_id}:",
                f"- Payments: {dbg.get('payment_count', 0)}",
                f"- Orders: {dbg.get('order_count', 0)}",
            ]
            if dbg.get("invoice_count", 0) > 0:
                answer_lines.append(f"- Invoice total (sum): {_fmt_float(dbg.get('invoice_amount_total', 0.0))}")
            if dbg.get("payment_count", 0) > 0:
                cur = dbg.get("payment_currency")
                cur_part = f" {cur}" if cur else ""
                answer_lines.append(f"- Payment total (sum): {_fmt_float(dbg.get('payment_amount_total', 0.0))}{cur_part}")

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )
        if structured_query.operation == "trace_customer" and structured_query.customer_id:
            nodes, edges, dbg = self._trace_customer(
                structured_query.customer_id,
                max_hops=req.max_hops,
                node_cap=node_cap,
            )
            if not nodes:
                return GraphQueryResponse(
                    answer=f"Customer {structured_query.customer_id} was not found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            answer_lines = [
                f"Trace for Customer {structured_query.customer_id}:",
                f"- Orders: {dbg.get('order_count', 0)}",
                f"- Deliveries: {dbg.get('delivery_count', 0)}",
                f"- Invoices: {dbg.get('invoice_count', 0)}",
                f"- Payments: {dbg.get('payment_count', 0)}",
            ]
            if dbg.get("invoice_count", 0) > 0:
                answer_lines.append(f"- Invoice total (sum): {_fmt_float(dbg.get('invoice_amount_total', 0.0))}")
            if dbg.get("payment_count", 0) > 0:
                cur = dbg.get("payment_currency")
                cur_part = f" {cur}" if cur else ""
                answer_lines.append(f"- Payment total (sum): {_fmt_float(dbg.get('payment_amount_total', 0.0))}{cur_part}")

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )

        keywords = structured_query.keywords or _keywords_from_question(req.question)
        selected_nodes = _match_nodes(graph.nodes, keywords=keywords, entity_types=structured_query.entity_types)

        if not selected_nodes:
            # fallback: choose a deterministic subset based on node label text match
            selected_nodes = []
            qkw = _keywords_from_question(req.question)[:5]
            for node in graph.nodes:
                text = _node_text(node)
                if any(k in text for k in qkw):
                    selected_nodes.append(node)
                if len(selected_nodes) >= min(req.limit, 50):
                    break

        # Cap selected nodes by limit for UI safety.
        selected_nodes = selected_nodes[: min(req.limit, 100)]
        selected_ids = {n.id for n in selected_nodes}

        # Expand to include relationship chains.
        # Interpretation: `max_hops` is the number of intermediate hops to traverse
        # (so Order->Delivery->Invoice->Payment is visible when max_hops=2).
        visited_node_ids = set(selected_ids)
        frontier = set(selected_ids)
        max_edge_steps = max(1, req.max_hops + 1)

        for _ in range(max_edge_steps):
            if not frontier:
                break

            next_frontier: set[str] = set()
            for e in graph.edges:
                # Follow edges in their built direction to avoid graph blow-up.
                # (For example: order_to_product should not make traversal reach other orders.)
                if e.from_id in frontier and e.to_id not in visited_node_ids:
                    next_frontier.add(e.to_id)

            visited_node_ids.update(next_frontier)
            frontier = next_frontier

        # Select edges whose endpoints are fully inside the expanded subgraph.
        selected_edges: list[GraphEdge] = []
        edge_cap = 5000
        for e in graph.edges:
            if e.from_id in visited_node_ids and e.to_id in visited_node_ids:
                selected_edges.append(e)
                if len(selected_edges) >= edge_cap:
                    break

        subgraph_nodes = [n for n in graph.nodes if n.id in visited_node_ids]
        subgraph = {"nodes": subgraph_nodes, "edges": selected_edges}

        # Data-backed answer (simple and structured).
        by_type = {
            "customer": [n for n in subgraph_nodes if n.type == "customer"],
            "order": [n for n in subgraph_nodes if n.type == "order"],
            "delivery": [n for n in subgraph_nodes if n.type == "delivery"],
            "invoice": [n for n in subgraph_nodes if n.type == "invoice"],
            "payment": [n for n in subgraph_nodes if n.type == "payment"],
            "product": [n for n in subgraph_nodes if n.type == "product"],
        }

        order_total_sum = _sum_numbers([n.data.get("total_net_amount") for n in by_type["order"] if n.data])
        invoice_total_sum = _sum_numbers([n.data.get("total_net_amount") for n in by_type["invoice"] if n.data])
        payment_total_sum = _sum_numbers([n.data.get("amount") for n in by_type["payment"] if n.data])

        payment_currency = None
        for pn in by_type["payment"]:
            cur = (pn.data or {}).get("currency")
            if cur:
                payment_currency = cur
                break

        order_ids = [n.data.get("order_id") for n in by_type["order"] if n.data and n.data.get("order_id")]
        top_order_ids = order_ids[:5]

        answer_lines = [
            "Graph query result:",
            f"- Customers: {len(by_type['customer'])}",
            f"- Orders: {len(by_type['order'])}" + (f" (e.g. {', '.join(top_order_ids)})" if top_order_ids else ""),
            f"- Deliveries: {len(by_type['delivery'])}",
            f"- Invoices: {len(by_type['invoice'])}",
            f"- Payments: {len(by_type['payment'])}",
            f"- Products: {len(by_type['product'])}",
        ]

        if len(by_type["order"]) > 0:
            answer_lines.append(f"- Orders total (sum): {_fmt_float(order_total_sum)}")
        if len(by_type["invoice"]) > 0:
            answer_lines.append(f"- Invoices total (sum): {_fmt_float(invoice_total_sum)}")
        if len(by_type["payment"]) > 0:
            cur_part = f" {payment_currency}" if payment_currency else ""
            answer_lines.append(f"- Payments total (sum): {_fmt_float(payment_total_sum)}{cur_part}")

        answer = "\n".join(answer_lines)

        return GraphQueryResponse(
            answer=answer,
            structured_query=structured_query,
            graph=GraphSnapshot(nodes=subgraph_nodes, edges=selected_edges),
            debug={
                "gemini_raw": gemini_raw,
                "keywords": keywords,
                "selected_node_ids": list(selected_ids)[:30],
            },
        )

