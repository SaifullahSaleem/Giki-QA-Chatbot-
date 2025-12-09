# embed.py
import sys
import os
import json
import argparse
from itertools import islice
from time import sleep

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import PINECONE_API_KEY, PINECONE_ENVIRONMENT, PINECONE_INDEX_NAME
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

# -------- configuration --------
DEFAULT_INPUT = "giki_data.json"   # adjust if your spider writes somewhere else
BATCH_SIZE = 100                    # upsert in chunks (recommended 50-200)
MAX_METADATA_SIZE = 40000           # bytes: truncate metadata (you already used 40k)
METRIC = "cosine"                   # recommended for semantic similarity
# --------------------------------

def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", "-i", default=DEFAULT_INPUT, help="Path to scraped JSON file")
    p.add_argument("--index", "-x", default=PINECONE_INDEX_NAME, help="Pinecone index name")
    p.add_argument("--batch", "-b", type=int, default=BATCH_SIZE, help="Batch size for upserts")
    p.add_argument("--metric", "-m", default=METRIC, choices=["cosine", "euclidean"], help="Distance metric")
    return p.parse_args()

# load model and pinecone client
print("Loading embedding model...")
hf_model = SentenceTransformer('all-MiniLM-L6-v2')
EMB_DIM = hf_model.get_sentence_embedding_dimension()
print(f"Embedding model loaded (dim={EMB_DIM}).")

pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

def get_embedding(text):
    return hf_model.encode(text).tolist()

def load_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def make_text_and_meta(entry):
    """
    Construct the text to embed and metadata dictionary for an entry.
    Keep metadata small and useful.
    """
    entry_type = entry.get("type", "unknown")
    meta = {
        "type": entry_type,
        "source": entry.get("source") or entry.get("url") or "",
        "url": entry.get("url", ""),
    }

    if entry_type == "faculty_profile":
        name = entry.get("name", "")
        research = entry.get("research", "") or entry.get("research_areas", "")
        text = f"Faculty Name: {name}. Research: {research}"
        meta["name"] = name
        meta["research"] = research[:2000]  # keep meta short
    elif entry_type == "research_project":
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        text = f"Project Title: {title}. Summary: {summary}"
        meta["title"] = title
    elif entry_type == "news_item":
        title = entry.get("title", "")
        excerpt = entry.get("excerpt", "")
        text = f"News: {title}. {excerpt}"
        meta["title"] = title
    elif entry_type in ("lab_or_group",):
        name = entry.get("name", "")
        desc = entry.get("description", "")
        text = f"{name}. {desc}"
        meta["name"] = name
    else:
        # generic fallback: prefer 'content' or 'title'
        text = entry.get("content") or entry.get("title") or ""
        meta["title"] = entry.get("title", "")[:200]

    return text, meta

def truncate_metadata_field(s, max_bytes=MAX_METADATA_SIZE):
    if not isinstance(s, str):
        s = str(s)
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    truncated = b[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")

def batched(iterable, n):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, n))
        if not chunk:
            break
        yield chunk

def main():
    args = get_args()
    input_file = args.input
    idx_name = args.index
    batch_size = args.batch
    metric = args.metric

    print(f"Loading data from {input_file} ...")
    data = load_data(input_file)
    print(f"Loaded {len(data)} items.")

    # Prepare vectors: compute text and metadata
    items = []
    for i, entry in enumerate(data):
        text, meta = make_text_and_meta(entry)
        # include truncated full text in metadata under 'text' but limit bytes
        meta_text = truncate_metadata_field(text, max_bytes=MAX_METADATA_SIZE)
        meta["text"] = meta_text
        # set stable id if url present else numeric id
        id_val = entry.get("url") or f"giki-{i}"
        items.append((id_val, text, meta))

    # Create index if missing
    existing = pc.list_indexes().names()
    if idx_name not in existing:
        print(f"Index '{idx_name}' not found. Creating with dim={EMB_DIM}, metric={metric} ...")
        pc.create_index(name=idx_name, dimension=EMB_DIM, metric=metric)
        print("Index created.")
    else:
        print(f"Index '{idx_name}' already exists.")

    index = pc.Index(idx_name)

    # Upsert in batches
    total = 0
    for batch in batched(items, batch_size):
        ids = [str(x[0]) for x in batch]
        texts = [x[1] for x in batch]
        metas = [x[2] for x in batch]

        # compute embeddings for batch (model accepts list)
        embeddings = hf_model.encode(texts).tolist()

        vectors = []
        for _id, emb, meta in zip(ids, embeddings, metas):
            # ensure metadata fields are small; truncate long meta fields
            # e.g., meta["text"] already truncated above
            vectors.append((_id, emb, meta))

        # Upsert to Pinecone (retry briefly on transient failures)
        try:
            index.upsert(vectors)
            total += len(vectors)
            print(f"Upserted {len(vectors)} vectors (total so far: {total}).")
        except Exception as e:
            print("Upsert failed for batch:", e)
            # tiny backoff & continue
            sleep(1)

    print(f"Finished. Upserted approximately {total} vectors into index '{idx_name}'.")

if __name__ == "__main__":
    main()
