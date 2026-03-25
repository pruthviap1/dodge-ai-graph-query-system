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
            m = re.search(r"\binvoice\s*([0-9]{6,})\b", q)
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

            # Operation priority: order > delivery > invoice > customer > product > keyword.
            if order_id:
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
You are part of an AI Graph Query System.
Convert a user's natural-language question into a JSON object that matches the schema below.

Rules:
- Output ONLY valid JSON (no markdown, no comments).
- Choose `operation` from: `trace_order`, `trace_delivery`, `trace_invoice`, `trace_customer`, `keyword_graph_lookup`.
- Prefer a specific `operation` when the question asks to trace/track.
- If the user provides an ID (order, delivery, invoice, customer, product), populate the corresponding *_id field.
- Use `keywords` only as a fallback when you cannot extract a reliable ID.

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

