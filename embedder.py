from sentence_transformers import SentenceTransformer

model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)

def get_embedding(text: str):
    # Nomic braucht Prefix für bessere Performance
    return model.encode(f"search_query: {text}")
