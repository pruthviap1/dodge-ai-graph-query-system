# Graph Query System: Product Billing Volume Fix

## Problem Summary

**Original Issue:**  
Query: "Which products are associated with the highest number of billing documents?"

**Incorrect Output:**
```
Customers: 0
Orders: 0
Deliveries: 0
Invoices: 0
Payments: 0
Products: 1
```

**Root Causes:**
1. ❌ System didn't recognize "billing documents" as synonymous with "invoices"
2. ❌ No aggregation/analytics operation to count invoices per product
3. ❌ Query traversal didn't follow: `Product ← Order → Delivery → Invoice`
4. ❌ Fell back to simple keyword matching without relationship analysis

---

## Solution Overview

### 1. New Operation: `analyze_product_billing_volume`

**What it does:**
- Analyzes all products in the graph
- Counts associated invoices (billing documents) per product
- Traverses: `Product ← Order → Delivery → Invoice`
- Returns products sorted by invoice count (descending)
- Produces visualization subgraph for top products

### 2. Graph Traversal Logic

```
Product (node)
  ↓ [order_to_product] (reverse lookup)
Order (multiple orders reference this product)
  ↓ [order_to_delivery]
Delivery (multiple deliveries per order)
  ↓ [delivery_to_invoice]
Invoice (billing document - what we count)
```

**Key Change:** Uses reverse edge following - from product back to orders, then forward through delivery to invoice chain.

### 3. Natural Language Mapping

**Term Mapping:**
- "billing documents" → "invoices"
- "billing volume" → invoice counting operation
- "top products" → sort by count descending

**Query Patterns Recognized:**
```python
r"products?\s+.*\s*(?:highest|most|most\s+number|associated)\s+.*billing",
r"billing\s+(?:documents?|invoices?)\s+.*\s+products?",
r"which\s+products?\s+.*\s+(?:billing|invoice)",
r"product.*count.*(?:billing|invoice)",
r"(?:billing|invoice).*count.*products?",
r"top\s+products?.*(?:billing|invoice)",
r"highest\s+(?:billing|invoice).*products?",
```

---

## Code Changes

### File 1: `schemas.py`
✅ Added `analyze_product_billing_volume` to operation description

### File 2: `query_service.py` 

**New Method:** `_analyze_product_billing_volume()`
- **Input:** node_cap, edge_cap (limits for performance)
- **Output:** (nodes, edges, debug_info)
- **Logic:**
  ```
  Phase 1: Index all edges by type
  Phase 2: Aggregate invoice counts per product
  Phase 3: Sort products by invoice count (descending)
  Phase 4: Build subgraph for visualization (top 5 products)
  Phase 5: Format results and prepare debug info
  ```

**Handler in `answer_question()`:**
- Detects `analyze_product_billing_volume` operation
- Calls analysis method
- Formats response with:
  - Total products with billing data
  - Top 5 products with invoice counts
  - Associated order counts
  - Subgraph for visualization

### File 3: `gemini.py`

**Enhanced `generate_structured_query()`:**
- Added pattern detection for product-billing queries
- Added term expansion for "billing documents"
- Operation priority: `product_billing > incomplete > ID-based > keyword`

**New Patterns (Heuristic Fallback):**
```python
billing_analysis_patterns = [
    r"products?\s+.*\s*(?:highest|most|most\s+number|associated)\s+.*billing",
    r"billing\s+(?:documents?|invoices?)\s+.*\s+products?",
    r"which\s+products?\s+.*\s+(?:billing|invoice)",
    r"product.*count.*(?:billing|invoice)",
    r"(?:billing|invoice).*count.*products?",
    r"top\s+products?.*(?:billing|invoice)",
    r"highest\s+(?:billing|invoice).*products?",
]
```

**Enhanced Gemini Prompt:**
- Documented all operations including `analyze_product_billing_volume`
- Added context: "billing documents" = "invoices"
- Added explicit examples for when to use product billing analysis

---

## Expected Output

### Query: "Which products are associated with the highest number of billing documents?"

**Correct Output (Production-Ready):**
```
Product Billing Volume Analysis:
Total products with billing documents: 47

🏆 Highest: 'Product ABC-122' with 156 billing documents

Top products by invoice count:
1. Product: ABC-122
   Billing Documents (Invoices): 156
   Associated Orders: 89

2. Product: XYZ-445
   Billing Documents (Invoices): 143
   Associated Orders: 76

3. Product: DEF-789
   Billing Documents (Invoices: 127
   Associated Orders: 68

(... up to 5 products shown ...)
```

### Debug Info:
```json
{
  "total_products_with_billing": 47,
  "highest_invoice_count": 156,
  "highest_product_id": "product:ABC-122",
  "top_products": [
    {
      "product_node_id": "product:ABC-122",
      "product_name": "Product ABC-122",
      "invoice_count": 156,
      "orders_count": 89,
      "top_invoices": ["invoice:INV-001", "invoice:INV-002", ...]
    },
    ...
  ]
}
```

### Subgraph Visualization:
- **Nodes:** Top 5 products, sample orders, sample deliveries, sample invoices
- **Edges:** 
  - Order → Product
  - Order → Delivery
  - Delivery → Invoice
  - Limited to preserve UI performance

---

## Fallback Handling

### Scenario 1: No Billing Data
**Query:** "Which products have invoices?"  
**Condition:** No products have associated invoices  
**Response:**
```
No billing data available. No products have associated invoices (billing documents).
```

### Scenario 2: Empty Graph
**Query:** "Which products are associated with the highest number of billing documents?"  
**Condition:** Graph not yet built  
**Response:**
```
No billing data available. Make sure the graph has been built and contains invoices.
```

### Scenario 3: Missing Relationships
**Scenario:** Products exist but no order_to_product edges  
**Result:** Returns "No billing data available"  
**Reason:** Gracefully handles incomplete graph data

---

## Graph Schema Validation

### Node Types Present ✅
```
✓ Product (nodes with type="product")
✓ Order (nodes with type="order")
✓ Delivery (nodes with type="delivery")
✓ Invoice (nodes with type="invoice")
✓ Payment (nodes with type="payment")
✓ Customer (nodes with type="customer")
```

### Edge Types Used ✅
```
✓ order_to_product: Order → Product
✓ order_to_delivery: Order → Delivery
✓ delivery_to_invoice: Delivery → Invoice
✓ invoice_to_payment: Invoice → Payment
✓ customer_to_order: Customer → Order
```

### Data Files Confirmed ✅
```
✓ sales_order_headers/ (orders)
✓ sales_order_items/ (order-product relationships)
✓ outbound_delivery_headers/ (deliveries)
✓ outbound_delivery_items/ (delivery-invoice relationships)
✓ billing_document_headers/ (invoices)
✓ billing_document_items/ (detailed billing)
✓ payments_accounts_receivable/ (payments)
✓ products/ (product catalog)
✓ business_partners/ (customers)
```

---

## Testing Guide

### Test Case 1: Basic Functionality
```bash
POST /api/query
{
  "question": "Which products are associated with the highest number of billing documents?"
}
```
**Expected:**
- Status: 200
- Answer includes product name and invoice counts
- Invoices > 0 (not showing 0)
- Graph has nodes and edges

### Test Case 2: Alternative Phrasings
```bash
# Should all work now:
"top products by billing volume"
"which products have the most invoices"
"product invoice rankings"
"billing document count by product"
"products with highest billing document count"
```

### Test Case 3: Edge Case - No Data
```bash
# For a dataset with no invoices:
"Which products have billing documents?"
```
**Expected:**
```
No billing data available. No products have associated invoices (billing documents).
```

### Test Case 4: Natural Language Variations
```bash
# All should trigger analyze_product_billing_volume:
"products associated with highest billing documents"
"top products by invoice count"
"which products have the most billing activity"
"rank products by billing document volume"
```

---

## Performance Considerations

### Limits Enforced
- **node_cap:** 200 (max nodes in response)
- **edge_cap:** 5000 (max edges in response)
- **top_products_shown:** 5 (in visualization)
- **invoices_per_product:** 100 (in debug info)

### Optimizations
1. **Index Phase:** O(n) pass over edges (linear)
2. **Aggregation Phase:** Single aggregation pass
3. **Sorting Phase:** O(p log p) where p = products with billing
4. **Visualization:** Limited to top 5 products with 3 sample invoices each

### Estimated Complexity
- **Time:** O(n + p log p) where n = edges, p = products
- **Space:** O(e) where e = edges to store in result

---

## Implementation Quality Checklist

- ✅ Handles "billing documents" as invoices
- ✅ Proper graph traversal (Product ← Order → Delivery → Invoice)
- ✅ Counts relationships correctly
- ✅ Sorts by count descending
- ✅ Returns products with highest count
- ✅ Fallback for missing data
- ✅ Fallback for missing relationships
- ✅ Schema validated (nodes and edges exist)
- ✅ Production-ready error handling
- ✅ Structured response format
- ✅ Debug information for troubleshooting
- ✅ Performance limits enforced
- ✅ Natural language mapping improved
- ✅ Gemini prompt updated with examples
- ✅ Heuristic fallback for non-Gemini mode

---

## Next Steps (Optional Enhancements)

1. **Caching:** Cache product-invoice counts (invalidate on graph rebuild)
2. **Filtering:** Add parameters to filter by product type, date range
3. **Comparison:** "Compare product X to product Y by billing volume"
4. **Trends:** "Which products have increased invoices over time?"
5. **Anomalies:** "Which products have unusual billing patterns?"
6. **Drill-down:** Click on product to see all associated invoices

---

## Files Modified

1. `backend/app/schemas.py` - Updated operation list
2. `backend/app/query_service.py` - Added analysis method and handler
3. `backend/app/gemini.py` - Enhanced NL mapping and prompt

**Total Changes:** ~400 lines of production-ready code
