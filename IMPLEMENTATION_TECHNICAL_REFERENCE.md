# Implementation Technical Reference

## Architecture Overview

### Problem Domain
- **Input:** Natural language question about billing document flow
- **Processing:** Parse NL → Extract invoice_id → Traverse graph path
- **Output:** Structured path with node IDs, edges, and per-step status

### System Layers

```
┌─────────────────────────────────────────────┐
│  User Query (Natural Language)              │
│  "Trace full flow of billing document INV123"
└────────────────┬────────────────────────────┘
                 │
┌─────────────────▼────────────────────────────┐
│  NL Mapping (gemini.py)                     │
│  - Heuristic pattern detection              │
│  - Gemini LLM extraction                    │
│  - Operation selection                      │
└────────┬───────────────────────────────────┬─┘
         │                                   │
    ✓ Fallback (Heuristic)    API (Gemini)  │
         │                                   │
└────────▼───────────────────────────────────▼─┐
│  StructuredGraphQuery (schemas.py)         │
│  {                                          │
│    "operation": "trace_billing_document_flow",
│    "invoice_id": "INV-123",                │
│    ...                                      │
│  }                                          │
└────────┬────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────┐
│  Query Execution (query_service.py)        │
│  _trace_billing_document_flow(invoice_id)  │
│  - Phase 1-5 traversal                     │
│  - Error handling                          │
│  - Response formatting                     │
└────────┬────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────┐
│  GraphQueryResponse                        │
│  - Structured path with steps              │
│  - Status indicators                       │
│  - Missing steps list                      │
│  - Subgraph (nodes/edges)                  │
└─────────────────────────────────────────────┘
```

---

## Component Details

### 1. Natural Language Mapping (`gemini.py`)

#### Heuristic Pattern Detection (Fallback)
**Purpose:** Quick pattern matching without API call

**6 Patterns Included:**
```python
trace_doc_flow_patterns = [
    r"trace\s+.*\s*(?:full\s+)?flow.*(?:billing|invoice)",
    r"billing\s+document\s+flow",
    r"(?:sales\s+order|order)\s+.*delivery.*invoice.*(?:journal|payment)",
    r"trace\s+(?:a\s+)?(?:specific\s+)?(?:billing\s+)?document",
    r"document.*flow.*(?:order|delivery|invoice)",
    r"(?:full\s+)?flow.*(?:sales\s+order|order).*delivery.*invoice",
]
```

**Pattern Matching Logic:**
```python
# In generate_structured_query()
is_trace_doc_flow = any(re.search(pattern, question) for pattern in trace_doc_flow_patterns)

# Extract invoice_id from question
invoice_id = None
for match in re.finditer(r'(?:INV|invoice|billing)[_-]?(\d+|[A-Z0-9]+)', question):
    invoice_id = match.group(1)
    break

# Set operation priority
if is_trace_doc_flow and invoice_id:
    operation = "trace_billing_document_flow"
elif is_product_billing_query:
    operation = "analyze_product_billing_volume"
elif is_incomplete_query:
    operation = "find_incomplete_orders"
# ... fallback to other operations
```

**Advantages:**
- ✓ No API latency
- ✓ Deterministic
- ✓ Handles common phrasings
- ✓ Fast fallback when Gemini unavailable

#### Gemini LLM Enhancement
**Purpose:** High-accuracy NL understanding with full context

**Updated Prompt Section:**
```
"Available Operations"
- ...existing 7 operations...
- trace_billing_document_flow: Trace the complete document flow through the ERP system

Operation Selection Rules:
✓ Use trace_billing_document_flow WHEN:
  - User asks to trace specific billing document through entire flow
  - User asks for 'full flow' or 'complete path' of invoice
  - User asks "where does this invoice come from" or "where does it go"
  - Sequence requested: Order → Delivery → Invoice → Payment/Journal Entry
  
✗ Do NOT use when:
  - User asks for aggregates or volume analysis
  - User asks to find incomplete orders (use find_incomplete_orders)
  - User asks for customer or product analysis

Concept Clarification:
- "journal entry" = payments and accounting records linked to invoices
- Payments table contains AR (Accounts Receivable) components
- Each payment/journal entry links to invoice via accounting_document field
```

**Extraction Logic:**
```python
# Gemini extracts: operation, invoice_id, and parameters
# Operation priority ensures trace_doc_flow selected for "full flow" queries
# Invoice_id becomes required parameter for this operation
```

---

### 2. Query Schema (`schemas.py`)

#### StructuredGraphQuery Model

```python
class StructuredGraphQuery(BaseModel):
    operation: str = Field(
        default="keyword_graph_lookup",
        description="Operation type: "
        "trace_billing_document_flow (path trace of specific invoice), "
        "analyze_product_billing_volume, find_incomplete_orders, "
        "trace_order, trace_delivery, trace_invoice, trace_customer, "
        "keyword_graph_lookup"
    )
    order_id: Optional[str] = None
    delivery_id: Optional[str] = None
    invoice_id: Optional[str] = None  # Required for trace_billing_document_flow
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    keyword: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    # ... other fields
```

**Validation:**
- ✓ Schema validates operation is in allowed list
- ✓ Ensures required fields present (invoice_id for trace_billing_document_flow)
- ✓ Type checking on all parameters

---

### 3. Path Traversal (`query_service.py`)

#### Method: `_trace_billing_document_flow(invoice_id: str)`

**Signature:**
```python
def _trace_billing_document_flow(
    self, 
    invoice_id: str
) -> tuple[List[GraphNode], List[GraphEdge], Dict[str, Any]]:
    """
    Trace the complete flow of a specific billing document through the ERP.
    
    Path: Sales Order → Delivery → Invoice → Payment/Journal Entry
    
    Args:
        invoice_id (str): The specific invoice to trace
        
    Returns:
        tuple: (nodes, edges, debug_info)
            - nodes: List of relevant GraphNode objects (4 max: Order, Delivery, Invoice, Payment)
            - edges: List of connecting GraphEdge objects (3 max)
            - debug_info: Dict with path steps, status, missing links
    """
```

#### Phase 1: Invoice Validation
```python
# Check invoice exists in graph
if invoice_id not in self._node_by_id:
    return [], [], {
        "invoice_id": invoice_id,
        "overall_status": "FAILED",
        "error": "invoice_not_found",
        "invoice_exists": False
    }

invoice_node = self._node_by_id[invoice_id]
```

**Purpose:** Ensure starting point exists; fail fast if not

#### Phase 2: Find Incoming Delivery
```python
# Search for delivery_to_invoice edges pointing to this invoice
delivery_ids = []
for edge in self.graph.edges:
    if edge.type == "delivery_to_invoice" and edge.to_id == invoice_id:
        delivery_ids.append(edge.from_id)
        break  # Take first match

delivery_node = self._node_by_id.get(delivery_ids[0]) if delivery_ids else None
```

**Purpose:** Backward traverse to find connected delivery
**Edge Type:** `delivery_to_invoice` (Delivery → Invoice)
**Node Found:** `delivery_node` or None if missing

#### Phase 3: Find Incoming Order
```python
# Search for order_to_delivery edges pointing to this delivery
order_ids = []
if delivery_node:
    for edge in self.graph.edges:
        if edge.type == "order_to_delivery" and edge.to_id == delivery_ids[0]:
            order_ids.append(edge.from_id)
            break  # Take first match

order_node = self._node_by_id.get(order_ids[0]) if order_ids else None
```

**Purpose:** Continue backward traverse to find order
**Edge Type:** `order_to_delivery` (Order → Delivery)
**Node Found:** `order_node` or None if missing

#### Phase 4: Find Outgoing Payments
```python
# Search for invoice_to_payment edges FROM this invoice
payment_ids = []
for edge in self.graph.edges:
    if edge.type == "invoice_to_payment" and edge.from_id == invoice_id:
        payment_ids.append(edge.to_id)
        break  # Take first match

payment_node = self._node_by_id.get(payment_ids[0]) if payment_ids else None
```

**Purpose:** Forward traverse to find payments/journal entries
**Edge Type:** `invoice_to_payment` (Invoice → Payment)
**Node Found:** `payment_node` or None if missing

#### Phase 5: Build Subgraph

```python
# Collect relevant nodes
nodes = []
all_node_ids = [invoice_id]
if order_node:
    nodes.append(order_node)
    all_node_ids.append(order_ids[0])
if delivery_node:
    nodes.append(delivery_node)
    all_node_ids.append(delivery_ids[0])
nodes.append(invoice_node)  # Invoice always included
if payment_node:
    nodes.append(payment_node)
    all_node_ids.append(payment_ids[0])

# Collect relevant edges (only those connecting our nodes)
edges = []
for edge in self.graph.edges:
    if edge.from_id in all_node_ids and edge.to_id in all_node_ids:
        edges.append(edge)
```

**Purpose:** Create minimal subgraph for visualization
**Result:** 4 nodes max + 3 edges connecting them in chain

#### Phase 6: Build Debug Info

```python
# Determine overall status
all_steps_complete = (
    len(order_ids) > 0 and 
    len(delivery_ids) > 0 and 
    len(payment_ids) > 0
)

# Build path items (one per step)
path = [
    {
        "step": 1,
        "node_type": "invoice",
        "node_id": invoice_id,
        "label": f"Invoice {invoice_id}",
        "status": "FOUND ✓"
    },
    {
        "step": 2,
        "node_type": "delivery",
        "node_id": delivery_ids[0] if delivery_ids else None,
        "label": f"Delivery {delivery_ids[0]}" if delivery_ids else "MISSING",
        "status": "FOUND ✓" if delivery_ids else "MISSING ✗"
    },
    # ... order and payment steps similarly
]

# Find missing steps
missing_steps = []
if not delivery_ids:
    missing_steps.append("delivery")
if not order_ids:
    missing_steps.append("order")
if not payment_ids:
    missing_steps.append("payment/journal_entry")

debug_info = {
    "invoice_id": invoice_id,
    "overall_status": "COMPLETE ✓" if all_steps_complete else "INCOMPLETE ⚠",
    "order_found": len(order_ids) > 0,
    "delivery_found": len(delivery_ids) > 0,
    "payment_found": len(payment_ids) > 0,
    "order_id": order_ids[0] if order_ids else None,
    "delivery_id": delivery_ids[0] if delivery_ids else None,
    "payment_id": payment_ids[0] if payment_ids else None,
    "missing_steps": missing_steps,
    "path": path
}

return nodes, edges, debug_info
```

---

### 4. Response Handler (`answer_question()` method)

#### Operation Detection
```python
if query.operation == "trace_billing_document_flow":
    # Ensure invoice_id provided
    if not query.invoice_id:
        return GraphQueryResponse(
            answer="Invoice ID required for document flow tracing.",
            error="missing_parameter"
        )
```

#### Execution
```python
# Call traversal method
nodes, edges, debug_info = self._trace_billing_document_flow(query.invoice_id)

# Check for errors
if debug_info.get("error") == "invoice_not_found":
    return GraphQueryResponse(
        answer="Invoice not found in system.",
        error="invoice_not_found",
        debug_info=debug_info
    )
```

#### Response Formatting
```python
# Extract path info
order_id = debug_info.get("order_id")
delivery_id = debug_info.get("delivery_id")
payment_id = debug_info.get("payment_id")
missing = debug_info.get("missing_steps", [])

# Build answer with visual structure
answer = f"""📋 BILLING DOCUMENT FLOW TRACE
Invoice ID: {query.invoice_id}
Overall Status: {debug_info.get("overall_status")}

Document Flow Path:
──────────────────────────────────────────────────

1. INVOICE
   ID: {query.invoice_id}
   Label: Invoice {query.invoice_id}
   Status: FOUND ✓

2. DELIVERY
   ID: {delivery_id or "N/A"}
   Label: {f"Delivery {delivery_id}" if delivery_id else "MISSING"}
   Status: {"FOUND ✓" if delivery_id else "MISSING ✗"}

3. ORDER
   ID: {order_id or "N/A"}
   Label: {f"SO {order_id}" if order_id else "MISSING"}
   Status: {"FOUND ✓" if order_id else "MISSING ✗"}

4. PAYMENT/JOURNAL_ENTRY
   ID: {payment_id or "N/A"}
   Label: {f"Payment {query.invoice_id}" if payment_id else "MISSING"}
   Status: {"FOUND ✓" if payment_id else "MISSING ✗"}

──────────────────────────────────────────────────

{"✓ SUCCESS: Full document flow traced" if not missing else f"⚠ INCOMPLETE: Missing {len(missing)} step(s)"}
{("All nodes from Sales Order → Delivery → Invoice → Payment found" if not missing else "Missing: " + ", ".join(missing))}
"""

return GraphQueryResponse(
    answer=answer,
    nodes=nodes,
    edges=edges,
    debug_info=debug_info
)
```

**Key Features:**
- ✓ Structured visual format
- ✓ Per-step status indicators
- ✓ Clear missing step reporting
- ✓ Overall completion status
- ✓ Emoji indicators for quick scanning

---

## Data Flow Diagram

```
Question: "Trace full flow of INV-12345"
         │
         ▼
    Heuristic patterns match document flow?
         │ YES
         ▼
    Extract invoice_id: "12345"
         │
         ▼
    Set operation: "trace_billing_document_flow"
         ├─ (OR pass to Gemini if no match/API enabled)
         │
         ▼
    Schema validation:
    StructuredGraphQuery {
        operation: "trace_billing_document_flow",
        invoice_id: "12345"
    }
         │
         ▼
    Route to query_service._trace_billing_document_flow("12345")
         │
    ┌────┴────────────────────────────────┐
    │   Phase 1: Check invoice exists     │
    │   Phase 2: Find delivery ← invoice  │
    │   Phase 3: Find order ← delivery    │
    │   Phase 4: Find payment → invoice   │
    │   Phase 5: Build subgraph           │
    └────┬────────────────────────────────┘
         │
    Returns: (nodes, edges, debug_info)
         │
    ┌────▼─────────────────────────────────┐
    │  Format answer_question response      │
    │  - Structured path visualization      │
    │  - Per-step status (✓/✗)              │
    │  - Overall status (COMPLETE/INCOMPLETE)
    │  - Missing steps list                 │
    └────┬──────────────────────────────────┘
         │
    GraphQueryResponse {
        answer: "📋 BILLING DOCUMENT FLOW...",
        nodes: [Order, Delivery, Invoice, Payment],
        edges: [order→delivery, delivery→invoice, invoice→payment],
        debug_info: {...}
    }
         │
         ▼
    Return to user with visualization
```

---

## Error Handling Matrix

| Scenario | Input | Detection | Response | Debug Info |
|----------|-------|-----------|----------|-----------|
| Invoice not found | invoice_id="INVALID" | `_node_by_id` lookup | "Invoice not found in system" | error: "invoice_not_found" |
| No delivery | invoice_id="INV1" | Edge search returns empty | "Overall Status: INCOMPLETE ⚠" | missing_steps: ["delivery"] |
| No order | invoice_id="INV1" | Edge search returns empty | "Overall Status: INCOMPLETE ⚠" | missing_steps: ["delivery", "order"] |
| No payment | invoice_id="INV1" | Edge search returns empty | "Overall Status: INCOMPLETE ⚠" | missing_steps: ["payment"] |
| All found | invoice_id="INV1" | All phases succeed | "Overall Status: COMPLETE ✓" | missing_steps: [] |
| API disabled | query string | Heuristic fallback | Correct operation set | operation: "trace_billing_document_flow" |

---

## Edge Type Reference

```
┌─────────────────────────────────────────────────────────────┐
│ Graph Edge Types Used                                       │
├─────────────────────────────────────────────────────────────┤
│ order_to_delivery                                           │
│   From: sales_order_headers.order_id                        │
│   To: outbound_delivery_headers.delivery_id                │
│   Data: Derived from outbound_delivery_items               │
│                                                              │
│ delivery_to_invoice                                         │
│   From: outbound_delivery_headers.delivery_id              │
│   To: billing_document_headers.invoice_id                  │
│   Data: Derived from outbound_delivery_items               │
│                                                              │
│ invoice_to_payment                                          │
│   From: billing_document_headers.invoice_id                │
│   To: payments_accounts_receivable.payment_key             │
│   Data: Foreign key = accounting_document                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Considerations

**Time Complexity:**
- Edge search: O(n) where n = total edges in graph (~100K)
- Node lookup: O(1) via hash map
- Overall per query: O(n) dominated by edge traversal

**Space Complexity:**
- Subgraph: O(1) - always 4 nodes + 3 edges max

**Optimization Opportunities:**
1. Index edges by type + endpoint ID (from_id/to_id)
2. Cache frequently accessed paths
3. Pre-compute document flows at build time

---

## Testing Strategy

### Unit Tests
```python
def test_complete_document_flow():
    """All 4 steps found"""
    nodes, edges, debug = service._trace_billing_document_flow("INV-123")
    assert debug["overall_status"] == "COMPLETE ✓"
    assert len(nodes) == 4
    assert len(debug["missing_steps"]) == 0

def test_incomplete_flow_missing_delivery():
    """No delivery linked to invoice"""
    nodes, edges, debug = service._trace_billing_document_flow("INV-999")
    assert debug["overall_status"] == "INCOMPLETE ⚠"
    assert "delivery" in debug["missing_steps"]

def test_invoice_not_found():
    """Invoice doesn't exist in graph"""
    nodes, edges, debug = service._trace_billing_document_flow("INVALID")
    assert debug.get("error") == "invoice_not_found"
    assert len(nodes) == 0
```

### Integration Tests
```python
def test_nl_to_structured_query():
    """NL question → Correct operation selected"""
    question = "Trace the full flow of billing document INV-456"
    query = gemini_service.generate_structured_query(question)
    assert query.operation == "trace_billing_document_flow"
    assert query.invoice_id == "456"

def test_answer_question_full_flow():
    """Complete pipeline: NL → Query → Response"""
    question = "Trace the full flow of billing document INV-789"
    response = query_service.answer_question(question)
    assert "COMPLETE ✓" in response.answer or "INCOMPLETE ⚠" in response.answer
    assert response.nodes is not None
    assert len(response.edges) in [0, 3]
```

---

## Deployment Checklist

- ✅ Code review completed
- ✅ Unit tests pass
- ✅ Integration tests pass
- ✅ Error handling comprehensive
- ✅ Performance acceptable
- ✅ Backward compatible
- ✅ Documentation complete
- ✅ Heuristic fallback tested
- ✅ Gemini prompt updated
- ✅ Schema validation active
