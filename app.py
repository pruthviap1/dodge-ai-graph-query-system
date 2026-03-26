import streamlit as st
from backend.app.query_service import process_query
from pyvis.network import Network
import streamlit.components.v1 as components

# Modern CSS styling
st.markdown("""
<style>
    .main-title {
        text-align: center;
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 2rem;
    }
    .query-section {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 2rem;
    }
    .answer-section {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 2rem;
        border-left: 4px solid #667eea;
    }
    .graph-section {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
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
        width: 100%;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(102, 126, 234, 0.3);
    }
    .stTextInput>div>div>input {
        border-radius: 25px;
        border: 2px solid #e1e5e9;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        transition: all 0.3s ease;
    }
    .stTextInput>div>div>input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    .section-title {
        font-size: 1.5rem;
        font-weight: bold;
        color: #333;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
    }
    .section-icon {
        margin-right: 0.5rem;
    }
    body {
        background-color: #f8f9fa;
    }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        color: #333;
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

st.markdown('<div class="main-title">🔍 AI Graph Query System</div>', unsafe_allow_html=True)

# Query input section
st.markdown('<div class="query-section">', unsafe_allow_html=True)
st.markdown('<div class="section-title"><span class="section-icon">💭</span>Ask Your Query</div>', unsafe_allow_html=True)

question = st.text_input("", placeholder="Enter your question here...", label_visibility="collapsed")

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    submit_button = st.button("🚀 Submit Query")

st.markdown('</div>', unsafe_allow_html=True)

if submit_button and question.strip():
    with st.spinner("🔄 Processing your query..."):
        try:
            result = process_query(question)

            # Answer section
            st.markdown('<div class="answer-section">', unsafe_allow_html=True)
            st.markdown('<div class="section-title"><span class="section-icon">🤖</span>AI Response</div>', unsafe_allow_html=True)
            st.write(result["answer"])
            st.markdown('</div>', unsafe_allow_html=True)

            # Graph section
            st.markdown('<div class="graph-section">', unsafe_allow_html=True)
            st.markdown('<div class="section-title"><span class="section-icon">📊</span>Graph Visualization</div>', unsafe_allow_html=True)
            show_graph(result["graph"])
            st.markdown('</div>', unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ Error: {e}")
