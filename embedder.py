from langchain_gigachat.embeddings import GigaChatEmbeddings
import os 
from dotenv import load_dotenv

load_dotenv()

def embedder() -> GigaChatEmbeddings:
    return GigaChatEmbeddings(
        credentials=os.getenv("GIGACHAT_API_KEY"),
        scope="GIGACHAT_API_CORP",
        verify_ssl_certs=False
    )
