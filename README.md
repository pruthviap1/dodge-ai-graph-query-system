# Dodge AI Graph Query System

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-red.svg)](https://streamlit.io/)

An AI-powered graph-based business intelligence system that transforms enterprise data into an interconnected knowledge graph, enabling natural language queries with accurate, data-driven insights.

## 🏗️ Architecture Overview

### System Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Streamlit UI  │────│   FastAPI       │────│   Gemini AI     │
│                 │    │   Backend       │    │   (LLM)         │
│ • Modern UI     │    │ • REST API      │    │ • Query         │
│ • Graph Viz     │    │ • Graph Logic   │    │   Processing    │
│ • Query Input   │    │ • Data Loading  │    │ • Structured    │
└─────────────────┘    └─────────────────┘    │   Parsing       │
                                              └─────────────────┘
                                                     │
┌─────────────────┐    ┌─────────────────┐          │
│   JSONL Data    │────│   NetworkX      │◄─────────┘
│   Files         │    │   Graph         │
│ • Orders        │    │ • In-Memory     │
│ • Deliveries    │    │ • Traversal     │
│ • Invoices      │    │ • Operations    │
│ • Customers     │    │                 │
└─────────────────┘    └─────────────────┘
```

### Architecture Decisions

#### **Backend Framework: FastAPI**
- **Why FastAPI?** Chosen for its automatic API documentation, type safety with Pydantic, and high performance with async support
- **Benefits:** Automatic OpenAPI/Swagger docs, request validation, dependency injection, and excellent developer experience
- **Trade-offs:** Slightly steeper learning curve than Flask, but better for complex APIs with data validation

#### **Frontend Framework: Streamlit**
- **Why Streamlit?** Rapid prototyping capabilities, built-in components, and seamless Python integration
- **Benefits:** No need for separate frontend stack, quick iteration, automatic hot-reload
- **Trade-offs:** Less control over UI customization compared to React/Vue, but sufficient for this use case

#### **Graph Visualization: PyVis**
- **Why PyVis?** Interactive network visualization with built-in physics simulation and customization options
- **Benefits:** JavaScript-free integration with Streamlit, responsive interactions, customizable styling
- **Trade-offs:** Limited compared to D3.js, but adequate for business intelligence use cases

#### **Modular Architecture**
- **Separation of Concerns:** Clear boundaries between data loading, graph building, query processing, and API endpoints
- **Benefits:** Easier testing, maintenance, and future extensions
- **Structure:**
  - `graph_builder.py`: Data ingestion and graph construction
  - `query_service.py`: Business logic and LLM integration
  - `gemini.py`: AI client wrapper
  - `schemas.py`: Data models and API contracts

## 🗄️ Database Choice

### File-Based Storage with JSONL

**Decision:** JSON Lines (JSONL) files instead of traditional RDBMS

#### **Why JSONL Files?**

1. **Simplicity & Portability**
   - No database server setup required
   - Easy to version control and deploy
   - Platform-independent data format
   - Zero configuration for development

2. **Business Intelligence Focus**
   - Read-heavy workload (analytics, not transactions)
   - Complex graph relationships better suited to in-memory processing
   - No need for ACID transactions or concurrent writes

3. **Data Volume Considerations**
   - Enterprise datasets often start as exports from existing systems
   - JSONL handles large datasets efficiently
   - Easy to parallelize processing across files

#### **Data Structure**
```
data/
├── sales_order_headers/          # Order master data
├── sales_order_items/            # Order line items
├── outbound_delivery_headers/    # Delivery documents
├── outbound_delivery_items/      # Delivery items
├── billing_document_headers/     # Invoice headers
├── billing_document_items/       # Invoice line items
├── payments_accounts_receivable/ # Payment records
├── business_partners/            # Customer/vendor data
└── products/                     # Product master data
```

#### **Graph Engine: NetworkX**
- **Why NetworkX?** Python's most comprehensive graph library with excellent algorithm support
- **Benefits:** Rich traversal algorithms, graph analytics, serialization support
- **In-Memory Processing:** Entire graph loaded into memory for fast queries

#### **Trade-offs Considered**
- **Scalability:** For very large datasets (>100M nodes), consider Neo4j or Amazon Neptune
- **Performance:** File I/O on startup vs. database connection pooling
- **Query Complexity:** NetworkX handles complex traversals well, but no declarative query language

## 🤖 LLM Prompting Strategy

### Multi-Layer Query Processing

```
Natural Language Query
        ↓
   Gemini AI Processing
        ↓
  Structured Query Object
        ↓
   Graph Traversal Logic
        ↓
   Business Intelligence
```

#### **Prompt Engineering Approach**

1. **Structured Output Parsing**
   - Gemini instructed to return JSON matching Pydantic `StructuredGraphQuery` model
   - Type-safe conversion from natural language to structured parameters
   - Validation ensures all required fields are present

2. **Domain-Specific Operations**
   ```python
   # Available operations in StructuredGraphQuery
   operations = [
       "trace_order",              # Follow order → delivery → invoice flow
       "trace_delivery",           # Delivery document analysis
       "trace_invoice",            # Invoice and payment tracking
       "find_incomplete_orders",   # Orders missing deliveries/invoices
       "analyze_product_billing_volume",  # Product performance analysis
       "trace_billing_document_flow",     # End-to-end document flow
       "keyword_graph_lookup"      # General graph search
   ]
   ```

3. **Context-Aware Parsing**
   - Extracts entity IDs (order numbers, customer IDs, etc.) from natural language
   - Recognizes business domain terminology
   - Handles variations in phrasing ("sales order 123" vs "order #123")

#### **Fallback Strategy**
- **Heuristic Parsing:** When Gemini API unavailable, regex-based keyword extraction
- **Pattern Matching:** Pre-defined patterns for common query types
- **Graceful Degradation:** System remains functional without AI, though less accurate

#### **Prompt Template Structure**
```python
prompt = f"""
Convert this business question to a structured graph query:

Question: {user_question}

Return JSON with these fields:
- operation: Choose from {available_operations}
- customer_id, order_id, delivery_id, invoice_id: Extract IDs if mentioned
- entity_types: Focus on specific entity types if relevant
- keywords: Extract search terms
- limit, max_hops: Control result size and traversal depth

JSON Response:
"""
```

## 🛡️ Guardrails & Security

### Input Validation & Sanitization

#### **Pydantic Model Validation**
- All API inputs validated with Pydantic models
- Type checking prevents malformed data
- Automatic error responses for invalid inputs
- Field constraints (min/max values, regex patterns)

#### **Query Limits & Performance Guards**
```python
class StructuredGraphQuery(BaseModel):
    limit: int = Field(200, ge=1, le=5000)      # Max results
    max_hops: int = Field(2, ge=0, le=6)        # Graph traversal depth
```

#### **Rate Limiting Considerations**
- No explicit rate limiting implemented (single-user system)
- API key authentication for production deployment
- Request logging for monitoring usage patterns

### Error Handling & Resilience

#### **Graceful Degradation**
- LLM fallback to heuristic parsing when API unavailable
- Partial results returned when some operations fail
- Comprehensive error logging with context

#### **Security Measures**
- CORS configuration for cross-origin requests
- Environment variable configuration (no hardcoded secrets)
- Input sanitization prevents injection attacks
- File system access restricted to data directory

#### **Data Privacy**
- No user data stored (stateless API)
- All processing happens in-memory
- Logs contain only query patterns, not sensitive data
- GDPR/CCPA compliance through data minimization

### Operational Safety

#### **Resource Limits**
- Graph traversal capped at reasonable depths
- Memory usage monitored through NetworkX operations
- File I/O restricted to known data directories
- Timeout handling for long-running queries

#### **Logging & Monitoring**
- AI session logging for debugging and improvement
- Structured logging with request IDs
- Error tracking without exposing sensitive information
- Performance metrics collection

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Gemini API key (optional, falls back to heuristics)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/dodge-ai-graph-query-system.git
   cd dodge-ai-graph-query-system
   ```

2. **Set up environment**
   ```bash
   # Copy environment template
   cp backend/.env.example backend/.env

   # Add your Gemini API key
   echo "GEMINI_API_KEY=your_api_key_here" >> backend/.env
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Running the Application

#### **Development Mode**
```bash
# Backend API
uvicorn backend.app.main:app --reload --port 8000

# Frontend (in another terminal)
streamlit run app.py
```

#### **Production Deployment**
- **Backend:** Deploy to Render, Railway, or Heroku using provided `Procfile`
- **Frontend:** Static hosting on Vercel, Netlify, or similar
- **Database:** No database required (file-based storage)

### API Usage

```python
import requests

# Health check
response = requests.get("http://localhost:8000/health")

# Build graph
response = requests.post("http://localhost:8000/api/graph/build")

# Query graph
query_data = {"question": "Show me orders for customer ABC123"}
response = requests.post("http://localhost:8000/api/graph/query", json=query_data)
```

## 📊 Data Model

### Core Entities
- **Orders:** Sales order headers and line items
- **Deliveries:** Outbound delivery documents and items
- **Invoices:** Billing documents and accounting entries
- **Payments:** Accounts receivable payment records
- **Customers:** Business partner information
- **Products:** Product master data and descriptions

### Graph Relationships
```
Order → Delivery → Invoice → Payment
   ↓       ↓         ↓        ↓
Customer  Product  Product  Customer
```

## 🔧 Configuration

### Environment Variables
```bash
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional
DATA_DIR=./data                    # Data files location
LOGS_DIR=./logs                    # Log files location
GEMINI_MODEL=gemini-1.5-flash     # AI model version
CORS_ORIGINS=*                     # CORS allowed origins
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Google Gemini AI for natural language processing
- FastAPI community for excellent documentation
- NetworkX for graph algorithm implementations
- PyVis for interactive visualizations
