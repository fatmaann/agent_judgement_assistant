from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import os
from dotenv import load_dotenv
from typing import List

load_dotenv()

def load_docs(path_to_pdf_folder : str) -> List[Document]:
    docs = []

    for file in os.listdir(path_to_pdf_folder):
        if file.endswith(".pdf"):
            filepath = os.path.join(path_to_pdf_folder, file)
            pdf_loader = PyMuPDFLoader(filepath)

            pdf_documents = pdf_loader.load()
            docs.extend(pdf_documents)

    char_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-4",
        chunk_size=512,
        chunk_overlap=100
    )
    small_chunks = char_splitter.split_documents(docs)

    return small_chunks
