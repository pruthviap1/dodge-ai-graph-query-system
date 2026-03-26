import streamlit as st
from backend.app.query_service import process_query

st.title("AI Graph Query System")

question = st.text_input("Ask your query")

if st.button("Submit"):
    try:
        result = process_query(question)

        st.subheader("Answer")
        st.write(result["answer"])

        st.subheader("Graph")
        st.json(result["graph"])

    except Exception as e:
        st.error(f"Error: {e}")
