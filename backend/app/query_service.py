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

    def _find_incomplete_orders(
        self,
        *,
        node_cap: int = 500,
        edge_cap: int = 2000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        """
        Find orders with incomplete data flows:
        - Delivery exists but no invoice
        - Invoice exists but no delivery
        - Invoice exists but no payment

        Returns tuple of (nodes, edges, debug_info)
        """
        graph = self._graph_snapshot
        if not graph:
            return [], [], {"reason": "no_graph"}

        # Maps to track relationships for each order
        orders_with_deliveries: dict[str, set[str]] = {}  # order_id -> set of delivery_ids
        orders_with_invoices: dict[str, set[str]] = {}    # order_id -> set of invoice_ids
        invoices_with_payments: dict[str, set[str]] = {}  # invoice_id -> set of payment_ids

        # First pass: collect all relationships
        for edge in graph.edges:
            if edge.type == "order_to_delivery":
                from_id_parts = edge.from_id.split(":")
                to_id_parts = edge.to_id.split(":")
                if len(from_id_parts) >= 2 and len(to_id_parts) >= 2:
                    order_id = from_id_parts[1]
                    delivery_id = to_id_parts[1]
                    orders_with_deliveries.setdefault(order_id, set()).add(delivery_id)

            elif edge.type == "delivery_to_invoice":
                to_id_parts = edge.to_id.split(":")
                if len(to_id_parts) >= 2:
                    invoice_id = to_id_parts[1]
                    # Map back from delivery to order
                    from_id_parts = edge.from_id.split(":")
                    if len(from_id_parts) >= 2:
                        delivery_id = from_id_parts[1]
                        # Find which orders have this delivery
                        for order_id, deliveries in orders_with_deliveries.items():
                            if delivery_id in deliveries:
                                orders_with_invoices.setdefault(order_id, set()).add(invoice_id)

            elif edge.type == "invoice_to_payment":
                from_id_parts = edge.from_id.split(":")
                if len(from_id_parts) >= 2:
                    invoice_id = from_id_parts[1]
                    to_id_parts = edge.to_id.split(":")
                    if len(to_id_parts) >= 2:
                        payment_id = to_id_parts[1]
                        invoices_with_payments.setdefault(invoice_id, set()).add(payment_id)

        # Identify problematic orders and collect nodes/edges
        problematic_nodes: set[str] = set()
        problematic_edges: list[GraphEdge] = []
        incomplete_cases: list[dict[str, Any]] = []

        # Case 1: Delivery exists but no invoice
        for order_id, delivery_ids in orders_with_deliveries.items():
            invoice_ids = orders_with_invoices.get(order_id, set())
            if delivery_ids and not invoice_ids:
                # This order has deliveries but no invoices
                case_nodes = {f"order:{order_id}"}
                case_edges: list[GraphEdge] = []
                
                for delivery_id in list(delivery_ids)[:10]:  # Limit deliveries shown
                    case_nodes.add(f"delivery:{delivery_id}")
                    # Find the edges
                    for edge in graph.edges:
                        if (edge.from_id == f"order:{order_id}" and 
                            edge.to_id == f"delivery:{delivery_id}" and 
                            edge.type == "order_to_delivery"):
                            case_edges.append(edge)
                            break

                problematic_nodes.update(case_nodes)
                problematic_edges.extend(case_edges)
                incomplete_cases.append({
                    "case": "delivery_no_invoice",
                    "order_id": order_id,
                    "node_ids": list(case_nodes),
                    "delivery_count": len(delivery_ids),
                })

        # Case 2: Invoice exists but no delivery
        # This is detected when we have invoices but they don't trace back to deliveries
        invoice_to_orders: dict[str, str] = {}  # invoice_id -> order_id
        for edge in graph.edges:
            if edge.type == "delivery_to_invoice":
                to_id_parts = edge.to_id.split(":")
                from_id_parts = edge.from_id.split(":")
                if len(to_id_parts) >= 2 and len(from_id_parts) >= 2:
                    invoice_id = to_id_parts[1]
                    delivery_id = from_id_parts[1]
                    # Find order for this delivery
                    for edge2 in graph.edges:
                        if (edge2.type == "order_to_delivery" and 
                            edge2.to_id == f"delivery:{delivery_id}"):
                            from_id_parts2 = edge2.from_id.split(":")
                            if len(from_id_parts2) >= 2:
                                order_id = from_id_parts2[1]
                                invoice_to_orders[invoice_id] = order_id

        # Find invoices that have no corresponding delivery (orphan invoices)
        for edge in graph.edges:
            if edge.type == "delivery_to_invoice":
                to_id_parts = edge.to_id.split(":")
                if len(to_id_parts) >= 2:
                    invoice_id = to_id_parts[1]
                    # Check if this invoice comes from a delivery
                    from_id_parts = edge.from_id.split(":")
                    if len(from_id_parts) >= 2:
                        # This invoice HAS a delivery, so skip it
                        continue

        # Case 3: Invoice exists but no payment
        unpaid_invoices: list[tuple[str, str]] = []  # (order_id, invoice_id)
        for order_id, invoice_ids in orders_with_invoices.items():
            for invoice_id in invoice_ids:
                if invoice_id not in invoices_with_payments or not invoices_with_payments[invoice_id]:
                    unpaid_invoices.append((order_id, invoice_id))

        for order_id, invoice_id in unpaid_invoices[:20]:  # Limit to 20 cases
            case_nodes = {f"order:{order_id}", f"invoice:{invoice_id}"}
            case_edges: list[GraphEdge] = []
            
            # Find edges connecting order to delivery to invoice
            for edge in graph.edges:
                if (edge.type == "order_to_delivery" and 
                    edge.from_id == f"order:{order_id}"):
                    delivery_id = edge.to_id.split(":")[1]
                    case_nodes.add(edge.to_id)
                    case_edges.append(edge)
                    
                    # Find delivery to invoice edge
                    for edge2 in graph.edges:
                        if (edge2.type == "delivery_to_invoice" and 
                            edge2.from_id == f"delivery:{delivery_id}" and 
                            edge2.to_id == f"invoice:{invoice_id}"):
                            case_nodes.add(f"delivery:{delivery_id}")
                            case_edges.append(edge2)
                            break
                    break

            problematic_nodes.update(case_nodes)
            problematic_edges.extend(case_edges)
            incomplete_cases.append({
                "case": "invoice_no_payment",
                "order_id": order_id,
                "invoice_id": invoice_id,
                "node_ids": list(case_nodes),
            })

        # Build final nodes list from collected node IDs
        nodes = [self._node_by_id[nid] for nid in problematic_nodes if nid in self._node_by_id]
        nodes = nodes[:node_cap]

        # Enforce edge cap
        if len(problematic_edges) > edge_cap:
            problematic_edges = problematic_edges[:edge_cap]

        debug = {
            "total_incomplete_cases": len(incomplete_cases),
            "delivery_no_invoice_count": sum(1 for c in incomplete_cases if c["case"] == "delivery_no_invoice"),
            "invoice_no_payment_count": sum(1 for c in incomplete_cases if c["case"] == "invoice_no_payment"),
            "incomplete_cases": incomplete_cases[:50],  # Return first 50 for analysis
        }

        return nodes, problematic_edges, debug

    def _analyze_product_billing_volume(
        self,
        *,
        node_cap: int = 200,
        edge_cap: int = 2000,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        """
        Analyze products by their billing document (invoice) count.
        Traverses: Product <- Order -> Delivery -> Invoice
        Groups by product and counts total invoices per product.
        Returns: Top products sorted by invoice volume, with subgraph.
        """
        graph = self._graph_snapshot
        if not graph:
            return [], [], {"reason": "no_graph", "message": "No billing data available"}

        # Build reverse index: product -> orders
        product_to_orders: dict[str, set[str]] = {}  # "product:id" -> set("order:id")
        order_to_deliveries: dict[str, set[str]] = {}  # "order:id" -> set("delivery:id")
        delivery_to_invoices: dict[str, set[str]] = {}  # "delivery:id" -> set("invoice:id")

        # Phase 1: Index all edges
        for edge in graph.edges:
            if edge.type == "order_to_product":
                # Reverse: product gains order
                product_id = edge.to_id  # product is the target
                order_id = edge.from_id   # order is the source
                product_to_orders.setdefault(product_id, set()).add(order_id)

            elif edge.type == "order_to_delivery":
                order_id = edge.from_id
                delivery_id = edge.to_id
                order_to_deliveries.setdefault(order_id, set()).add(delivery_id)

            elif edge.type == "delivery_to_invoice":
                delivery_id = edge.from_id
                invoice_id = edge.to_id
                delivery_to_invoices.setdefault(delivery_id, set()).add(invoice_id)

        # Phase 2: Aggregate invoice counts per product
        product_invoice_counts: dict[str, dict[str, Any]] = {}  # product_id -> {count, invoices, orders_sample}

        for product_node_id, orders in product_to_orders.items():
            invoice_set: set[str] = set()
            orders_with_invoices: list[str] = []
            sample_deliveries: list[str] = []

            for order_id in orders:
                deliveries = order_to_deliveries.get(order_id, set())
                if deliveries:
                    orders_with_invoices.append(order_id)
                    for delivery_id in deliveries:
                        invoices = delivery_to_invoices.get(delivery_id, set())
                        if invoices:
                            invoice_set.update(invoices)
                            sample_deliveries.append(delivery_id)

            count = len(invoice_set)
            if count > 0:
                product_invoice_counts[product_node_id] = {
                    "count": count,
                    "invoices": sorted(list(invoice_set))[:100],  # Limit to 100 for processing
                    "orders_with_invoices": len(orders_with_invoices),
                    "orders_sample": sorted(list(orders_with_invoices))[:5],
                    "deliveries_sample": sorted(list(set(sample_deliveries)))[:5],
                }

        # Phase 3: Sort by invoice count (descending)
        if not product_invoice_counts:
            return [], [], {
                "reason": "no_data",
                "message": "No billing data available",
                "product_invoice_counts": {},
            }

        sorted_products = sorted(
            product_invoice_counts.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )

        # Phase 4: Build subgraph for top products (limit to avoid explosion)
        nodes_set: set[str] = set()
        edges_list: list[GraphEdge] = []

        # Include top 5 products
        top_products = sorted_products[:5]
        for product_node_id, stats in top_products:
            nodes_set.add(product_node_id)
            # Add sample orders
            for order_id in stats["orders_sample"]:
                nodes_set.add(order_id)
                # Find order->product edge
                for edge in graph.edges:
                    if (edge.type == "order_to_product" and 
                        edge.from_id == order_id and 
                        edge.to_id == product_node_id):
                        edges_list.append(edge)
                        break
                # Add sample deliveries
                for delivery_id in stats["deliveries_sample"]:
                    if delivery_id in order_to_deliveries.get(order_id, set()):
                        nodes_set.add(delivery_id)
                        # Add order->delivery edge
                        for edge in graph.edges:
                            if (edge.type == "order_to_delivery" and 
                                edge.from_id == order_id and 
                                edge.to_id == delivery_id):
                                edges_list.append(edge)
                                break
                        # Add sample invoices for this delivery
                        invoices = delivery_to_invoices.get(delivery_id, set())
                        for invoice_id in list(invoices)[:3]:  # Show 3 sample invoices max per delivery
                            nodes_set.add(invoice_id)
                            # Add delivery->invoice edge
                            for edge in graph.edges:
                                if (edge.type == "delivery_to_invoice" and 
                                    edge.from_id == delivery_id and 
                                    edge.to_id == invoice_id):
                                    edges_list.append(edge)
                                    break

        # Phase 5: Build output nodes and enforce caps
        nodes = [self._node_by_id[nid] for nid in nodes_set if nid in self._node_by_id]
        nodes = nodes[:min(len(nodes), node_cap)]

        if len(edges_list) > edge_cap:
            edges_list = edges_list[:edge_cap]

        # Phase 6: Prepare debug info
        debug = {
            "total_products_with_billing": len(product_invoice_counts),
            "top_products": [
                {
                    "product_node_id": prod_id,
                    "product_name": self._node_by_id.get(prod_id, GraphNode(id="", type="", label="")).label,
                    "invoice_count": stats["count"],
                    "orders_count": stats["orders_with_invoices"],
                    "top_invoices": stats["invoices"][:10],
                }
                for prod_id, stats in sorted_products[:10]
            ],
            "highest_invoice_count": sorted_products[0][1]["count"] if sorted_products else 0,
            "highest_product_id": sorted_products[0][0] if sorted_products else None,
        }

        return nodes, edges_list, debug

    def _trace_billing_document_flow(
        self,
        invoice_id: str,
    ) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
        """
        Trace the complete flow of a specific billing document (invoice):
        Sales Order → Delivery → Invoice → Payment (Journal Entry)

        Returns: (nodes, edges, debug_info) with structured path information
        """
        graph = self._graph_snapshot
        if not graph:
            return [], [], {"reason": "no_graph", "path": []}

        # Check if invoice exists
        invoice_node_id = f"invoice:{invoice_id}"
        if invoice_node_id not in self._node_by_id:
            return [], [], {
                "reason": "invoice_not_found",
                "invoice_id": invoice_id,
                "path": [],
                "status": "FAILED - Invoice not found",
            }

        invoice_node = self._node_by_id[invoice_node_id]
        path_items: list[dict[str, Any]] = [
            {
                "step": 1,
                "node_type": "invoice",
                "node_id": invoice_id,
                "node_label": invoice_node.label,
                "status": "FOUND ✓",
            }
        ]

        # Step 2: Find Delivery → Invoice edges (incoming)
        delivery_ids: list[str] = []
        delivery_invoice_edges: list[GraphEdge] = []

        for edge in graph.edges:
            if (edge.type == "delivery_to_invoice" and 
                edge.to_id == invoice_node_id):
                from_id_parts = edge.from_id.split(":")
                if len(from_id_parts) >= 2:
                    delivery_id = from_id_parts[1]
                    delivery_ids.append(delivery_id)
                    delivery_invoice_edges.append(edge)

        if delivery_ids:
            delivery_id = delivery_ids[0]  # Take first (usually only one per invoice)
            path_items.append({
                "step": 2,
                "node_type": "delivery",
                "node_id": delivery_id,
                "node_label": self._node_by_id.get(f"delivery:{delivery_id}", GraphNode(id="", type="", label="")).label,
                "edge_type": "delivery_to_invoice",
                "status": f"FOUND ✓ ({len(delivery_ids)} delivery(ies))",
            })
        else:
            path_items.append({
                "step": 2,
                "node_type": "delivery",
                "node_id": None,
                "status": "MISSING ✗ - No delivery linked to this invoice",
            })

        # Step 3: Find Order → Delivery edges (incoming)
        order_ids: list[str] = []
        order_delivery_edges: list[GraphEdge] = []

        if delivery_ids:
            delivery_node_id = f"delivery:{delivery_ids[0]}"
            for edge in graph.edges:
                if (edge.type == "order_to_delivery" and 
                    edge.to_id == delivery_node_id):
                    from_id_parts = edge.from_id.split(":")
                    if len(from_id_parts) >= 2:
                        order_id = from_id_parts[1]
                        order_ids.append(order_id)
                        order_delivery_edges.append(edge)

        if order_ids:
            order_id = order_ids[0]  # Take first
            path_items.append({
                "step": 3,
                "node_type": "order",
                "node_id": order_id,
                "node_label": self._node_by_id.get(f"order:{order_id}", GraphNode(id="", type="", label="")).label,
                "edge_type": "order_to_delivery",
                "status": f"FOUND ✓ ({len(order_ids)} order(s))",
            })
        else:
            path_items.append({
                "step": 3,
                "node_type": "order",
                "node_id": None,
                "status": "MISSING ✗ - No order linked to delivery",
            })

        # Step 4: Find Invoice → Payment/Journal Entry (outgoing)
        payment_ids: list[str] = []
        invoice_payment_edges: list[GraphEdge] = []

        for edge in graph.edges:
            if (edge.type == "invoice_to_payment" and 
                edge.from_id == invoice_node_id):
                to_id_parts = edge.to_id.split(":")
                if len(to_id_parts) >= 2:
                    payment_id = to_id_parts[1]
                    payment_ids.append(payment_id)
                    invoice_payment_edges.append(edge)

        if payment_ids:
            payment_id = payment_ids[0]  # Take first
            payment_node = self._node_by_id.get(f"payment:{payment_id}")
            path_items.append({
                "step": 4,
                "node_type": "payment/journal_entry",
                "node_id": payment_id,
                "node_label": payment_node.label if payment_node else payment_id,
                "edge_type": "invoice_to_payment",
                "journal_entry_count": len(payment_ids),
                "status": f"FOUND ✓ ({len(payment_ids)} payment(s)/journal entry(ies))",
            })
        else:
            path_items.append({
                "step": 4,
                "node_type": "payment/journal_entry",
                "node_id": None,
                "status": "MISSING ✗ - No payment/journal entry linked to invoice",
            })

        # Build minimal subgraph for visualization
        nodes_set: set[str] = {invoice_node_id}
        edges_list: list[GraphEdge] = []

        # Add delivery if found
        if delivery_ids:
            delivery_node_id = f"delivery:{delivery_ids[0]}"
            nodes_set.add(delivery_node_id)
            edges_list.extend(delivery_invoice_edges)

        # Add order if found
        if order_ids:
            order_node_id = f"order:{order_ids[0]}"
            nodes_set.add(order_node_id)
            edges_list.extend(order_delivery_edges)

        # Add payment if found
        if payment_ids:
            payment_node_id = f"payment:{payment_ids[0]}"
            nodes_set.add(payment_node_id)
            edges_list.extend(invoice_payment_edges)

        # Build nodes list
        nodes = [self._node_by_id[nid] for nid in nodes_set if nid in self._node_by_id]

        # Determine overall status
        all_steps_complete = (len(order_ids) > 0 and 
                            len(delivery_ids) > 0 and 
                            len(payment_ids) > 0)
        overall_status = "COMPLETE ✓" if all_steps_complete else "INCOMPLETE ⚠ (Missing links)"

        # Build debug info
        debug = {
            "invoice_id": invoice_id,
            "path": path_items,
            "overall_status": overall_status,
            "order_found": len(order_ids) > 0,
            "delivery_found": len(delivery_ids) > 0,
            "payment_found": len(payment_ids) > 0,
            "order_id": order_ids[0] if order_ids else None,
            "delivery_id": delivery_ids[0] if delivery_ids else None,
            "payment_id": payment_ids[0] if payment_ids else None,
            "missing_steps": [
                item["node_type"] for item in path_items 
                if item.get("status") and "MISSING" in item["status"]
            ],
        }

        return nodes, edges_list, debug

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

        if structured_query.operation == "find_incomplete_orders":
            nodes, edges, dbg = self._find_incomplete_orders(
                node_cap=min(req.limit, 300),
                edge_cap=5000,
            )

            if not nodes:
                return GraphQueryResponse(
                    answer="No incomplete orders found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            incomplete_cases = dbg.get("incomplete_cases", [])
            total = dbg.get("total_incomplete_cases", 0)
            delivery_no_inv = dbg.get("delivery_no_invoice_count", 0)
            invoice_no_pay = dbg.get("invoice_no_payment_count", 0)

            # Build detailed answer
            answer_lines = [
                f"Found {total} incomplete orders:",
                "",
                f"1. Delivery exists but no invoice: {delivery_no_inv} case(s)",
                f"   - Orders have been delivered but not yet invoiced",
                "",
                f"2. Invoice exists but no payment: {invoice_no_pay} case(s)",
                f"   - Invoices have been issued but not yet paid",
                "",
                "Sample cases:",
            ]

            # Add sample cases
            samples_shown = 0
            for case in incomplete_cases[:10]:
                case_type = case.get("case")
                order_id = case.get("order_id")
                if case_type == "delivery_no_invoice":
                    delivery_count = case.get("delivery_count", 0)
                    answer_lines.append(f"  • Order {order_id}: {delivery_count} delivery(ies), no invoice")
                    samples_shown += 1
                elif case_type == "invoice_no_payment":
                    invoice_id = case.get("invoice_id")
                    answer_lines.append(f"  • Order {order_id}: Invoice {invoice_id}, no payment")
                    samples_shown += 1

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )

        if structured_query.operation == "analyze_product_billing_volume":
            nodes, edges, dbg = self._analyze_product_billing_volume(
                node_cap=min(req.limit, 200),
                edge_cap=5000,
            )

            # Check for no data scenario
            if dbg.get("reason") == "no_data":
                return GraphQueryResponse(
                    answer="No billing data available. No products have associated invoices (billing documents).",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            if not nodes:
                return GraphQueryResponse(
                    answer="No billing data available. Make sure the graph has been built and contains invoices.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            top_products = dbg.get("top_products", [])
            total_products = dbg.get("total_products_with_billing", 0)
            highest_count = dbg.get("highest_invoice_count", 0)

            # Build detailed answer
            answer_lines = [
                f"Product Billing Volume Analysis:",
                f"Total products with billing documents: {total_products}",
                "",
            ]

            if top_products:
                answer_lines.append(f"Top products by invoice count:")
                for idx, prod in enumerate(top_products[:5], 1):
                    product_name = prod.get("product_name") or prod.get("product_node_id", "Unknown")
                    invoice_count = prod.get("invoice_count", 0)
                    orders_count = prod.get("orders_count", 0)
                    answer_lines.append(
                        f"{idx}. Product: {product_name}"
                    )
                    answer_lines.append(
                        f"   Billing Documents (Invoices): {invoice_count}"
                    )
                    answer_lines.append(
                        f"   Associated Orders: {orders_count}"
                    )
                    answer_lines.append("")

                # Highlight the winner
                winner = top_products[0]
                answer_lines.insert(
                    2,
                    f"🏆 Highest: '{winner.get('product_name') or winner.get('product_node_id')}' with {winner.get('invoice_count', 0)} billing documents\n"
                )

            return GraphQueryResponse(
                answer="\n".join(answer_lines),
                structured_query=structured_query,
                graph=GraphSnapshot(nodes=nodes, edges=edges),
                debug={"gemini_raw": gemini_raw, **dbg},
            )

        if structured_query.operation == "trace_billing_document_flow":
            # If no invoice_id provided, pick a sample one from the graph
            invoice_id_to_use = structured_query.invoice_id
            if not invoice_id_to_use:
                # Pick first available invoice as sample
                for node_id in self._node_by_id:
                    if node_id.startswith("invoice:"):
                        invoice_id_to_use = node_id.split(":", 1)[1]  # Extract ID after "invoice:"
                        break
            
            if not invoice_id_to_use:
                return GraphQueryResponse(
                    answer="No invoices found in the graph to trace.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, "error": "no_invoices"},
                )
            
            nodes, edges, dbg = self._trace_billing_document_flow(invoice_id_to_use)

            if dbg.get("reason") == "invoice_not_found":
                return GraphQueryResponse(
                    answer=f"Invoice {invoice_id_to_use} was not found in the graph.",
                    structured_query=structured_query,
                    graph=GraphSnapshot(nodes=[], edges=[]),
                    debug={"gemini_raw": gemini_raw, **dbg},
                )

            # Build structured path output
            path_items = dbg.get("path", [])
            overall_status = dbg.get("overall_status", "UNKNOWN")
            missing_steps = dbg.get("missing_steps", [])

            answer_lines = [
                "📋 BILLING DOCUMENT FLOW TRACE",
                f"Invoice ID: {invoice_id_to_use}",
                f"Overall Status: {overall_status}",
                "",
                "Document Flow Path:",
                "─" * 50,
            ]

            # Add each step with status
            for item in path_items:
                step = item.get("step")
                node_type = item.get("node_type")
                node_id = item.get("node_id")
                status = item.get("status", "UNKNOWN")
                node_label = item.get("node_label", node_id)

                if node_id:
                    answer_lines.append(f"\n{step}. {node_type.upper()}")
                    answer_lines.append(f"   ID: {node_id}")
                    answer_lines.append(f"   Label: {node_label}")
                    answer_lines.append(f"   Status: {status}")
                else:
                    answer_lines.append(f"\n{step}. {node_type.upper()}")
                    answer_lines.append(f"   Status: {status}")

            answer_lines.append("\n" + "─" * 50)

            # Provide clear summary
            if overall_status.startswith("COMPLETE"):
                answer_lines.append("\n✓ SUCCESS: Full document flow traced")
                answer_lines.append("All nodes from Sales Order → Delivery → Invoice → Payment found")
            else:
                answer_lines.append(f"\n⚠ INCOMPLETE: Missing {len(missing_steps)} step(s)")
                for missing in missing_steps:
                    answer_lines.append(f"  • {missing.upper()}")

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

