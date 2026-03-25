const BACKEND_KEY = "backendUrl";
const DEFAULT_BACKEND_URL = "http://localhost:8000";

const backendUrlEl = document.getElementById("backendUrl");
const saveBackendUrlBtn = document.getElementById("saveBackendUrl");
const questionEl = document.getElementById("question");
const chatFormEl = document.getElementById("chatForm");
const answerEl = document.getElementById("answer");
const debugEl = document.getElementById("debug");

function setBackendUrl(url) {
  backendUrlEl.value = url;
}

function getBackendUrl() {
  return localStorage.getItem(BACKEND_KEY) || DEFAULT_BACKEND_URL;
}

function saveBackendUrl() {
  localStorage.setItem(BACKEND_KEY, backendUrlEl.value.trim() || DEFAULT_BACKEND_URL);
}

function stringifyShort(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch (e) {
    return String(obj);
  }
}

function buildVisGraph(snapshot) {
  const nodes = (snapshot.nodes || []).map((n) => {
    const label = n.label || n.id;
    return { id: n.id, label: label, title: label, group: n.type };
  });

  const edges = (snapshot.edges || []).map((e) => {
    return {
      from: e.from_id,
      to: e.to_id,
      label: e.label || e.type || "",
      arrows: "to",
    };
  });

  const container = document.getElementById("graph");
  const data = {
    nodes: new vis.DataSet(nodes),
    edges: new vis.DataSet(edges),
  };

  const options = {
    physics: { stabilization: false },
    interaction: { hover: true },
    nodes: { shape: "dot", size: 10 },
    edges: { color: { inherit: true }, font: { size: 10 } },
  };

  // Create/replace network each time (starter simplicity).
  return new vis.Network(container, data, options);
}

let network = null;

async function ask(question) {
  const backendUrl = backendUrlEl.value.trim() || DEFAULT_BACKEND_URL;
  answerEl.textContent = "Loading...";
  debugEl.textContent = "";

  const res = await fetch(`${backendUrl}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Backend error: ${res.status} ${text}`);
  }

  return await res.json();
}

chatFormEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = (questionEl.value || "").trim();
  if (!question) return;

  const submitBtn = chatFormEl.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const data = await ask(question);
    answerEl.textContent = data.answer || "";

    // Clear debug by default to keep UI minimal/clean.
    debugEl.textContent = "";

    const graph = data.graph || { nodes: [], edges: [] };
    const nodeCount = (graph.nodes || []).length;
    const edgeCount = (graph.edges || []).length;

    // Guardrail case: empty graph -> do not render network.
    if (nodeCount === 0 && edgeCount === 0) {
      if (network) network.destroy();
      network = null;
      return;
    }

    if (network) network.destroy();
    network = buildVisGraph(graph);
  } catch (err) {
    answerEl.textContent = "";
    debugEl.textContent = String(err && err.message ? err.message : err);
  } finally {
    const submitBtn = chatFormEl.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = false;
  }
});

saveBackendUrlBtn.addEventListener("click", () => {
  saveBackendUrl();
  setBackendUrl(getBackendUrl());
});

// Init
setBackendUrl(getBackendUrl());

