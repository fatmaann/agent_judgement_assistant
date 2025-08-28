from langchain_chroma import Chroma
from langchain_core.documents import Document
from typing import List
from pdf_chunker import load_docs
from embedder import embedder
import os
from dotenv import load_dotenv
import logging
import hashlib
import time
import re

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def generate_id(text: str) -> str:
    """Генерируем ID для документа на основе его содержимого."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def normalize_collection_name(name: str) -> str:
    """Нормализует имя коллекции: создает хеш на основе ввода для уникальности."""
    # Создаем хеш от имени для уникальности и совместимости
    import hashlib
    hash_object = hashlib.md5(name.encode('utf-8'))
    hash_hex = hash_object.hexdigest()[:12]  # Берем первые 12 символов хеша
    
    # Убираем спецсимволы, оставляем только буквы, цифры, дефисы и подчеркивания
    clean_name = re.sub(r'[^a-zA-Z0-9\-_]', '_', name)
    clean_name = re.sub(r'_+', '_', clean_name)
    clean_name = clean_name.strip('_')
    
    # Если имя слишком длинное, обрезаем и добавляем хеш
    if len(clean_name) > 30:
        clean_name = clean_name[:30]
    
    # Формируем финальное имя: префикс + хеш
    if clean_name:
        normalized = f"case_{clean_name}_{hash_hex}"
    else:
        normalized = f"case_{hash_hex}"
    
    return normalized


def load_to_collection(docs: List[Document], collection_name: str) -> Chroma:
    """Загружает документы в конкретную коллекцию Chroma."""
    logging.info(f'Запуск функции load_to_collection для коллекции: {collection_name}')
    embedder_func = embedder()
    
    # Создаем или открываем коллекцию
    vec_db = Chroma(
        collection_name=collection_name,
        persist_directory="./chroma_db",
        embedding_function=embedder_func
    )
    
    if docs:
        ids = [generate_id(doc.page_content) for doc in docs]
        id_to_doc = {}
        for doc, id_ in zip(docs, ids):
            if id_ not in id_to_doc:
                id_to_doc[id_] = doc
        unique_ids = list(id_to_doc.keys())

        # Проверяем существующие документы в коллекции
        try:
            res = vec_db.get(ids=unique_ids)
            existing_ids = set(res.get('ids', []) or [])
        except Exception:
            existing_ids = set()

        new_docs = []
        new_ids = []
        for id_, doc in id_to_doc.items():
            if id_ in existing_ids:
                continue
            new_docs.append(doc)
            new_ids.append(id_)
            
        if new_docs:
            logging.info(f'Добавляю {len(new_docs)} новых документов в коллекцию {collection_name}...')
            batch_size = 50
            for i in range(0, len(new_docs), batch_size):
                chunk_docs = new_docs[i:i+batch_size]
                chunk_ids = new_ids[i:i+batch_size]
                retries = 3
                for attempt in range(1, retries + 1):
                    try:
                        vec_db.add_documents(chunk_docs, ids=chunk_ids)
                        break
                    except Exception as e:
                        if attempt == retries:
                            logging.error(f'Не удалось добавить документы в коллекцию {collection_name} после {retries} попыток: {e}')
                            raise
                        sleep_s = 1.5 * attempt
                        logging.warning(f'Ошибка добавления батча документов в {collection_name} (попытка {attempt}/{retries}): {e}. Повтор через {sleep_s:.1f}s')
                        time.sleep(sleep_s)
        else:
            logging.info(f'Нет новых документов для добавления в коллекцию {collection_name}.')
    
    return vec_db


def get_collection_for_case(case_input: str) -> str:
    """Определяет имя коллекции на основе ввода пользователя."""
    # Нормализуем ввод
    case_input = case_input.strip().upper()
    
    # Определяем тип ввода
    if re.match(r'^\d{10}$', case_input):  # ИНН (10 цифр)
        return normalize_collection_name(f"INN_{case_input}")
    elif re.match(r'^\d{12}$', case_input):  # ИНН (12 цифр)
        return normalize_collection_name(f"INN_{case_input}")
    elif re.match(r'^[АA]\d+-\d+', case_input):  # Номер дела (А40-123456)
        return normalize_collection_name(case_input)
    else:
        # Организация или другой тип - используем как есть
        return normalize_collection_name(f"ORG_{case_input}")


def chroma_database(pdf_directory: str, collection_name: str) -> Chroma:
    """Создает или открывает коллекцию Chroma для конкретного дела."""
    logging.info(f'Запуск chroma_database для директории: {pdf_directory}, коллекция: {collection_name}')
    
    # Создаем директорию если не существует
    os.makedirs("./chroma_db", exist_ok=True)
    
    documents = load_docs(pdf_directory)
    logging.info(f'Закончил работу с обработкой чанков... Приступаю к загрузке в коллекцию {collection_name}...')
    
    vectorstorage = load_to_collection(docs=documents, collection_name=collection_name)
    return vectorstorage


def get_existing_collection(collection_name: str) -> Chroma:
    """Открывает существующую коллекцию без загрузки новых документов."""
    embedder_func = embedder()
    return Chroma(
        collection_name=collection_name,
        persist_directory="./chroma_db",
        embedding_function=embedder_func
    )

