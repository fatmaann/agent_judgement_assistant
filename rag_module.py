from langchain.retrievers.multi_query import MultiQueryRetriever
from vec_database import chroma_database, get_existing_collection
from model import SudebChatModel
import logging
import re

import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig()

def rag(user_prompt: str, collection_name: str | None = None) -> str:
    """RAG-поиск в указанной коллекции Chroma."""
    
    if not collection_name:
        raise ValueError("collection_name обязателен для RAG-поиска")
    
    logging.info(f"RAG: Ищу в коллекции: {collection_name}")
    
    try:
        # Открываем существующую коллекцию
        vectorstorage = get_existing_collection(collection_name)
        
        # Проверяем, есть ли документы в коллекции
        try:
            # Пробуем получить все документы из коллекции
            all_docs = vectorstorage.get()
            doc_count = len(all_docs.get('ids', []))
            logging.info(f"RAG: В коллекции {collection_name} найдено {doc_count} документов")
            
            if doc_count == 0:
                return f"Коллекция {collection_name} пуста. Документы не были загружены или были удалены."
                
        except Exception as e:
            logging.error(f"RAG: Ошибка при проверке коллекции {collection_name}: {e}")
            return f"Ошибка доступа к коллекции {collection_name}: {str(e)}"

        retriever = MultiQueryRetriever.from_llm(
            retriever=vectorstorage.as_retriever(search_kwargs={"k": 5}),
            llm=SudebChatModel(temperature=0)
        )

        logging.getLogger("langchain.retrievers.multi_query").setLevel(logging.INFO)

        logging.info(f"RAG: Выполняю поиск для запроса: {user_prompt}")
        rel_docs = retriever.invoke(user_prompt)
        
        logging.info(f"RAG: Найдено {len(rel_docs)} релевантных документов")

        context = ""

        for i, doc in enumerate(rel_docs):
            context += f"Документ {i+1}:\n{doc.page_content}\n\n"

        context = context.rstrip()
        context = re.sub(r'\s+', ' ', context).strip()
        
        if not context:
            return f"По запросу '{user_prompt}' в коллекции {collection_name} ничего не найдено."

        return context
        
    except Exception as e:
        logging.error(f"RAG: Ошибка при поиске в коллекции {collection_name}: {e}")
        return f"Ошибка поиска в коллекции {collection_name}: {str(e)}"
