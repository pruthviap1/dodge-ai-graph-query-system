from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import CORS_ORIGINS
from backend.app.query_service import QueryService
from backend.app.schemas import GraphBuildResponse, GraphQueryRequest, GraphQueryResponse, HealthResponse
from backend.app.session_logger import log_ai_session, new_session_id


app = FastAPI(title="AI Graph Query System (Backend)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = QueryService()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/graph/build", response_model=GraphBuildResponse)
def build_graph() -> GraphBuildResponse:
    built = service.build_graph()
    return GraphBuildResponse(
        ok=True,
        node_count=len(built.snapshot.nodes),
        edge_count=len(built.snapshot.edges),
        sources=built.sources[:50],
    )


@app.get("/api/graph")
def get_graph_snapshot() -> Any:
    # Not typed: the UI only needs a graph-like JSON with nodes/edges.
    if service.graph_snapshot is None:
        return {"nodes": [], "edges": []}
    return service.graph_snapshot.model_dump()


@app.post("/api/query", response_model=GraphQueryResponse)
def query(req: GraphQueryRequest) -> GraphQueryResponse:
    # In this starter, Gemini raw output isn't captured separately.
    # We still log the structured query and final answer for later debugging.
    session_id = new_session_id()
    resp = service.answer_question(req)

    gemini_raw = resp.debug.get("gemini_raw") if isinstance(resp.debug, dict) else None
    log_ai_session(
        session_id=session_id,
        event="query",
        question=req.question,
        gemini_raw=gemini_raw,
        answer=resp.answer,
        structured_query=resp.structured_query.model_dump(),
    )
    return resp


from fastapi.staticfiles import StaticFiles
from pathlib import Path

frontend_path = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

