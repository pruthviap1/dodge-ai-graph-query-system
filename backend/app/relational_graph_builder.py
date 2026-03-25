from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator

from backend.app.schemas import GraphEdge, GraphNode, GraphSnapshot


NODE_CUSTOMER = "customer"
NODE_ORDER = "order"
NODE_DELIVERY = "delivery"
NODE_INVOICE = "invoice"
NODE_PAYMENT = "payment"
NODE_PRODUCT = "product"


EDGE_CUSTOMER_TO_ORDER = "customer_to_order"
EDGE_ORDER_TO_DELIVERY = "order_to_delivery"
EDGE_DELIVERY_TO_INVOICE = "delivery_to_invoice"
EDGE_INVOICE_TO_PAYMENT = "invoice_to_payment"
EDGE_ORDER_TO_PRODUCT = "order_to_product"


def _iter_jsonl_records(folder: Path) -> Iterator[dict[str, Any]]:
    """
    Streams records from all *.jsonl files in the folder tree.
    """
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
        except Exception:
            continue


def _norm_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _search_text(*parts: Any) -> str:
    # Lowercase concatenated values used by query keyword matching.
    cleaned: list[str] = []
    for p in parts:
        if p is None:
            continue
        cleaned.append(str(p))
    return " ".join(cleaned).lower()


def _node_id(node_type: str, raw_id: str) -> str:
    return f"{node_type}:{raw_id}"


def build_relational_graph(data_dir: Path) -> tuple[GraphSnapshot, list[str]]:
    """
    Builds a graph using real relationships inferred from dataset foreign keys:
    - Customer -> Order (sales_order_headers.soldToParty -> business_partners.customer)
    - Order -> Delivery (outbound_delivery_items.referenceSdDocument -> sales_order_headers.salesOrder)
    - Delivery -> Invoice (billing_document_items.referenceSdDocument -> outbound_delivery_headers.deliveryDocument)
    - Invoice -> Payment (billing_document_headers.accountingDocument -> payments_accounts_receivable.accountingDocument)
    - Order -> Product (sales_order_items.material -> products.product)

    Only 6 node types are created: Customers, Orders, Deliveries, Invoices, Payments, Products.
    """
    # --- dataset paths ---
    orders_dir = data_dir / "sales_order_headers"
    order_items_dir = data_dir / "sales_order_items"

    deliveries_dir = data_dir / "outbound_delivery_headers"
    delivery_items_dir = data_dir / "outbound_delivery_items"

    invoices_dir = data_dir / "billing_document_headers"
    invoice_items_dir = data_dir / "billing_document_items"

    payments_dir = data_dir / "payments_accounts_receivable"

    customers_dir = data_dir / "business_partners"

    products_dir = data_dir / "products"
    product_desc_dir = data_dir / "product_descriptions"

    sources = []
    for p in [
        orders_dir,
        order_items_dir,
        deliveries_dir,
        delivery_items_dir,
        invoices_dir,
        invoice_items_dir,
        payments_dir,
        customers_dir,
        products_dir,
        product_desc_dir,
    ]:
        if p.exists():
            sources.append(p.name)

    # --- nodes: Customers ---
    customers: dict[str, GraphNode] = {}
    for r in _iter_jsonl_records(customers_dir):
        customer_id = _norm_str(r.get("customer") or r.get("businessPartner"))
        if not customer_id:
            continue
        full_name = _norm_str(r.get("businessPartnerFullName") or r.get("businessPartnerName"))
        node_id = _node_id(NODE_CUSTOMER, customer_id)
        customers[node_id] = GraphNode(
            id=node_id,
            type=NODE_CUSTOMER,
            label=full_name or customer_id,
            data={
                "customer_id": customer_id,
                "full_name": full_name,
                "search_text": _search_text(customer_id, full_name),
            },
        )

    # --- nodes: Products ---
    product_desc: dict[str, str] = {}
    for r in _iter_jsonl_records(product_desc_dir):
        product_id = _norm_str(r.get("product"))
        if not product_id:
            continue
        desc = _norm_str(r.get("productDescription"))
        if desc:
            product_desc[product_id] = desc

    products: dict[str, GraphNode] = {}
    for r in _iter_jsonl_records(products_dir):
        product_id = _norm_str(r.get("product"))
        if not product_id:
            continue
        desc = product_desc.get(product_id)
        node_id = _node_id(NODE_PRODUCT, product_id)
        products[node_id] = GraphNode(
            id=node_id,
            type=NODE_PRODUCT,
            label=desc or product_id,
            data={
                "product_id": product_id,
                "product_type": _norm_str(r.get("productType")),
                "product_group": _norm_str(r.get("productGroup")),
                "description": desc,
                "search_text": _search_text(product_id, desc),
            },
        )

    # --- nodes: Orders ---
    orders: dict[str, GraphNode] = {}
    order_customer_id: dict[str, str | None] = {}
    for r in _iter_jsonl_records(orders_dir):
        order_id = _norm_str(r.get("salesOrder"))
        if not order_id:
            continue
        customer_id = _norm_str(r.get("soldToParty"))
        node_id = _node_id(NODE_ORDER, order_id)
        orders[node_id] = GraphNode(
            id=node_id,
            type=NODE_ORDER,
            label=f"SO {order_id}",
            data={
                "sales_order": order_id,
                "order_id": order_id,
                "customer_id": customer_id,
                "currency": _norm_str(r.get("transactionCurrency")),
                "total_net_amount": _norm_str(r.get("totalNetAmount")),
                "delivery_status": _norm_str(r.get("overallDeliveryStatus")),
                "search_text": _search_text(order_id, customer_id),
            },
        )
        order_customer_id[node_id] = customer_id

    # --- nodes: Deliveries ---
    deliveries: dict[str, GraphNode] = {}
    for r in _iter_jsonl_records(deliveries_dir):
        delivery_id = _norm_str(r.get("deliveryDocument"))
        if not delivery_id:
            continue
        node_id = _node_id(NODE_DELIVERY, delivery_id)
        deliveries[node_id] = GraphNode(
            id=node_id,
            type=NODE_DELIVERY,
            label=f"Delivery {delivery_id}",
            data={
                "delivery_id": delivery_id,
                "shipping_point": _norm_str(r.get("shippingPoint")),
                "overall_goods_movement_status": _norm_str(r.get("overallGoodsMovementStatus")),
                "search_text": _search_text(delivery_id),
            },
        )

    # --- nodes: Invoices ---
    invoices: dict[str, GraphNode] = {}
    invoice_accounting_doc: dict[str, str | None] = {}
    for r in _iter_jsonl_records(invoices_dir):
        invoice_id = _norm_str(r.get("billingDocument"))
        if not invoice_id:
            continue
        accounting_doc = _norm_str(r.get("accountingDocument"))
        node_id = _node_id(NODE_INVOICE, invoice_id)
        invoices[node_id] = GraphNode(
            id=node_id,
            type=NODE_INVOICE,
            label=f"Invoice {invoice_id}",
            data={
                "billing_document": invoice_id,
                "invoice_id": invoice_id,
                "accounting_document": accounting_doc,
                "company_code": _norm_str(r.get("companyCode")),
                "fiscal_year": _norm_str(r.get("fiscalYear")),
                "sold_to_party": _norm_str(r.get("soldToParty")),
                "total_net_amount": _norm_str(r.get("totalNetAmount")),
                "is_cancelled": bool(r.get("billingDocumentIsCancelled", False)),
                "search_text": _search_text(invoice_id, accounting_doc),
            },
        )
        invoice_accounting_doc[node_id] = accounting_doc

    # --- nodes: Payments ---
    payments: dict[str, GraphNode] = {}
    payments_by_invoice_accounting_doc: dict[str, list[str]] = defaultdict(list)

    for r in _iter_jsonl_records(payments_dir):
        company_code = _norm_str(r.get("companyCode"))
        fiscal_year = _norm_str(r.get("fiscalYear"))
        accounting_doc = _norm_str(r.get("accountingDocument"))
        accounting_doc_item = _norm_str(r.get("accountingDocumentItem"))
        customer_id = _norm_str(r.get("customer"))

        if not (company_code and fiscal_year and accounting_doc and accounting_doc_item):
            continue

        pay_node_id = _node_id(
            NODE_PAYMENT,
            f"{company_code}:{fiscal_year}:{accounting_doc}:{accounting_doc_item}",
        )
        label = f"Payment {accounting_doc} (item {accounting_doc_item})"

        payments[pay_node_id] = GraphNode(
            id=pay_node_id,
            type=NODE_PAYMENT,
            label=label,
            data={
                "company_code": company_code,
                "fiscal_year": fiscal_year,
                "accounting_document": accounting_doc,
                "accounting_document_item": accounting_doc_item,
                "customer_id": customer_id,
                "amount": _norm_str(r.get("amountInTransactionCurrency")),
                "currency": _norm_str(r.get("transactionCurrency")),
                "clearing_date": _norm_str(r.get("clearingDate")),
                "search_text": _search_text(accounting_doc, accounting_doc_item, customer_id),
            },
        )

        payments_by_invoice_accounting_doc[accounting_doc].append(pay_node_id)

    # --- edges (dedup sets) ---
    edges: list[GraphEdge] = []
    seen_customer_order: set[tuple[str, str]] = set()
    seen_order_delivery: set[tuple[str, str]] = set()
    seen_delivery_invoice: set[tuple[str, str]] = set()
    seen_invoice_payment: set[tuple[str, str]] = set()
    seen_order_product_item: set[tuple[str, str, str]] = set()

    # Customer -> Order
    for order_node_id, cust_id in order_customer_id.items():
        if not cust_id:
            continue
        cust_node_id = _node_id(NODE_CUSTOMER, cust_id)
        if cust_node_id not in customers:
            continue
        key = (cust_node_id, order_node_id)
        if key in seen_customer_order:
            continue
        seen_customer_order.add(key)
        edges.append(
            GraphEdge(
                from_id=cust_node_id,
                to_id=order_node_id,
                type=EDGE_CUSTOMER_TO_ORDER,
                label=EDGE_CUSTOMER_TO_ORDER,
                data={},
            )
        )

    # Order -> Delivery (via outbound_delivery_items.referenceSdDocument)
    delivery_item_pair_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for r in _iter_jsonl_records(delivery_items_dir):
        order_ref = _norm_str(r.get("referenceSdDocument"))
        delivery_id = _norm_str(r.get("deliveryDocument"))
        if not (order_ref and delivery_id):
            continue
        order_node_id = _node_id(NODE_ORDER, order_ref)
        delivery_node_id = _node_id(NODE_DELIVERY, delivery_id)
        if order_node_id not in orders or delivery_node_id not in deliveries:
            continue
        key = (order_node_id, delivery_node_id)

        # Track item-level references but only emit a single edge per order-delivery pair.
        if key not in delivery_item_pair_stats:
            delivery_item_pair_stats[key] = {
                "count": 0,
                "reference_item_ids": set(),
            }
        delivery_item_pair_stats[key]["count"] += 1
        item_ref = _norm_str(r.get("referenceSdDocumentItem"))
        if item_ref:
            delivery_item_pair_stats[key]["reference_item_ids"].add(item_ref)

    for (order_node_id, delivery_node_id), stats in delivery_item_pair_stats.items():
        if (order_node_id, delivery_node_id) in seen_order_delivery:
            continue
        seen_order_delivery.add((order_node_id, delivery_node_id))
        edges.append(
            GraphEdge(
                from_id=order_node_id,
                to_id=delivery_node_id,
                type=EDGE_ORDER_TO_DELIVERY,
                label=EDGE_ORDER_TO_DELIVERY,
                data={
                    "delivery_item_count": stats["count"],
                    "order_item_references": sorted(stats["reference_item_ids"])[:10],
                },
            )
        )

    # Delivery -> Invoice (via billing_document_items.referenceSdDocument)
    delivery_invoice_pair_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for r in _iter_jsonl_records(invoice_items_dir):
        delivery_ref = _norm_str(r.get("referenceSdDocument"))
        invoice_id = _norm_str(r.get("billingDocument"))
        if not (delivery_ref and invoice_id):
            continue
        delivery_node_id = _node_id(NODE_DELIVERY, delivery_ref)
        invoice_node_id = _node_id(NODE_INVOICE, invoice_id)
        if delivery_node_id not in deliveries or invoice_node_id not in invoices:
            continue

        key = (delivery_node_id, invoice_node_id)
        if key not in delivery_invoice_pair_stats:
            delivery_invoice_pair_stats[key] = {
                "count": 0,
                "delivery_item_refs": set(),
            }
        delivery_invoice_pair_stats[key]["count"] += 1
        delivery_item_ref = _norm_str(r.get("referenceSdDocumentItem"))
        if delivery_item_ref:
            delivery_invoice_pair_stats[key]["delivery_item_refs"].add(delivery_item_ref)

    for (delivery_node_id, invoice_node_id), stats in delivery_invoice_pair_stats.items():
        if (delivery_node_id, invoice_node_id) in seen_delivery_invoice:
            continue
        seen_delivery_invoice.add((delivery_node_id, invoice_node_id))
        edges.append(
            GraphEdge(
                from_id=delivery_node_id,
                to_id=invoice_node_id,
                type=EDGE_DELIVERY_TO_INVOICE,
                label=EDGE_DELIVERY_TO_INVOICE,
                data={
                    "invoice_item_count": stats["count"],
                    "delivery_item_references": sorted(stats["delivery_item_refs"])[:10],
                },
            )
        )

    # Invoice -> Payment (via accountingDocument match)
    for invoice_node_id, acc_doc in invoice_accounting_doc.items():
        if not acc_doc:
            continue
        pay_node_ids = payments_by_invoice_accounting_doc.get(acc_doc, [])
        for pay_node_id in pay_node_ids:
            key = (invoice_node_id, pay_node_id)
            if key in seen_invoice_payment:
                continue
            seen_invoice_payment.add(key)
            edges.append(
                GraphEdge(
                    from_id=invoice_node_id,
                    to_id=pay_node_id,
                    type=EDGE_INVOICE_TO_PAYMENT,
                    label=EDGE_INVOICE_TO_PAYMENT,
                    data={"accounting_document": acc_doc},
                )
            )

    # Order -> Product (via sales_order_items.material)
    order_item_to_product_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in _iter_jsonl_records(order_items_dir):
        order_ref = _norm_str(r.get("salesOrder"))
        order_item_id = _norm_str(r.get("salesOrderItem"))
        product_id = _norm_str(r.get("material"))
        if not (order_ref and order_item_id and product_id):
            continue
        order_node_id = _node_id(NODE_ORDER, order_ref)
        product_node_id = _node_id(NODE_PRODUCT, product_id)
        if order_node_id not in orders or product_node_id not in products:
            continue
        key = (order_node_id, order_item_id, product_node_id)
        if key in order_item_to_product_stats:
            continue
        order_item_to_product_stats[key] = {
            "order_item_id": order_item_id,
            "product_id": product_id,
            "requested_quantity": _norm_str(r.get("requestedQuantity")),
            "requested_quantity_unit": _norm_str(r.get("requestedQuantityUnit")),
            "net_amount": _norm_str(r.get("netAmount")),
        }

    for (order_node_id, order_item_id, product_node_id), meta in order_item_to_product_stats.items():
        if (order_node_id, order_item_id, product_node_id) in seen_order_product_item:
            continue
        seen_order_product_item.add((order_node_id, order_item_id, product_node_id))

        # Keep the visualization simple but structured:
        # show the exact order item id and the target product id.
        # Append quantity only when available to avoid clutter.
        qty = meta.get("requested_quantity")
        unit = meta.get("requested_quantity_unit")
        qty_part = ""
        if qty and unit:
            qty_part = f" ({qty} {unit})"
        edge_label = f"Item {order_item_id} -> {meta.get('product_id')}{qty_part}"

        edges.append(
            GraphEdge(
                from_id=order_node_id,
                to_id=product_node_id,
                type=EDGE_ORDER_TO_PRODUCT,
                label=edge_label,
                data={
                    "order_item_id": meta["order_item_id"],
                    "product_id": meta["product_id"],
                    "requested_quantity": meta.get("requested_quantity"),
                    "requested_quantity_unit": meta.get("requested_quantity_unit"),
                    "net_amount": meta.get("net_amount"),
                },
            )
        )

    nodes: list[GraphNode] = []
    nodes.extend(customers.values())
    nodes.extend(products.values())
    nodes.extend(orders.values())
    nodes.extend(deliveries.values())
    nodes.extend(invoices.values())
    nodes.extend(payments.values())

    snapshot = GraphSnapshot(nodes=nodes, edges=edges)
    return snapshot, sources

