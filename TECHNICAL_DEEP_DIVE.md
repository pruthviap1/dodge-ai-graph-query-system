# Product Billing Query: Technical Deep Dive

## Graph Traversal Visualization

### Data Model
```
PRODUCTS (catalog)
    ↑
    | order_to_product (many-to-many)
    |
ORDERS (sales orders)
    |
    | order_to_delivery (one-to-many)
    ↓
DELIVERIES (outbound deliveries)
    |
    | delivery_to_invoice (one-to-many)
    ↓
INVOICES (billing documents)
    |
    | invoice_to_payment (one-to-many)
    ↓
PAYMENTS (accounts receivable)

CUSTOMERS (business partners)
    |
    | customer_to_order (one-to-many)
    ↓
ORDERS (back to orders)
```

### Algorithm: Product Billing Volume

```
INPUT: Graph with nodes and edges

STEP 1: Build Reverse Index
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for each edge in graph.edges:
  if edge.type == "order_to_product":
    product_to_orders[product_id].add(order_id)
  else if edge.type == "order_to_delivery":
    order_to_deliveries[order_id].add(delivery_id)
  else if edge.type == "delivery_to_invoice":
    delivery_to_invoices[delivery_id].add(invoice_id)
    
Result: Three lookup maps for fast traversal

STEP 2: Aggregate Invoice Counts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for each (product_id, orders) in product_to_orders.items():
  invoice_set = {}
  for each order_id in orders:
    deliveries = order_to_deliveries[order_id]
    for each delivery_id in deliveries:
      invoices = delivery_to_invoices[delivery_id]
      invoice_set.union(invoices)
  
  product_invoice_counts[product_id] = len(invoice_set)
  
Result: Dictionary of product_id → invoice_count

STEP 3: Sort by Count
━━━━━━━━━━━━━━━━━━━━━
sorted_products = sort(product_invoice_counts.items())
                  by count descending
                  
Result: Products ranked by billing volume

STEP 4: Build Subgraph for Visualization
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for each top_product in sorted_products[0:5]:
  add product_node
  for each order in orders_with_invoices:
    add order_node
    add order→product edge
    for each delivery in order's deliveries:
      add delivery_node
      add order→delivery edge
      for each invoice (limit 3):
        add invoice_node
        add delivery→invoice edge
        
Result: Limited subgraph showing top products with sample flows

STEP 5: Format Output
━━━━━━━━━━━━━━━━━━━━
answer = format_answer(sorted_products)
debug_info = {
  total_products_with_billing: len(product_invoice_counts),
  highest_invoice_count: sorted_products[0].count,
  top_products: [product details for top 10]
}

OUTPUT: (nodes, edges, debug_info)
```

---

## Example Execution Trace

### Sample Graph State
```
Nodes:
├─ product:ABC-122
│  └─ label: "Premium Widget"
├─ product:XYZ-445
│  └─ label: "Standard Gadget"
├─ order:SO-100001
├─ order:SO-100002
├─ order:SO-100003
├─ delivery:DO-001
├─ delivery:DO-002
├─ delivery:DO-003
├─ invoice:INV-500
├─ invoice:INV-501
├─ invoice:INV-502
├─ invoice:INV-503
└─ payment:PAY-001

Edges:
├─ (order:SO-100001) --order_to_product--> (product:ABC-122)
├─ (order:SO-100002) --order_to_product--> (product:ABC-122)
├─ (order:SO-100003) --order_to_product--> (product:XYZ-445)
├─ (order:SO-100001) --order_to_delivery--> (delivery:DO-001)
├─ (order:SO-100002) --order_to_delivery--> (delivery:DO-002)
├─ (order:SO-100003) --order_to_delivery--> (delivery:DO-003)
├─ (delivery:DO-001) --delivery_to_invoice--> (invoice:INV-500)
├─ (delivery:DO-001) --delivery_to_invoice--> (invoice:INV-501)
├─ (delivery:DO-002) --delivery_to_invoice--> (invoice:INV-502)
├─ (delivery:DO-003) --delivery_to_invoice--> (invoice:INV-503)
└─ (invoice:INV-500) --invoice_to_payment--> (payment:PAY-001)
```

### Execution Steps

**Phase 1: Build Index**
```
product_to_orders = {
  "product:ABC-122": {"order:SO-100001", "order:SO-100002"},
  "product:XYZ-445": {"order:SO-100003"}
}

order_to_deliveries = {
  "order:SO-100001": {"delivery:DO-001"},
  "order:SO-100002": {"delivery:DO-002"},
  "order:SO-100003": {"delivery:DO-003"}
}

delivery_to_invoices = {
  "delivery:DO-001": {"invoice:INV-500", "invoice:INV-501"},
  "delivery:DO-002": {"invoice:INV-502"},
  "delivery:DO-003": {"invoice:INV-503"}
}
```

**Phase 2: Aggregate**
```
For product:ABC-122:
  orders = {order:SO-100001, order:SO-100002}
  
  For order:SO-100001:
    deliveries = {delivery:DO-001}
    invoices = {invoice:INV-500, invoice:INV-501}
    invoice_set.update() → {invoice:INV-500, invoice:INV-501}
  
  For order:SO-100002:
    deliveries = {delivery:DO-002}
    invoices = {invoice:INV-502}
    invoice_set.update() → {invoice:INV-500, invoice:INV-501, invoice:INV-502}
  
  Result: product:ABC-122 has 3 invoices ✓

For product:XYZ-445:
  orders = {order:SO-100003}
  
  For order:SO-100003:
    deliveries = {delivery:DO-003}
    invoices = {invoice:INV-503}
    invoice_set.update() → {invoice:INV-503}
  
  Result: product:XYZ-445 has 1 invoice ✓
```

**Phase 3: Sort**
```
sorted_products = [
  (product:ABC-122, count=3),
  (product:XYZ-445, count=1)
]
```

**Phase 4: Return**
```
Answer:
"Product Billing Volume Analysis:
Total products with billing documents: 2

🏆 Highest: 'Premium Widget' with 3 billing documents

Top products by invoice count:
1. Product: Premium Widget
   Billing Documents (Invoices): 3
   Associated Orders: 2

2. Product: Standard Gadget
   Billing Documents (Invoices): 1
   Associated Orders: 1"
```

---

## Query Classification Flow

```
User Input
    ↓
_looks_like_domain_question() ?
    ├─ NO → REJECT (not supply chain related)
    └─ YES ↓
        
Is operation already set by NL mapper?
    ├─ trace_order ✓
    ├─ trace_delivery ✓
    ├─ trace_invoice ✓
    ├─ trace_customer ✓
    ├─ find_incomplete_orders ✓
    ├─ analyze_product_billing_volume → ✓✓✓
    └─ keyword_graph_lookup (fallback)
    
For analyze_product_billing_volume:
    ├─ Call _analyze_product_billing_volume()
    ├─ Format specialized answer
    ├─ Return product rankings with invoice counts
    └─ Include subgraph visualization
```

---

## Natural Language Mapping Examples

### Query → Operation Mapping

| Query | Detected By | Operation |
|-------|-------------|-----------|
| "Which products have the most invoices?" | Gemini + Heuristic | `analyze_product_billing_volume` |
| "Products with highest billing volume?" | Heuristic patterns | `analyze_product_billing_volume` |
| "Top 10 products by billing documents" | Gemini | `analyze_product_billing_volume` |
| "Which products are associated with the highest number of billing documents?" | Gemini + Heuristic | `analyze_product_billing_volume` |
| "Show me incomplete orders" | Heuristic | `find_incomplete_orders` |
| "Trace order 100001" | Heuristic (order_id) | `trace_order` |
| "Find products with keyword" | Heuristic | `keyword_graph_lookup` |

### Heuristic Patterns

```python
# Product Billing Patterns (Highest Priority)
r"products?\s+.*\s*(?:highest|most|most\s+number|associated)\s+.*billing",
r"billing\s+(?:documents?|invoices?)\s+.*\s+products?",
r"which\s+products?\s+.*\s+(?:billing|invoice)",
r"product.*count.*(?:billing|invoice)",
r"(?:billing|invoice).*count.*products?",
r"top\s+products?.*(?:billing|invoice)",
r"highest\s+(?:billing|invoice).*products?",

# These get higher priority than simple keyword matching
# But lower than specific ID extraction
```

---

## Error Handling & Edge Cases

### Case 1: No Invoices Found
```
Condition: Graph has products and orders, but no invoices
Action: Return empty nodes/edges with NO_DATA message
Message: "No billing data available. No products have associated invoices."
```

### Case 2: No Orders for Product
```
Condition: Product exists but no order_to_product edges
Action: Skip product from analysis (doesn't appear in results)
Result: Product list is smaller than node count
```

### Case 3: Orders Without Deliveries
```
Condition: Order exists but no order_to_delivery edges
Action: Continue to next order (skip this one)
Note: Doesn't affect final product count (order had no associated invoices)
```

### Case 4: Deliveries Without Invoices
```
Condition: Delivery exists but no delivery_to_invoice edges
Action: Invoice count remains 0 for that path
Note: Product still counted if it has other invoices from other deliveries
```

### Case 5: Empty Graph
```
Condition: Graph not built or has 0 nodes
Action: Return "no_graph" reason in debug
Message: "No billing data available. Make sure graph has been built."
```

---

## Performance Metrics

### Scenario: 10,000 products, 50,000 orders, 100,000 deliveries, 150,000 invoices

```
Phase 1 (Indexing):       O(n) ≈ 300,000 edges × 1 lookup ≈ 300ms
Phase 2 (Aggregation):    O(p × o/p × d/o × i/d) ≈ 10,000 products ≈ 500ms
Phase 3 (Sorting):        O(p log p) ≈ 10,000 × 14 ≈ 50ms
Phase 4 (Subgraph):       Fixed cost (top 5 products × samples) ≈ 100ms
Phase 5 (Formatting):     O(n') ≈ response nodes ≈ 50ms

TOTAL TIME:               ~1000ms (1 second) ✓
RESULT SIZE:              ~200 nodes, ~2000 edges ✓
```

---

## Testing Queries

### Happy Path Tests
```json
{
  "question": "Which products are associated with the highest number of billing documents?"
}
```
Expected: Top products ranked by invoice count, Invoices > 0

```json
{
  "question": "What products have the most invoices?"
}
```
Expected: Same as above, shows rankings

### Edge Case Tests
```json
{
  "question": "Which products have billing documents?"
}
```
Expected: Works if data exists, "No billing data available" if not

### Negative Tests (Should NOT trigger analyze_product_billing_volume)
```json
{
  "question": "Show me this product"
}
```
Expected: Uses keyword_graph_lookup

```json
{
  "question": "Trace order 100001"
}
```
Expected: Uses trace_order operation
