# API Testing Reference: Product Billing Query Fix

## Quick Start

### Test the Fix

```bash
# 1. Start/Verify Backend is Running
curl http://localhost:8000/health

# Expected: {"status":"ok"}

# 2. Build Graph (if not already built)
curl -X POST http://localhost:8000/api/graph/build

# Expected: 
# {
#   "ok": true,
#   "node_count": 12345,
#   "edge_count": 45000,
#   "sources": ["sales_order_headers", "billing_document_headers", ...]
# }

# 3. Run the Query
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which products are associated with the highest number of billing documents?"
  }'
```

---

## Expected Response Format

### Success Response (200)

```json
{
  "answer": "Product Billing Volume Analysis:\nTotal products with billing documents: 47\n\n🏆 Highest: 'Product ABC-122' with 156 billing documents\n\nTop products by invoice count:\n1. Product: ABC-122\n   Billing Documents (Invoices): 156\n   Associated Orders: 89\n\n2. Product: XYZ-445\n   Billing Documents (Invoices): 143\n   Associated Orders: 76\n",
  "structured_query": {
    "operation": "analyze_product_billing_volume",
    "customer_id": null,
    "order_id": null,
    "delivery_id": null,
    "invoice_id": null,
    "accounting_document": null,
    "product_id": null,
    "entity_types": [],
    "keywords": ["products", "associated", "highest", "number", "billing", "documents"],
    "limit": 200,
    "max_hops": 2
  },
  "graph": {
    "nodes": [
      {
        "id": "product:ABC-122",
        "type": "product",
        "label": "Product ABC-122",
        "data": {"product_id": "ABC-122", "description": "Premium Widget", "search_text": "abc-122 premium widget"}
      },
      {
        "id": "order:SO-100001",
        "type": "order",
        "label": "SO SO-100001",
        "data": {"order_id": "SO-100001", "customer_id": "CUST-001", "total_net_amount": "1500.00"}
      },
      {
        "id": "delivery:DO-001",
        "type": "delivery",
        "label": "Delivery DO-001",
        "data": {"delivery_id": "DO-001"}
      },
      {
        "id": "invoice:INV-500",
        "type": "invoice",
        "label": "Invoice INV-500",
        "data": {"invoice_id": "INV-500", "total_net_amount": "1500.00"}
      }
    ],
    "edges": [
      {
        "from_id": "order:SO-100001",
        "to_id": "product:ABC-122",
        "type": "order_to_product",
        "label": "Item SO-001 -> ABC-122 (10 EA)",
        "data": {"order_item_id": "SO-001", "requested_quantity": "10", "requested_quantity_unit": "EA"}
      },
      {
        "from_id": "order:SO-100001",
        "to_id": "delivery:DO-001",
        "type": "order_to_delivery",
        "label": "order_to_delivery",
        "data": {"delivery_item_count": 1}
      },
      {
        "from_id": "delivery:DO-001",
        "to_id": "invoice:INV-500",
        "type": "delivery_to_invoice",
        "label": "delivery_to_invoice",
        "data": {"invoice_item_count": 1}
      }
    ]
  },
  "debug": {
    "gemini_raw": null,
    "total_products_with_billing": 47,
    "highest_invoice_count": 156,
    "highest_product_id": "product:ABC-122",
    "top_products": [
      {
        "product_node_id": "product:ABC-122",
        "product_name": "Product ABC-122",
        "invoice_count": 156,
        "orders_count": 89,
        "top_invoices": ["invoice:INV-500", "invoice:INV-501", "invoice:INV-502"]
      },
      {
        "product_node_id": "product:XYZ-445",
        "product_name": "Product XYZ-445",
        "invoice_count": 143,
        "orders_count": 76,
        "top_invoices": ["invoice:INV-600", "invoice:INV-601"]
      }
    ]
  }
}
```

### Key Validations

✅ **answer** contains:
- "Product Billing Volume Analysis:"
- Product counts (not 0)
- "🏆 Highest:" shows top product
- Invoice counts > 0
- Multiple products listed (if data exists)

✅ **structured_query.operation** = `"analyze_product_billing_volume"`

✅ **graph.nodes** contains:
- At least one product node
- At least one order node (not 0)
- At least one delivery node (not 0)
- **At least one invoice node** (this was the bug!)

✅ **debug.total_products_with_billing** > 0

---

## Query Variations to Test

### All These Should Work Now

```bash
# Variation 1
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most billing documents?"}'

# Variation 2
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Top products by invoice count"}'

# Variation 3
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Products with highest billing volume"}'

# Variation 4
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me which products are associated with the highest number of billing documents"}'

# Variation 5 (Alternative term for invoices)
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most invoices?"}'

# Variation 6 (Ranking query)
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Rank products by their billing document count"}'
```

---

## Before/After Comparison

### BEFORE (Bug)
```
Customers: 0
Orders: 0
Deliveries: 0
Invoices: 0         ← BUG! Should be > 0
Payments: 0
Products: 1
```

**Why it failed:**
- Used keyword matching only
- Didn't traverse Order → Delivery → Invoice
- "billing documents" not recognized

---

### AFTER (Fixed)
```
Product Billing Volume Analysis:
Total products with billing documents: 47

🏆 Highest: 'ABC-122' with 156 billing documents

Top products by invoice count:
1. Product: ABC-122
   Billing Documents (Invoices): 156      ← NOW POPULATED!
   Associated Orders: 89

2. Product: XYZ-445
   Billing Documents (Invoices): 143      ← CORRECT!
   Associated Orders: 76
```

---

## Debugging Checklist

### If Response Shows "No billing data available":

- [ ] Graph has been built? `GET /api/graph/build`
- [ ] Data files exist in `data/` directory?
  - [ ] `billing_document_headers/` (invoices exist)
  - [ ] `billing_document_items/` (invoice items exist)
  - [ ] `sales_order_items/` (orders reference products)
  - [ ] `outbound_delivery_items/` (deliveries reference orders)
- [ ] Verify relationships via debug info:
  ```json
  "debug": {
    "total_products_with_billing": 0,
    "highest_invoice_count": 0
  }
  ```

### If Response Shows Wrong Product (Not the Highest):

- [ ] Check debug info for `top_products` list
- [ ] Verify invoice counts in debug info
- [ ] Confirm answer is sorted descending

### If Invoices: 0 Still Shows:

- [ ] Verify operation is `"analyze_product_billing_volume"` (not keyword_graph_lookup)
- [ ] Check that `delivery_to_invoice` edges exist
- [ ] Verify billing_document_headers JSONL files are loaded

---

## Performance Testing

### Query 1000 Times in Sequence
```bash
#!/bin/bash
for i in {1..1000}; do
  curl -s -X POST http://localhost:8000/api/query \
    -H "Content-Type: application/json" \
    -d '{"question": "Which products have the most billing documents?"}' \
    | jq -r '.debug.highest_invoice_count'
done
```
**Expected:** All responses complete in < 2 seconds total (1-2ms per query after cache warmup)

### Large Graph Test
```bash
# Monitor response time
time curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most billing documents?"}'
```
**Expected:** < 1 second for graphs with 10K+ products

---

## Response Code Reference

| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success with data | Products ranked by billing volume |
| 200 | Success, no data | "No billing data available" |
| 200 | Query not recognized | Falls back to keyword lookup |
| 400 | Invalid JSON | Malformed request body |
| 500 | Server error | Unhandled exception in analysis |

---

## Sample cURL Commands

### Minimal Request
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most invoices?"}'
```

### With Options
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which products are associated with the highest number of billing documents?",
    "limit": 300,
    "max_hops": 3
  }'
```

### Save to File
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most billing documents?"}' \
  | jq '.' > response.json
```

### Extract Just Answers
```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products have the most billing documents?"}' \
  | jq -r '.answer'
```

---

## Verification Checklist

After deploying the fix, verify these assertions:

- [ ] Query "Which products have the most invoices?" returns > 0 invoices
- [ ] Operation is detected as `analyze_product_billing_volume`
- [ ] Top product has highest invoice count
- [ ] Answer includes emoji (🏆) and product names
- [ ] Graph returned has actual nodes and edges (not empty)
- [ ] Multiple products shown if data allows
- [ ] "No billing data available" only when appropriate
- [ ] Response time < 1 second
- [ ] Debug info has non-zero `highest_invoice_count`
- [ ] Subgraph includes order→delivery→invoice chains
