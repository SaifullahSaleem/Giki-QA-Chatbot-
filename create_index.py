from pinecone import Pinecone, ServerlessSpec
from config import PINECONE_API_KEY, PINECONE_ENVIRONMENT, PINECONE_INDEX_NAME

pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

if PINECONE_INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=384,
        metric='euclidean',
        spec=ServerlessSpec(cloud='aws', region='us-east-1')  # Use us-east-1 for free plan
    )
    print(f"Index {PINECONE_INDEX_NAME} created.")
else:
    print(f"Index {PINECONE_INDEX_NAME} already exists.")
