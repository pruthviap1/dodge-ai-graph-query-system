import streamlit as st
from backend.app.query_service import process_query
from pyvis.network import Network
import streamlit.components.v1 as components

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

st.title("AI Graph Query System")

question = st.text_input("Ask your query")

if st.button("Submit"):
    try:
        result = process_query(question)

        st.subheader("Answer")
        st.write(result["answer"])

        st.subheader("Graph Visualization")
        show_graph(result["graph"])

    except Exception as e:
        st.error(f"Error: {e}")
