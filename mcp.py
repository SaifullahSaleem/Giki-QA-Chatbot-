# mcp.py

"""
A minimal MCP wrapper that forwards MCP-style requests to the existing chat pipeline
and returns an MCP-compatible response.

Usage:
  python mcp.py --port 5001
"""

import json
import argparse
from flask import Flask, request, jsonify

try:
    from chatbot.app import process_query  # type: ignore
except Exception:
    # Fallback placeholder if import path is different
    def process_query(query: str) -> str:
        return f"<p>Placeholder MCP response for: {query}</p>"

app = Flask(__name__)

@app.route("/mcp", methods=["POST"])
def mcp_endpoint():
    payload = request.get_json(force=True) or {}
    query = payload.get("input") or payload.get("query") or ""
    if not query:
        return jsonify({"status": "error", "error": "No query provided"}), 400

    try:
        answer_html = process_query(query)
        response = {
            "status": "ok",
            "answer": answer_html,
            "context": None
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001, help="Port to run MCP server on")
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=False)
