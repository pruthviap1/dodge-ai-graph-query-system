import streamlit as st
from backend.app.query_service import process_query
from pyvis.network import Network
import streamlit.components.v1 as components

# Page configuration
st.set_page_config(
    page_title="AI Graph Query System",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for modern styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 2rem 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 15px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .main-title {
        font-size: 3rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.2rem;
        opacity: 0.9;
    }
    .input-container {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 2rem;
    }
    .result-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1.5rem;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: bold;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
    }
    .section-icon {
        margin-right: 0.5rem;
    }
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        border-radius: 25px;
        font-weight: bold;
        font-size: 1rem;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
    }
    .stTextInput>div>div>input {
        border-radius: 25px;
        border: 2px solid #e1e5e9;
        padding: 0.75rem 1rem;
        font-size: 1rem;
    }
    .stTextInput>div>div>input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2);
    }
    body {
        background-color: #f8f9fa;
    }
    .centered {
        display: flex;
        justify-content: center;
        align-items: center;
    }
</style>
""", unsafe_allow_html=True)

def show_graph(graph):
    net = Network(height="500px", width="100%", directed=True)

    # Add nodes
    for node in graph["nodes"]:
        net.add_node(node["id"], label=node["label"])

    # Add edges
    for edge in graph["edges"]:
        net.add_edge(edge["from_id"], edge["to_id"], label=edge["type"])

    net.save_graph("graph.html")

    HtmlFile = open("graph.html", "r", encoding="utf-8")
    components.html(HtmlFile.read(), height=500)

# Header
st.markdown("""
<div class="main-header">
    <div class="main-title">🔍 AI Graph Query System</div>
    <div class="subtitle">Explore your business data with intelligent graph queries</div>
</div>
""", unsafe_allow_html=True)

# Main content in columns for better layout
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    # Input section
    st.markdown('<div class="input-container">', unsafe_allow_html=True)
    st.markdown("### 💬 Ask Your Query")
    question = st.text_input("", placeholder="e.g., Show me orders for customer ABC123", label_visibility="collapsed")

    if st.button("🚀 Analyze Query", use_container_width=True):
        if not question.strip():
            st.error("Please enter a query first!")
        else:
            with st.spinner("🔄 Processing your query..."):
                try:
                    result = process_query(question)

                    # Answer section
                    st.markdown('<div class="result-card">', unsafe_allow_html=True)
                    st.markdown('<div class="section-header"><span class="section-icon">🤖</span>AI Answer</div>', unsafe_allow_html=True)
                    st.write(result["answer"])
                    st.markdown('</div>', unsafe_allow_html=True)

                    # Graph visualization section
                    st.markdown('<div class="result-card">', unsafe_allow_html=True)
                    st.markdown('<div class="section-header"><span class="section-icon">📊</span>Graph Visualization</div>', unsafe_allow_html=True)
                    show_graph(result["graph"])
                    st.markdown('</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"❌ Error processing query: {str(e)}")

    st.markdown('</div>', unsafe_allow_html=True)
