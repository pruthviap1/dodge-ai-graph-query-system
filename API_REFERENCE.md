# API Reference: Billing Document Flow Tracing

## Quick Start

### User Query
```
"Trace the full flow of billing document INV-12345"
```

### Expected Response
```json
{
  "answer": "📋 BILLING DOCUMENT FLOW TRACE\nInvoice ID: INV-12345\nOverall Status: COMPLETE ✓\n\nDocument Flow Path:\n...",
  "nodes": [
    {"id": "INV-12345", "type": "invoice", "label": "Invoice INV-12345"},
    {"id": "DO-789", "type": "delivery", "label": "Delivery DO-789"},
    {"id": "SO-456", "type": "order", "label": "SO SO-456"},
    {"id": "PAY-001", "type": "payment", "label": "Payment INV-12345"}
  ],
  "edges": [
    {"from_id": "SO-456", "to_id": "DO-789", "type": "order_to_delivery"},
    {"from_id": "DO-789", "to_id": "INV-12345", "type": "delivery_to_invoice"},
    {"from_id": "INV-12345", "to_id": "PAY-001", "type": "invoice_to_payment"}
  ],
  "debug_info": {
    "invoice_id": "INV-12345",
    "overall_status": "COMPLETE ✓",
    "order_found": true,
    "delivery_found": true,
    "payment_found": true,
    "order_id": "SO-456",
    "delivery_id": "DO-789",
    "payment_id": "PAY-001",
    "missing_steps": [],
    "path": [...]
  }
}
```

---

## Module: `backend/app/gemini.py`

### Function: `generate_structured_query()`

#### Signature
```python
def generate_structured_query(question: str) -> StructuredGraphQuery:
```

#### Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | str | Yes | Natural language query from user |

#### Returns
```python
StructuredGraphQuery(
    operation: str,           # e.g., "trace_billing_document_flow"
    invoice_id: Optional[str],
    order_id: Optional[str],
    # ... other fields
)
```

#### Processing Flow
1. **Heuristic Detection (≈200ms, no API)**
   ```python
   is_trace_doc_flow = any(
       re.search(pattern, question) 
       for pattern in trace_doc_flow_patterns
   )
   ```
   - 6 patterns check for document flow keywords
   - Extracts invoice_id via regex

2. **Operation Selection**
   ```python
   if is_trace_doc_flow and invoice_id:
       operation = "trace_billing_document_flow"
   elif is_product_billing:
       operation = "analyze_product_billing_volume"
   # ... etc
   ```

3. **Gemini Fallback** (if enabled, ≈2-5s)
   - Sends question + prompt to Gemini API
   - Returns operation + parameters
   - May override heuristic result

#### Example Usage
```python
# Scenario 1: Heuristic match
question = "Trace the full flow of billing document INV-456"
query = gemini_service.generate_structured_query(question)
# Returns:
# StructuredGraphQuery(
#     operation="trace_billing_document_flow",
#     invoice_id="456"
# )

# Scenario 2: No match
question = "What are sales for customers in Berlin?"
query = gemini_service.generate_structured_query(question)
# Returns:
# StructuredGraphQuery(
#     operation="keyword_graph_lookup",
#     keyword="Berlin customer sales"
# )
```

#### Error Handling
- Malformed question → Falls back to keyword_graph_lookup
- Invalid invoice_id format → Extracted as string, validated later
- Gemini API error → Uses heuristic result

#### Implementation Location
[backend/app/gemini.py](backend/app/gemini.py#L80-L150) (approx)

---

## Module: `backend/app/schemas.py`

### Class: `StructuredGraphQuery`

#### Definition
```python
class StructuredGraphQuery(BaseModel):
    operation: str = Field(
        default="keyword_graph_lookup",
        description="Operation: trace_billing_document_flow, "
                    "analyze_product_billing_volume, find_incomplete_orders, "
                    "trace_order, trace_delivery, trace_invoice, trace_customer, "
                    "keyword_graph_lookup"
    )
    invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    delivery_id: Optional[str] = None
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    keyword: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
```

#### Field Details
| Field | Type | Default | For Operation | Notes |
|-------|------|---------|---------------|-------|
| `operation` | str | "keyword_graph_lookup" | All | Required |
| `invoice_id` | Optional[str] | None | trace_billing_document_flow | Required for trace_doc_flow |
| `order_id` | Optional[str] | None | trace_order | - |
| `delivery_id` | Optional[str] | None | trace_delivery | - |
| `customer_id` | Optional[str] | None | trace_customer | - |
| `product_id` | Optional[str] | None | analyze_product_billing_volume | - |
| `keyword` | Optional[str] | None | keyword_graph_lookup | - |

#### Validation
```python
# Auto-validated by Pydantic:
- Operation must be in allowed list
- invoice_id is string or None
- No required fields checked at schema level
  (validation happens in query_service.py)
```

#### Usage
```python
# Create query object
query = StructuredGraphQuery(
    operation="trace_billing_document_flow",
    invoice_id="INV-12345"
)

# Validate
query.model_validate({
    "operation": "trace_billing_document_flow",
    "invoice_id": "INV-12345"
})

# Convert to dict
query.model_dump()
```

---

## Module: `backend/app/query_service.py`

### Method: `_trace_billing_document_flow()`

#### Signature
```python
def _trace_billing_document_flow(
    self, 
    invoice_id: str
) -> tuple[List[GraphNode], List[GraphEdge], Dict[str, Any]]:
```

#### Parameters
| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `invoice_id` | str | Yes | Invoice identifier | "INV-12345" |

#### Returns

**Tuple Structure:** `(nodes, edges, debug_info)`

##### 1. Nodes (List[GraphNode])

```python
# Example: 4 nodes (max)
[
    GraphNode(
        id="SO-456",
        type="order",
        label="SO SO-456",
        # ... additional properties from graph
    ),
    GraphNode(
        id="DO-789",
        type="delivery",
        label="Delivery DO-789",
    ),
    GraphNode(
        id="INV-12345",
        type="invoice",
        label="Invoice INV-12345",
    ),
    GraphNode(
        id="PAY-001",
        type="payment",
        label="Payment INV-12345 (item 01)",
    )
]
```

**Properties:**
- `id`: Unique identifier in graph
- `type`: Node type (order, delivery, invoice, payment)
- `label`: Human-readable label
- May contain additional graph properties (customer, amount, date, etc.)

##### 2. Edges (List[GraphEdge])

```python
# Example: 3 edges (max)
[
    GraphEdge(
        from_id="SO-456",
        to_id="DO-789",
        type="order_to_delivery",
        # ... metadata
    ),
    GraphEdge(
        from_id="DO-789",
        to_id="INV-12345",
        type="delivery_to_invoice",
    ),
    GraphEdge(
        from_id="INV-12345",
        to_id="PAY-001",
        type="invoice_to_payment",
    )
]
```

**Properties:**
- `from_id`: Source node ID
- `to_id`: Target node ID
- `type`: Relationship type
- Graph edges only; always exactly 3 if all steps found, 0-2 if incomplete

##### 3. Debug Info (Dict[str, Any])

```python
# Example: Complete flow
{
    "invoice_id": "INV-12345",
    "overall_status": "COMPLETE ✓",
    "order_found": True,
    "delivery_found": True,
    "payment_found": True,
    "order_id": "SO-456",
    "delivery_id": "DO-789",
    "payment_id": "PAY-001",
    "missing_steps": [],
    "path": [
        {
            "step": 1,
            "node_type": "invoice",
            "node_id": "INV-12345",
            "label": "Invoice INV-12345",
            "status": "FOUND ✓"
        },
        {
            "step": 2,
            "node_type": "delivery",
            "node_id": "DO-789",
            "label": "Delivery DO-789",
            "status": "FOUND ✓ (1 delivery(ies))"
        },
        {
            "step": 3,
            "node_type": "order",
            "node_id": "SO-456",
            "label": "SO SO-456",
            "status": "FOUND ✓ (1 order(s))"
        },
        {
            "step": 4,
            "node_type": "payment/journal_entry",
            "node_id": "PAY-001",
            "label": "Payment INV-12345 (item 01)",
            "status": "FOUND ✓ (1 payment(s)/journal entry(ies))"
        }
    ]
}

# Example: Incomplete flow (missing delivery)
{
    "invoice_id": "INV-999",
    "overall_status": "INCOMPLETE ⚠",
    "order_found": False,
    "delivery_found": False,
    "payment_found": True,
    "order_id": None,
    "delivery_id": None,
    "payment_id": "PAY-002",
    "missing_steps": ["delivery", "order"],
    "path": [...]
}

# Example: Invoice not found
{
    "invoice_id": "INVALID",
    "overall_status": "FAILED",
    "error": "invoice_not_found",
    "invoice_exists": False
}
```

**Debug Info Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `invoice_id` | str | Input invoice ID |
| `overall_status` | str | "COMPLETE ✓", "INCOMPLETE ⚠", or "FAILED" |
| `error` | Optional[str] | Error code if failed (e.g., "invoice_not_found") |
| `order_found` | bool | True if order linked |
| `delivery_found` | bool | True if delivery linked |
| `payment_found` | bool | True if payment linked |
| `order_id` | Optional[str] | Order ID if found |
| `delivery_id` | Optional[str] | Delivery ID if found |
| `payment_id` | Optional[str] | Payment ID if found |
| `missing_steps` | List[str] | Which steps failed (e.g., ["delivery", "order"]) |
| `path` | List[Dict] | Per-step status details |

#### Example Usage

```python
# Complete flow
nodes, edges, debug = service._trace_billing_document_flow("INV-123")
print(debug["overall_status"])  # "COMPLETE ✓"
print(len(nodes))               # 4
print(len(edges))               # 3

# Incomplete flow
nodes, edges, debug = service._trace_billing_document_flow("INV-999")
print(debug["overall_status"])  # "INCOMPLETE ⚠"
print(debug["missing_steps"])   # ["delivery"]

# Not found
nodes, edges, debug = service._trace_billing_document_flow("INVALID")
print(debug.get("error"))       # "invoice_not_found"
print(len(nodes))               # 0
```

#### Algorithm Phases

| Phase | Input | Process | Output |
|-------|-------|---------|--------|
| 1 | invoice_id | Validate exists in `_node_by_id` | invoice_node or error |
| 2 | invoice_id | Search for incoming "delivery_to_invoice" edges | delivery_id |
| 3 | delivery_id | Search for incoming "order_to_delivery" edges | order_id |
| 4 | invoice_id | Search for outgoing "invoice_to_payment" edges | payment_id |
| 5 | All IDs | Build minimal subgraph (nodes + edges) | (nodes, edges, debug) |

#### Error Cases

| Condition | Return |
|-----------|--------|
| invoice_id not in graph | `([], [], {"error": "invoice_not_found"})` |
| delivery_ids is empty | Marked as missing in debug_info |
| order_ids is empty | Marked as missing in debug_info |
| payment_ids is empty | Marked as missing in debug_info |
| Multiple matches | Takes first match via `break` |

#### Implementation Location
[backend/app/query_service.py](backend/app/query_service.py#L200-L350) (approx)

---

### Method: `answer_question()` - Handler Section

#### Signature
```python
def answer_question(self, question: str) -> GraphQueryResponse:
```

#### Handler for `trace_billing_document_flow`

**Location in Method:**
```python
def answer_question(self, question: str) -> GraphQueryResponse:
    # ... earlier code for NL mapping ...
    
    # Handler for trace_billing_document_flow operation
    if query.operation == "trace_billing_document_flow":
        if not query.invoice_id:
            return GraphQueryResponse(
                answer="Invoice ID required for document flow tracing.",
                error="missing_parameter",
            )
        
        nodes, edges, debug_info = self._trace_billing_document_flow(query.invoice_id)
        
        if debug_info.get("error") == "invoice_not_found":
            return GraphQueryResponse(
                answer="Invoice not found in system.",
                error="invoice_not_found",
                debug_info=debug_info,
            )
        
        # Format response
        overall_status = debug_info.get("overall_status", "UNKNOWN")
        missing = debug_info.get("missing_steps", [])
        
        answer = f"""📋 BILLING DOCUMENT FLOW TRACE
Invoice ID: {query.invoice_id}
Overall Status: {overall_status}

Document Flow Path:
──────────────────────────────────────────────────
[... detailed path formatting ...]
──────────────────────────────────────────────────

{... completion message ...}
"""
        
        return GraphQueryResponse(
            answer=answer,
            nodes=nodes,
            edges=edges,
            debug_info=debug_info,
        )
    
    # ... continue with other operations ...
```

#### Response Format

```python
GraphQueryResponse(
    answer=str,           # Human-readable formatted path
    nodes=List[GraphNode],
    edges=List[GraphEdge],
    debug_info=Dict[str, Any],
    error=Optional[str]   # "missing_parameter", "invoice_not_found", etc.
)
```

#### Example Output

**Request:**
```python
answer_question("Trace the full flow of billing document INV-12345")
```

**Response:**
```
GraphQueryResponse(
    answer="""📋 BILLING DOCUMENT FLOW TRACE
Invoice ID: INV-12345
Overall Status: COMPLETE ✓

Document Flow Path:
──────────────────────────────────────────────────

1. INVOICE
   ID: INV-12345
   Label: Invoice INV-12345
   Status: FOUND ✓

2. DELIVERY
   ID: DO-789
   Label: Delivery DO-789
   Status: FOUND ✓ (1 delivery(ies))

3. ORDER
   ID: SO-456
   Label: SO SO-456
   Status: FOUND ✓ (1 order(s))

4. PAYMENT/JOURNAL_ENTRY
   ID: PAY-001
   Label: Payment INV-12345 (item 01)
   Status: FOUND ✓ (1 payment(s)/journal entry(ies))

──────────────────────────────────────────────────

✓ SUCCESS: Full document flow traced
All nodes from Sales Order → Delivery → Invoice → Payment found""",
    nodes=[
        GraphNode(id="SO-456", type="order", label="SO SO-456"),
        GraphNode(id="DO-789", type="delivery", label="Delivery DO-789"),
        GraphNode(id="INV-12345", type="invoice", label="Invoice INV-12345"),
        GraphNode(id="PAY-001", type="payment", label="Payment INV-12345 (item 01)")
    ],
    edges=[
        GraphEdge(from_id="SO-456", to_id="DO-789", type="order_to_delivery"),
        GraphEdge(from_id="DO-789", to_id="INV-12345", type="delivery_to_invoice"),
        GraphEdge(from_id="INV-12345", to_id="PAY-001", type="invoice_to_payment")
    ],
    debug_info={...}
)
```

---

## Data Structures

### GraphNode
```python
class GraphNode:
    id: str              # Unique identifier
    type: str            # "order", "delivery", "invoice", "payment"
    label: str           # Display label
    properties: Dict[str, Any]  # Any additional attributes
```

### GraphEdge
```python
class GraphEdge:
    from_id: str         # Source node ID
    to_id: str           # Target node ID
    type: str            # "order_to_delivery", "delivery_to_invoice", "invoice_to_payment"
    properties: Dict[str, Any]  # Any additional attributes
```

### GraphQueryResponse
```python
class GraphQueryResponse:
    answer: str          # Human-readable response
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    debug_info: Dict[str, Any]
    error: Optional[str] = None
```

---

## Integration Examples

### Example 1: Direct API Call
```python
from backend.app.query_service import GraphQueryService

service = GraphQueryService()

# Query
response = service.answer_question(
    "Trace the full flow of billing document INV-12345"
)

# Use response
print(response.answer)
print(f"Found {len(response.nodes)} nodes")
print(f"Status: {response.debug_info['overall_status']}")

if response.error:
    print(f"Error: {response.error}")
```

### Example 2: Test Incomplete Flow
```python
# Setup data where INV-999 has no delivery
response = service.answer_question("Trace INV-999")

assert "INCOMPLETE ⚠" in response.answer
assert "delivery" in response.debug_info["missing_steps"]
assert len(response.nodes) == 2  # Only invoice and payment
```

### Example 3: REST Endpoint
```python
# In FastAPI app
@app.post("/query")
def query_endpoint(question: str):
    service = GraphQueryService()
    response = service.answer_question(question)
    
    return {
        "answer": response.answer,
        "nodes": [n.model_dump() for n in response.nodes],
        "edges": [e.model_dump() for e in response.edges],
        "debug_info": response.debug_info,
        "status": "success" if not response.error else "error"
    }

# Usage
POST /query?question=Trace%20full%20flow%20of%20INV-12345
```

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Heuristic pattern match | 50-200ms | Regex-based, no API |
| Gemini API call | 2-5s | Optional, LLM fallback |
| Edge traversal (O(n)) | 50-200ms | ~100K edges in graph |
| Node lookup (O(1)) | <1ms | Hash map access |
| Response formatting | <100ms | String building |
| **Total (no Gemini)** | **100-400ms** | Production typical case |
| **Total (with Gemini)** | **2-6s** | API-dependent timing |

---

## Troubleshooting

### Missing Steps Not Reported
**Check:**
- Invoice exists in graph (`_node_by_id[invoice_id]`)
- Edge types match exactly: "order_to_delivery", "delivery_to_invoice", "invoice_to_payment"
- Edge direction correct (from_id, to_id)

### Operation Not Triggered
**Check:**
- Question contains document flow keyword
- invoice_id successfully extracted
- Heuristic patterns cover the language used
- Fallback to Gemini if heuristic misses

### Empty Nodes/Edges Returned
**Check:**
- Invoice found but all steps missing → nodes=[invoice_node], edges=[]
- Invoice not found → nodes=[], edges=[]
- Check `debug_info["error"]` for details

### Response Format Issues
- Template in `answer_question()` generates format
- Check indentation and emoji characters (✓, ✗, ⚠)
- Ensure f-string substitution correct

---

## API Versioning

**Current Version:** 1.0  
**Release Date:** [Date]  
**Status:** Production Ready

### Future Enhancements
- v1.1: Multi-path tracing (show all deliveries, not just first)
- v1.2: Timeline visualization (dates per step)
- v1.3: Reverse tracing (from payment backward to order)
- v2.0: Multiple document chains (related invoices, etc.)

---

## Support & Debugging

### Enable Verbose Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
# View detailed execution path
```

### Debug Query Object
```python
query = generate_structured_query(question)
print(query.model_dump())  # See all extracted fields
```

### Inspect Debug Info
```python
nodes, edges, debug = _trace_billing_document_flow("INV-123")
print(json.dumps(debug, indent=2))  # Full trace details
```

### Test Heuristic Patterns
```python
import re
question = "Trace the full flow of billing document INV-456"
patterns = [r"trace\s+.*\s*(?:full\s+)?flow.*(?:billing|invoice)"]
match = any(re.search(p, question) for p in patterns)
print(f"Pattern match: {match}")
```

---

## References

- [Billing Document Flow Fix Documentation](BILLING_DOCUMENT_FLOW_FIX.md)
- [Technical Implementation Reference](IMPLEMENTATION_TECHNICAL_REFERENCE.md)
- [Graph Data Model](backend/data/README.md)
