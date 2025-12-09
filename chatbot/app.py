import sys
import os
import time
import traceback
import markdown
from flask import Flask, request, jsonify, render_template
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
import requests

# ===== CONFIG =====
# ensure parent folder is on path so `config.py` can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import PINECONE_API_KEY, PINECONE_ENVIRONMENT, PINECONE_INDEX_NAME

GROQ_API_KEY = "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"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "groq/compound-mini"

# ===== TUNABLE LIMITS / RETRY =====
MAX_MATCH_TEXT_CHARS = 800       # truncate each Pinecone match to this many chars
MAX_CONTEXT_CHARS = 2000         # total context chars sent to LLM
DEFAULT_TOP_K = 3                # default number of matches to fetch from Pinecone
LLM_MAX_TOKENS = 250             # max tokens requested from LLM
RETRY_MAX = 3                    # number of retries for rate-limits / transient errors
RETRY_BASE_DELAY = 1.0           # base delay in seconds for exponential backoff

# ===== FLASK SETUP =====
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# ===== MODEL & PINECONE INIT =====
print("Loading embedding model...")
hf_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Embedding model loaded.")

print("Initializing Pinecone client...")
pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

# tolerant check for index existence (handle different wrapper return types)
try:
    idxs = pc.list_indexes()
    if hasattr(idxs, "names"):
        index_names = idxs.names()
    else:
        index_names = idxs if isinstance(idxs, list) else list(idxs)
except Exception:
    # fall back to calling list_indexes() and trusting user set value
    try:
        index_names = pc.list_indexes()
    except Exception as e:
        print("Error checking Pinecone indexes:", e)
        raise

if PINECONE_INDEX_NAME not in index_names:
    raise ValueError(f"Index {PINECONE_INDEX_NAME} does not exist. Found indexes: {index_names}")

index = pc.Index(PINECONE_INDEX_NAME)
print(f"Pinecone index '{PINECONE_INDEX_NAME}' initialized.")


# ===== HELPER FUNCTIONS =====
def get_embedding(text):
    print(f"Generating embedding for query: {text[:50]}...")
    return hf_model.encode(text).tolist()


def semantic_search(query, top_k=DEFAULT_TOP_K):
    """
    Run semantic search with a safe default top_k to avoid huge contexts.
    """
    print(f"Running semantic search for query: {query} (top_k={top_k})")
    query_emb = get_embedding(query)
    results = index.query(vector=query_emb, top_k=top_k, include_metadata=True)
    # adapt to possible return shapes
    matches = results.get('matches', []) if isinstance(results, dict) else getattr(results, "matches", []) or []
    print(f"Found {len(matches)} Pinecone matches.")
    return matches


def ask_groq_llm(context, question, model=GROQ_MODEL,
                 max_tokens=LLM_MAX_TOKENS, temperature=0.7, max_context_chars=MAX_CONTEXT_CHARS):
    """
    Send request to Groq LLM with:
      - context truncated to `max_context_chars`
      - retry on 429 with exponential backoff
      - on 413 (payload too large) try with reduced context
    """
    if len(context) > max_context_chars:
        print(f"Context too long ({len(context)} chars), truncating to {max_context_chars} chars.")
        context = context[-max_context_chars:]

    prompt_template = "Answer the user's question based on the following context:\n{context}\n\nQuestion: {question}\nAnswer:"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # prepare the JSON payload (we will modify messages if we retry with shorter context)
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt_template.format(context=context, question=question)}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    attempt = 0
    while attempt <= RETRY_MAX:
        try:
            resp = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            print("Received Groq LLM response.")
            return result["choices"][0]["message"]["content"].strip()
        except requests.exceptions.HTTPError as http_err:
            status = getattr(http_err.response, "status_code", None)
            print(f"Groq HTTP error (status={status}): {http_err}")
            # If payload too large, try shrinking context and retry once
            if status == 413:
                # shrink context and retry, but don't loop forever
                if max_context_chars <= 200:
                    # cannot shrink further, re-raise
                    raise
                print("Received 413 Payload Too Large. Reducing context and retrying...")
                max_context_chars = max(200, max_context_chars // 2)
                # truncate context and update payload
                truncated_context = context[-max_context_chars:]
                data["messages"][1]["content"] = prompt_template.format(context=truncated_context, question=question)
                attempt += 1
                continue
            # Too Many Requests -> exponential backoff
            if status == 429:
                backoff = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"429 Too Many Requests. Backing off for {backoff:.1f}s (attempt {attempt+1}/{RETRY_MAX})")
                time.sleep(backoff)
                attempt += 1
                continue
            # other HTTP errors -> re-raise
            raise
        except requests.exceptions.RequestException as e:
            # network / timeout -> backoff and retry
            print("Network/Request error to Groq:", e)
            backoff = RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(backoff)
            attempt += 1
            continue

    # failed after retries
    raise RuntimeError("Failed to get response from Groq LLM after retries.")


def process_query(query: str, top_k: int = DEFAULT_TOP_K) -> str:
    """
    Build a compact context from Pinecone matches:
      - truncate each match's metadata['text'] to MAX_MATCH_TEXT_CHARS
      - join pieces and ensure total length <= MAX_CONTEXT_CHARS
    """
    if not query:
        return "No query provided."
    matches = semantic_search(query, top_k=top_k)
    if not matches:
        return "Sorry, I couldn't find any relevant information."

    pieces = []
    for m in matches:
        meta = m.get("metadata", {}) or {}
        text = meta.get("text") or meta.get("excerpt") or ""
        if not text:
            continue
        # per-match truncation
        if len(text) > MAX_MATCH_TEXT_CHARS:
            text = text[:MAX_MATCH_TEXT_CHARS]
        pieces.append(text)

    # join and ensure total context length limit (prefer recent tail)
    context = "\n\n".join(pieces)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[-MAX_CONTEXT_CHARS:]

    try:
        llm_answer = ask_groq_llm(context, query)
    except Exception as e:
        # Log the error, and return a friendly message
        print("ERROR calling Groq LLM:", e)
        traceback.print_exc()
        return "Sorry — the language model request failed (rate limit or payload size). Try again with a shorter question."

    formatted_answer = markdown.markdown(llm_answer, extensions=['tables', 'fenced_code'])
    return formatted_answer


# ===== ROUTES =====
@app.route("/", methods=["GET"])
def index_view():
    try:
        return render_template("index.html")
    except Exception as e:
        print("ERROR rendering index.html:", e)
        traceback.print_exc()
        return "Internal Server Error", 500


@app.route("/chat", methods=["POST"])
def chat():
    try:
        payload = request.get_json(force=True) or {}
        user_query = payload.get("query", "")
        # allow client to pass top_k optionally in JSON payload
        top_k = int(payload.get("top_k", DEFAULT_TOP_K))
        print(f"User asked: {user_query} (top_k={top_k})")
        answer = process_query(user_query, top_k=top_k)
        return jsonify({"answer": answer})
    except Exception as e:
        print("ERROR in /chat:", e)
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
