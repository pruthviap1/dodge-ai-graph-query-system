import streamlit as st
import subprocess
import time
import requests

# Start backend
subprocess.Popen(["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"])
time.sleep(3)

st.title("AI Graph Query System")

question = st.text_input("Ask your query")

if st.button("Submit"):
    try:
        response = requests.post(
            "http://localhost:8000/api/query",
            json={"question": question}
        )
        data = response.json()

        st.subheader("Answer")
        st.write(data.get("answer"))

        st.subheader("Graph")
        st.json(data.get("graph"))

    except Exception as e:
        st.error(f"Error: {e}")
