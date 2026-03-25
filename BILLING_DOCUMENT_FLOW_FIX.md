# ERP Graph Query: Billing Document Flow Tracing Fix

## Problem Summary

**Original Issue:**  
Query: "Trace the full flow of a given billing document (Sales Order → Delivery → Billing → Journal Entry)"

**Incorrect Behavior:**
- Returned aggregated counts instead of a single document's path
- Example output: "Customers: 0, Orders: 0, Deliveries: 86, Invoices: 163, Payments: ..."
- Showed multiple unrelated records instead of connected chain
- Used simple `keyword_graph_lookup` operation

**Root Causes:**
1. ❌ No path-tracing operation for specific billing documents
2. ❌ System treated document flow as aggregation query
3. ❌ Invoice ID not extracted or prioritized from query
4. ❌ No structured per-step error reporting for missing links

---

## Solution Overview

### 1. New Operation: `trace_billing_document_flow`

**What it does:**
- Takes a specific Invoice ID as input
- Traces BACKWARD to find the connected Order and Delivery
- Traces FORWARD to find related Payments/Journal Entries
- Returns a LINEAR PATH (not aggregation)
- Explicitly indicates status of each step
- Reports which links are missing (if any)

### 2. Path Traversal Logic

```
BACKWARD CHAIN (Incoming edges):
┌─────────────────────────────────────┐
│  Sales Order                        │
│  (trace_order_id)                   │
└──────┬──────────────────────────────┘
       │ [order_to_delivery edge]
       ↓
┌─────────────────────────────────────┐
│  Delivery                           │
│  (found via edge search)            │
└──────┬──────────────────────────────┘
       │ [delivery_to_invoice edge]
       ↓
┌─────────────────────────────────────┐
│  Invoice (INPUT - Starting Point)   │
│  (invoice:ID)                       │
└──────┬──────────────────────────────┘

FORWARD CHAIN (Outgoing edges):
       │ [invoice_to_payment edge]
       ↓
┌─────────────────────────────────────┐
│  Payment / Journal Entry            │
│  (linked via accounting_document)   │
└─────────────────────────────────────┘
```

### 3. Per-Step Status Reporting

Each step in the path includes:
- **Step number** (1-4)
- **Node type** (Order, Delivery, Invoice, Payment)
- **Node ID** (specific record identifier)
- **Node label** (human-readable description)
- **Edge type** (how it connects)
- **Status** (FOUND ✓ or MISSING ✗)

### 4. Error Handling

**Missing Step Scenarios:**
- ❌ Invoice not found → "Invoice not found in graph" (return empty)
- ❌ Delivery not linked → "No delivery linked to this invoice"
- ❌ Order not linked → "No order linked to delivery"  
- ❌ Payment not linked → "No payment/journal entry linked to invoice"

**Edge Cases:**
- Multiple deliveries per invoice → Show count, take first
- Multiple payments per invoice → Show count, take first
- All steps present → Mark as "COMPLETE ✓"
- Some steps missing → Mark as "INCOMPLETE ⚠" with missing list

---

## Code Changes

### File 1: `schemas.py`
✅ Added `trace_billing_document_flow` to operation description

### File 2: `query_service.py`

**New Method:** `_trace_billing_document_flow(invoice_id: str)`
- **Parameters:** invoice_id (string)
- **Returns:** (nodes, edges, debug_info)
- **Logic:**
  ```
  1. Validate invoice exists in graph
  2. Search for Delivery → Invoice edges (incoming)
  3. Search for Order → Delivery edges (incoming)
  4. Search for Invoice → Payment edges (outgoing)
  5. Build minimal subgraph with these 4 nodes + 3 edges
  6. Return structured path with status per step
  7. Flag overall: COMPLETE or INCOMPLETE + what's missing
  ```

**Handler in `answer_question()`:**
- Detects operation: `trace_billing_document_flow`
- Calls analysis method
- Formats human-readable response with:
  - 📋 Document flow visualization
  - Invoice ID and overall status
  - Step-by-step path with IDs and labels
  - ✓/✗ indicators per step
  - Clear summary (Complete/Incomplete)
  - List of missing steps if any

### File 3: `gemini.py`

**Enhanced `generate_structured_query()`:**
- Added pattern detection for document flow queries
- Patterns include:
  ```python
  r"trace\s+.*\s*(?:full\s+)?flow.*(?:billing|invoice)",
  r"billing\s+document\s+flow",
  r"(?:sales\s+order|order)\s+.*delivery.*invoice.*(?:journal|payment)",
  r"trace\s+(?:a\s+)?(?:specific\s+)?(?:billing\s+)?document",
  r"document.*flow.*(?:order|delivery|invoice)",
  r"(?:full\s+)?flow.*(?:sales\s+order|order).*delivery.*invoice",
  ```
- Operation priority: `trace_billing_document_flow` (if invoice ID found) > product_billing > incomplete > others

**Enhanced Gemini Prompt:**
- Documents new `trace_billing_document_flow` operation
- Explains when to use it (full flow, specific document path tracing)
- Clarifies that journal entries = payments/accounting records
- Updates operation list in Gemini's available options

---

## Expected Output

### Query: "Trace the full flow of a given billing document (Sales Order → Delivery → Billing → Journal Entry) for invoice INV-123456"

**Correct Output (Production-Ready):**
```
📋 BILLING DOCUMENT FLOW TRACE
Invoice ID: INV-123456
Overall Status: COMPLETE ✓

Document Flow Path:
──────────────────────────────────────────────────

1. INVOICE
   ID: INV-123456
   Label: Invoice INV-123456
   Status: FOUND ✓

2. DELIVERY
   ID: DO-456789
   Label: Delivery DO-456789
   Status: FOUND ✓ (1 delivery(ies))

3. ORDER
   ID: SO-123456
   Label: SO SO-123456
   Status: FOUND ✓ (1 order(s))

4. PAYMENT/JOURNAL_ENTRY
   ID: payment_key_001
   Label: Payment INV-123456 (item 01)
   Status: FOUND ✓ (1 payment(s)/journal entry(ies))

──────────────────────────────────────────────────

✓ SUCCESS: Full document flow traced
All nodes from Sales Order → Delivery → Invoice → Payment found
```

### Debug Info:
```json
{
  "invoice_id": "INV-123456",
  "overall_status": "COMPLETE ✓",
  "order_found": true,
  "delivery_found": true,
  "payment_found": true,
  "order_id": "SO-123456",
  "delivery_id": "DO-456789",
  "payment_id": "payment_key_001",
  "missing_steps": [],
  "path": [
    {
      "step": 1,
      "node_type": "invoice",
      "node_id": "INV-123456",
      "status": "FOUND ✓"
    },
    {
      "step": 2,
      "node_type": "delivery",
      "node_id": "DO-456789",
      "status": "FOUND ✓ (1 delivery(ies))"
    },
    {
      "step": 3,
      "node_type": "order",
      "node_id": "SO-123456",
      "status": "FOUND ✓ (1 order(s))"
    },
    {
      "step": 4,
      "node_type": "payment/journal_entry",
      "node_id": "payment_key_001",
      "status": "FOUND ✓ (1 payment(s)/journal entry(ies))"
    }
  ]
}
```

### Subgraph Visualization:
- **Nodes:** Invoice, Delivery, Order, Payment (4 nodes)
- **Edges:** Order→Delivery, Delivery→Invoice, Invoice→Payment (3 edges)
- Pure chain visualization, no extraneous connections

---

## Example: Incomplete Path

### Query: "Trace invoice INV-999999"

**Output when Delivery is missing:**
```
📋 BILLING DOCUMENT FLOW TRACE
Invoice ID: INV-999999
Overall Status: INCOMPLETE ⚠ (Missing links)

Document Flow Path:
──────────────────────────────────────────────────

1. INVOICE
   ID: INV-999999
   Label: Invoice INV-999999
   Status: FOUND ✓

2. DELIVERY
   Status: MISSING ✗ - No delivery linked to this invoice

3. ORDER
   Status: MISSING ✗ - No order linked to delivery

4. PAYMENT/JOURNAL_ENTRY
   ID: PAY-111
   Label: Payment INV-999999 (item 01)
   Status: FOUND ✓ (1 payment(s)/journal entry(ies))

──────────────────────────────────────────────────

⚠ INCOMPLETE: Missing 2 step(s)
  • DELIVERY
  • ORDER
```

---

## Key Improvements vs Original

| Aspect | Before | After |
|--------|--------|-------|
| **Query type** | Aggregation (counts) | Path tracing (single document) |
| **Output format** | Multiple unrelated counts | Structured 4-step path |
| **Relationship handling** | Lists all/many nodes | Only connected chain |
| **Error reporting** | Generic "Not found" | Per-step status with clear reasons |
| **Missing links** | No indication | Explicitly listed |
| **Invoice required** | No, falls back to keywords | Yes, must extract/provide |
| **Response structure** | Flat summary | Hierarchical path with steps |

---

## Graph Schema Requirements

### Node Types Used ✅
```
✓ Order (sales_order_headers)
✓ Delivery (outbound_delivery_headers)
✓ Invoice (billing_document_headers)
✓ Payment (payments_accounts_receivable) - represents journal entry
```

### Edge Types Used ✅
```
✓ order_to_delivery: Order → Delivery
✓ delivery_to_invoice: Delivery → Invoice
✓ invoice_to_payment: Invoice → Payment (via accounting_document)
```

### Data Used ✅
```
✓ sales_order_headers (order_id, currency, customer)
✓ sales_order_items (order_to_product links)
✓ outbound_delivery_headers (delivery_id)
✓ outbound_delivery_items (delivery→invoice references)
✓ billing_document_headers (invoice_id, accounting_document)
✓ billing_document_items (invoice items detail)
✓ payments_accounts_receivable (payment records, linked to invoice via accounting_document)
```

---

## Implementation Quality Checklist

- ✅ Path tracing instead of aggregation
- ✅ Specific billing document (invoice) tracing
- ✅ Traverses: Order → Delivery → Invoice → Payment
- ✅ Returns structured path with step numbers
- ✅ Clear per-step status indicators
- ✅ Error handling for missing relationships
- ✅ Explicit indication of which steps are missing
- ✅ Overall completion status
- ✅ Subgraph returned for visualization
- ✅ Production-ready format
- ✅ Natural language query detection enhanced
- ✅ Gemini prompt updated
- ✅ No aggregation/counts in response
- ✅ No multiple unrelated records shown
- ✅ Linear path visualization only

---

## Next Steps (Optional Enhancements)

1. **Journal Entry Nodes:** Load actual journal_entry_items_accounts_receivable records as separate nodes
2. **Multiple Paths:** Show all orders/deliveries/payments (not just first) if multiple exist
3. **Document Status:** Query invoice status (paid/unpaid/cancelled)
4. **Timeline:** Add dates for each step (order date, delivery date, invoice date, payment date)
5. **Drill-down:** From any step, allow drilling down to that node's details
6. **History:** Track document flow modifications over time
7. **Reverse Trace:** Start from payment and trace backward to order

---

## Files Modified

1. `backend/app/schemas.py` - Operation schema
2. `backend/app/query_service.py` - Main implementation (~180 lines)
3. `backend/app/gemini.py` - NL detection (~100 lines)

**Total Production Code:** ~300 lines
