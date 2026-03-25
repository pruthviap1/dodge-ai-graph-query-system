from __future__ import annotations

import json
import re
from typing import Any

from backend.app.config import GEMINI_API_KEY, GEMINI_MODEL
from backend.app.schemas import StructuredGraphQuery


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """
    Best-effort extraction of a single top-level JSON object from Gemini output.
    """
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to locate the first {...} block.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


class GeminiClient:
    """
    Gemini wrapper.

    If `GEMINI_API_KEY` is missing, we fall back to a deterministic heuristic query.
    """

    def __init__(self) -> None:
        self.api_key = GEMINI_API_KEY
        self.model_name = GEMINI_MODEL

        if self.api_key:
            import google.generativeai as genai  # local import to keep deps optional at runtime

            genai.configure(api_key=self.api_key)
            self._genai = genai
        else:
            self._genai = None

    def generate_structured_query(self, question: str) -> tuple[StructuredGraphQuery, str | None]:
        if not self._genai:
            # Minimal heuristic: derive keywords from the question.
            keywords = re.findall(r"[a-zA-Z0-9_-]{3,}", question.lower())
            q = question.lower()

            # Check for billing document flow trace query
            trace_doc_flow_patterns = [
                r"trace\s+.*\s*(?:full\s+)?flow",  # "trace ... flow"
                r"billing\s+(?:document|invoice)\s+flow",  # "billing document flow"
                r"(?:full\s+)?flow.*(?:order|delivery|invoice)",  # "flow ... order/delivery/invoice"
                r"(?:order|delivery|invoice).*(?:full\s+)?flow",  # "order/delivery/invoice ... flow"
                r"sales\s+order.*delivery.*invoice",  # "sales order ... delivery ... invoice"
                r"document\s+flow",  # "document flow"
                r"trace.*(?:order|delivery|invoice|billing|invoice)",  # "trace ... <entity>"
            ]
            is_trace_doc_flow = any(re.search(pattern, q) for pattern in trace_doc_flow_patterns)

            # Check for incomplete orders query
            incomplete_patterns = [
                r"incomplete\s+orders?",
                r"broken\s+flow",
                r"missing\s+invoice",
                r"not\s+delivered",
                r"not\s+paid",
                r"without\s+invoice",
                r"without\s+delivery",
                r"without\s+payment",
                r"no\s+invoice",
                r"no\s+delivery",
                r"no\s+payment",
            ]
            is_incomplete_query = any(re.search(pattern, q) for pattern in incomplete_patterns)

            # Check for product billing volume analysis queries
            billing_analysis_patterns = [
                r"products?\s+.*\s*(?:highest|most|most\s+number|associated)\s+.*billing",
                r"billing\s+(?:documents?|invoices?)\s+.*\s+products?",
                r"which\s+products?\s+.*\s+(?:billing|invoice)",
                r"product.*count.*(?:billing|invoice)",
                r"(?:billing|invoice).*count.*products?",
                r"top\s+products?.*(?:billing|invoice)",
                r"highest\s+(?:billing|invoice).*products?",
            ]
            is_product_billing_query = any(re.search(pattern, q) for pattern in billing_analysis_patterns)

            # Best-effort ID extraction (works without Gemini key).
            order_id = None
            delivery_id = None
            invoice_id = None
            customer_id = None
            product_id = None
            accounting_document = None

            m = re.search(r"\border\s*([0-9]{5,})\b", q)
            if m:
                order_id = m.group(1)
            m = re.search(r"\bdelivery\s*([0-9]{6,})\b", q)
            if m:
                delivery_id = m.group(1)
            
            # Invoice ID extraction: match "invoice 123456" OR "billing document/invoice 123456" OR "INV-123456" OR just numbers after "invoice"
            m = re.search(r"\b(?:invoice|inv)\s*[-]?([0-9]{5,})\b", q)
            if m:
                invoice_id = m.group(1)
            # Also try matching "billing document" or "billing invoice" pattern
            if not invoice_id:
                m = re.search(r"\b(?:billing\s+(?:document|invoice))\s*[-]?([0-9]{5,})\b", q)
                if m:
                    invoice_id = m.group(1)
            # Also try matching standalone invoice format like INV-123456
            if not invoice_id:
                m = re.search(r"\binv[-]?([0-9]{6,})\b", q)
                if m:
                    invoice_id = m.group(1)
            
            m = re.search(r"\bcustomer\s*([0-9]{5,})\b", q)
            if m:
                customer_id = m.group(1)
            m = re.search(r"\bproduct\s*([a-z0-9-]{4,})\b", q)
            if m:
                product_id = m.group(1).upper()
            m = re.search(r"\b(?:accounting\s*document|payment)\s*([0-9]{8,})\b", q)
            if m:
                accounting_document = m.group(1)

            # Operation priority: trace_doc_flow > product_billing > incomplete > order > delivery > invoice > customer > product > keyword.
            if is_trace_doc_flow:
                # Document flow trace (will use invoice_id if provided, or pick a sample)
                operation = "trace_billing_document_flow"
            elif is_product_billing_query:
                operation = "analyze_product_billing_volume"
            elif is_incomplete_query:
                operation = "find_incomplete_orders"
            elif order_id:
                operation = "trace_order"
            elif delivery_id:
                operation = "trace_delivery"
            elif invoice_id:
                operation = "trace_invoice"
            elif customer_id:
                operation = "trace_customer"
            elif product_id:
                operation = "keyword_graph_lookup"
            else:
                operation = "keyword_graph_lookup"

            return (
                StructuredGraphQuery(
                    operation=operation,
                    customer_id=customer_id,
                    order_id=order_id,
                    delivery_id=delivery_id,
                    invoice_id=invoice_id,
                    accounting_document=accounting_document,
                    product_id=product_id,
                    entity_types=[],
                    keywords=keywords[:10],
                    limit=200,
                    max_hops=2,
                ),
                None,
            )

        prompt = f"""
You are part of an AI Graph Query System for analyzing ERP supply chain and billing data.
Convert a user's natural-language question into a JSON object that matches the schema below.

IMPORTANT CONCEPTS:
- "billing documents" = "invoices"
- Document flow tracing: Sales Order → Delivery → Invoice → Payment/Journal Entry
- "journal entry" refers to payments and accounting records linked to invoices

Rules:
- Output ONLY valid JSON (no markdown, no comments).
- Choose `operation` from: `trace_order`, `trace_delivery`, `trace_invoice`, `trace_customer`, 
  `find_incomplete_orders`, `analyze_product_billing_volume`, `trace_billing_document_flow`, `keyword_graph_lookup`.
- Use `trace_billing_document_flow` ONLY when:
  * User asks to trace a specific billing document (invoice) through the entire flow
  * User asks for "full flow" or "complete path" of an invoice
  * User asks to trace: Sales Order → Delivery → Invoice → Payment/Journal Entry
  * An invoice_id is available to trace
- Use `find_incomplete_orders` for questions about:
  * Incomplete orders
  * Broken flows
  * Missing invoices or payments
  * Orders not delivered or not paid
- Use `analyze_product_billing_volume` for questions about:
  * Top products by invoices/billing volume
  * Which products have most billing documents
  * Product ranking by billing activity
- If the user provides a specific ID (order, delivery, invoice, customer, product), populate the corresponding *_id field.
- Use `keywords` only as a fallback when you cannot determine a specific operation.

Schema:
{{
  "operation": string,
  "customer_id": string | null,
  "order_id": string | null,
  "delivery_id": string | null,
  "invoice_id": string | null,
  "accounting_document": string | null,
  "product_id": string | null,
  "entity_types": string[],
  "keywords": string[],
  "limit": number,
  "max_hops": number
}}

User question:
{question}
"""

        model = self._genai.GenerativeModel(self.model_name)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or str(resp)

        payload = _extract_json_object(text) or {}
        # Let pydantic fill defaults for missing fields by passing what we have.
        return StructuredGraphQuery.model_validate(payload), text

