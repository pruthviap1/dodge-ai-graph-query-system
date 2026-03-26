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

# Custom CSS for modern dashboard styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1.5rem 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 15px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .main-title {
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.1rem;
        opacity: 0.9;
    }
    .dashboard-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
        height: 100%;
    }
    .chat-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        height: 600px;
        display: flex;
        flex-direction: column;
    }
    .chat-messages {
        flex: 1;
        overflow-y: auto;
        margin-bottom: 1rem;
        padding: 1rem;
        background: #f8f9fa;
        border-radius: 10px;
        max-height: 500px;
    }
    .message {
        margin-bottom: 1rem;
        padding: 0.75rem;
        border-radius: 10px;
        max-width: 80%;
    }
    .user-message {
        background: #667eea;
        color: white;
        margin-left: auto;
        text-align: right;
    }
    .ai-message {
        background: #f8f9fa;
        color: #333;
        border-left: 4px solid #667eea;
    }
    .message-icon {
        margin-right: 0.5rem;
    }
    .input-container {
        background: white;
        padding: 1rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-top: 1rem;
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
    .stButton>button:hover:not(:disabled) {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.2);
    }
    .stButton>button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
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
        background-color: #f5f7fb;
    }
    .card-title {
        font-size: 1.3rem;
        font-weight: bold;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
    }
    .card-icon {
        margin-right: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

def show_graph(graph):
    net = Network(
        height="500px", 
        width="100%", 
        directed=True,
        bgcolor="#f8f9fa",
        font_color="#333333"
    )
    
    # Modern styling options
    net.set_options("""
    {
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.3,
          "springLength": 95,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.1
        },
        "maxVelocity": 50,
        "minVelocity": 0.1,
        "solver": "barnesHut",
        "timestep": 0.5,
        "stabilization": {
          "enabled": true,
          "iterations": 1000,
          "updateInterval": 25
        }
      },
      "nodes": {
        "borderWidth": 2,
        "borderWidthSelected": 4,
        "color": {
          "border": "#667eea",
          "background": "#ffffff",
          "highlight": {
            "border": "#764ba2",
            "background": "#e8f4fd"
          },
          "hover": {
            "border": "#764ba2",
            "background": "#f0f8ff"
          }
        },
        "font": {
          "color": "#333333",
          "size": 14,
          "face": "arial",
          "background": "rgba(255, 255, 255, 0.8)",
          "strokeWidth": 0
        },
        "shape": "dot",
        "size": 20,
        "shadow": {
          "enabled": true,
          "color": "rgba(0,0,0,0.2)",
          "size": 5,
          "x": 2,
          "y": 2
        }
      },
      "edges": {
        "color": {
          "color": "#667eea",
          "highlight": "#764ba2",
          "hover": "#764ba2",
          "inherit": false,
          "opacity": 0.8
        },
        "font": {
          "color": "#333333",
          "size": 12,
          "face": "arial",
          "background": "rgba(255, 255, 255, 0.8)",
          "strokeWidth": 0,
          "align": "middle"
        },
        "arrows": {
          "to": {
            "enabled": true,
            "scaleFactor": 0.8,
            "type": "arrow"
          }
        },
        "smooth": {
          "enabled": true,
          "type": "dynamic",
          "roundness": 0.5
        },
        "shadow": {
          "enabled": true,
          "color": "rgba(0,0,0,0.1)",
          "size": 3,
          "x": 1,
          "y": 1
        },
        "width": 2
      },
      "interaction": {
        "dragNodes": true,
        "dragView": true,
        "hideEdgesOnDrag": false,
        "hideEdgesOnZoom": false,
        "hideNodesOnDrag": false,
        "hover": true,
        "hoverConnectedEdges": true,
        "keyboard": {
          "enabled": true,
          "speed": {
            "x": 10,
            "y": 10,
            "zoom": 0.02
          },
          "bindToWindow": true
        },
        "multiselect": true,
        "navigationButtons": true,
        "selectable": true,
        "selectConnectedEdges": true,
        "tooltipDelay": 300,
        "zoomView": true
      },
      "manipulation": {
        "enabled": false
      }
    }
    """)

    # Add nodes with modern colors
    node_colors = ["#667eea", "#764ba2", "#f093fb", "#f5576c", "#4facfe", "#00f2fe", "#43e97b", "#38f9d7"]
    for i, node in enumerate(graph["nodes"]):
        color = node_colors[i % len(node_colors)]
        net.add_node(
            node["id"], 
            label=node.get("label", node["id"]),
            color=color,
            title=f"ID: {node['id']}\nType: {node.get('type', 'Unknown')}"
        )

    # Add edges with labels
    for edge in graph["edges"]:
        net.add_edge(
            edge["from_id"], 
            edge["to_id"], 
            label=edge.get("type", ""),
            title=f"From: {edge['from_id']}\nTo: {edge['to_id']}\nType: {edge.get('type', '')}"
        )

    net.save_graph("graph.html")

    HtmlFile = open("graph.html", "r", encoding="utf-8")
    components.html(HtmlFile.read(), height=500)

# Initialize session state for chat
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_graph" not in st.session_state:
    st.session_state.current_graph = None
if "processing" not in st.session_state:
    st.session_state.processing = False

# Header
st.markdown("""
<div class="main-header">
    <div style="font-size: 1.5rem; opacity: 0.8; margin-bottom: 0.5rem;">🚀 Dodge AI</div>
    <div class="main-title">🔍 Graph Query System</div>
    <div class="subtitle">Next-gen AI-powered business intelligence for enterprise data exploration</div>
</div>
""", unsafe_allow_html=True)

# AI Assistant at top
st.markdown('<div class="chat-card" style="margin-bottom: 2rem;">', unsafe_allow_html=True)
st.markdown('<div class="card-title"><span class="card-icon">💬</span>AI Assistant</div>', unsafe_allow_html=True)

# Chat messages container
chat_container = st.container()
with chat_container:
    st.markdown('<div class="chat-messages">', unsafe_allow_html=True)
    for message in st.session_state.messages:
        if message["role"] == "user":
            st.markdown(f'<div class="message user-message"><span class="message-icon">👤</span>{message["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="message ai-message"><span class="message-icon">🤖</span>{message["content"]}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# Input section
st.markdown('<div class="input-container">', unsafe_allow_html=True)
with st.form(key="query_form", clear_on_submit=True):
    question = st.text_input("Ask your query...", placeholder="e.g., Show me orders for customer ABC123", label_visibility="collapsed")
    submit_button = st.form_submit_button(
        "🚀 Send Query", 
        use_container_width=True,
        disabled=st.session_state.processing
    )

if submit_button and question.strip() and not st.session_state.processing:
    # Add user message
    st.session_state.messages.append({"role": "user", "content": question})
    
    # Set processing state
    st.session_state.processing = True
    
    with st.spinner("🔄 Analyzing your query..."):
        try:
            result = process_query(question)
            
            # Add AI response
            st.session_state.messages.append({"role": "assistant", "content": result["answer"]})
            
            # Update graph
            st.session_state.current_graph = result["graph"]
            
            # Rerun to update UI
            st.rerun()
            
        except Exception as e:
            st.session_state.messages.append({"role": "assistant", "content": f"❌ Error: {str(e)}"})
            st.rerun()
    
    # Reset processing state
    st.session_state.processing = False

st.markdown('</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Graph visualization below
st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
st.markdown('<div class="card-title"><span class="card-icon">📊</span>Graph View</div>', unsafe_allow_html=True)

if st.session_state.current_graph:
    show_graph(st.session_state.current_graph)
else:
    st.info("💡 Submit a query to visualize the graph")

st.markdown('</div>', unsafe_allow_html=True)
