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
    const colors = {
      order: "#3b82f6",
      delivery: "#9333ea",
      invoice: "#0891b2",
      payment: "#059669",
      customer: "#d97706",
      product: "#db2777",
    };
    const color = colors[n.type] || "#3b82f6";

    return {
      id: n.id,
      label: label,
      title: label,
      group: n.type,
      color: {
        background: color,
        border: color,
        highlight: { background: color, border: color },
      },
      font: { size: 14, color: "#000", face: "Arial" },
      borderWidth: 2,
      borderWidthSelected: 3,
    };
  });

  const edges = (snapshot.edges || []).map((e) => {
    return {
      from: e.from_id,
      to: e.to_id,
      label: e.label || e.type || "",
      arrows: "to",
      color: { color: "rgba(59, 130, 246, 0.8)", highlight: "rgba(59, 130, 246, 1)" },
      font: { size: 12, color: "#333" },
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
    nodes: { shape: "dot", size: 25 },
    edges: { color: { inherit: true }, font: { size: 10 } },
  };

  // Destroy previous network if exists
  let network = null;
  if (window.currentNetwork) {
    window.currentNetwork.destroy();
  }

  network = new vis.Network(container, data, options);
  window.currentNetwork = network;
  
  return network;
}

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

    debugEl.textContent = "";

    const graph = data.graph || { nodes: [], edges: [] };
    const nodeCount = (graph.nodes || []).length;
    const edgeCount = (graph.edges || []).length;

    if (nodeCount === 0 && edgeCount === 0) {
      if (window.currentNetwork) window.currentNetwork.destroy();
      window.currentNetwork = null;
      return;
    }

    buildVisGraph(graph);
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

