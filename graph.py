from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.graph.message import AnyMessage
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langchain_core.prompts import ChatPromptTemplate

from typing import List, Annotated, Optional, Literal, TypedDict
import os
import uuid
import re
import logging

from model import SudebChatModel
from parser import download_by_query
from rag_module import rag
from vec_database import get_collection_for_case, chroma_database

def save_graph_png(graph, filename='langgraph_workflow.png'):
    try:
        png_data = graph.get_graph().draw_mermaid_png(
            output_file_path=filename,
            background_color='white',
            padding=20
        )
        logging.info(f"Граф сохранен в {filename}")
        return filename
    except Exception as e:
        logging.error(f"Ошибка сохранения графа: {e}")

class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    rag_answer: Optional[str]
    case_type: Optional[str]  # "ИНН", "Номер дела", "Организация"
    collection_name: Optional[str]  # Имя коллекции для текущего дела
    flag: bool  # True если документы уже загружены

class Graph:
    def __init__(self) -> None:
        self.model = SudebChatModel()
        self.memory = MemorySaver()
        self.config = {"configurable": {"thread_id": "1"}}
        self.graph = self._build_graph(State)

    def _check_case(self, state: State):
        """Автоматически определяет тип ввода: ИНН, номер дела или организация."""
        message_for_check = state["messages"][-1].content
        
        # Используем LLM для определения типа ввода
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "Твоя задача - определять, что пришло: ИНН, Организация или Номер дела. Выбери одно из этих трех значений и пришли это значение."),
                ("user", message_for_check)
            ]
        )
        choose_case_chain = prompt | self.model
        response = choose_case_chain.invoke({"user_input": message_for_check}, profanity_check=False)
        case_type = response.content.strip()
        
        # Определяем имя коллекции на основе ввода и определенного типа
        case_input = message_for_check.strip().upper()
        collection_name = get_collection_for_case(case_input)
        
        logging.info(f"LLM определил тип: {case_type}, коллекция: {collection_name}")
        
        return {
            "case_type": case_type,
            "collection_name": collection_name
        }

    def _search(self, state: State):
        """Загружает документы в соответствующую коллекцию."""
        query = state["messages"][-1].content
        case_type = state.get("case_type", "Номер дела")
        collection_name = state.get("collection_name")
        
        if not collection_name:
            raise ValueError("Не удалось определить имя коллекции")
        
        # Создаем папку для PDF под это дело
        pdf_dir = os.path.join(os.path.abspath("pdfs"), collection_name)
        os.makedirs(pdf_dir, exist_ok=True)
        
        logging.info(f"Загружаю документы для {case_type}: {query} в коллекцию {collection_name}")
        
        # Загружаем документы
        download_by_query(query=query, output_folder=pdf_dir, choose_case=case_type)
        
        # Индексируем документы в коллекцию
        chroma_database(pdf_directory=pdf_dir, collection_name=collection_name)
        
        return {"flag": True}

    def _rag(self, state: State):
        """Выполняет RAG-поиск в коллекции дела."""
        last_message = state["messages"][-1].content
        collection_name = state.get("collection_name")
        
        logging.info(f"Graph _rag: Запрос '{last_message}' для коллекции '{collection_name}'")
        
        if not collection_name:
            logging.warning("Graph _rag: Не удалось определить коллекцию для поиска")
            return {"rag_answer": "Не удалось определить коллекцию для поиска."}
        
        try:
            rag_answer = rag(user_prompt=last_message, collection_name=collection_name)
            logging.info(f"Graph _rag: Получен ответ длиной {len(rag_answer)} символов")
            return {"rag_answer": rag_answer}
        except Exception as e:
            logging.error(f"Graph _rag: Ошибка RAG-поиска: {e}")
            return {"rag_answer": f"Ошибка поиска в базе данных: {str(e)}"}

    def _generate(self, state: State):
        """Генерирует ответ на основе RAG-результатов."""
        messages = state["messages"]
        rag_answer = state["rag_answer"]

        logging.info(f"Graph _generate: RAG ответ: {rag_answer[:200]}...")

        if not rag_answer or "Ошибка" in rag_answer:
            logging.warning("Graph _generate: Не удалось получить контекст для анализа дела")
            return {"messages": "Не удалось получить контекст для анализа дела."}

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", """
                Ты - эксперт по анализу судебных дел. 
                Анализируй документы с заглавием «определение», «решение», «постановление».

                ## СТРУКТУРА АНАЛИЗА ПО ИНСТАНЦИЯМ:
                1. **Первая инстанция** - Арбитражные суды субъектов РФ (АС [субъект])
                2. **Апелляционная инстанция** - Арбитражные апелляционные суды (номер суда)
                3. **Кассационная инстанция** - Арбитражные суды округов или ВС РФ
                
                ## ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ ОТВЕТА:
                • **Стороны**: истец и ответчик (из преамбулы)
                • **Предмет спора**: суть требований (из преамбулы)  
                • **Сумма требований**: стоимостное выражение (из преамбулы)
                • **Вердикт**: ключевое решение (после слов «Решил»/«Постановил»)
                • **Суд и дата**: название суда и дата принятия решения
                
                ## ПРАВИЛА АНАЛИЗА:
                - Анализируй документы в хронологическом порядке по инстанциям
                - Если решений нет в инстанции - укажи "не вынесены на текущую дату"
                - При множественных решениях - каждое отдельно в хронологии
                - Учитывай возможность отмены/возврата дела на новое рассмотрение
                - Используй ТОЛЬКО информацию из RAG-контекста
                - Пиши простым языком без сложных конструкций
                - Не используй markdown, только обычный текст с абзацами
                
                ## ФОРМАТ ОТВЕТА:
                Начни с краткого описания сторон и предмета спора, 
                затем изложи ход рассмотрения по инстанциям с указанием ключевых решений и их дат.
                """),
                ("user", "Контекст:\n" + rag_answer + "\n\nВопрос:\n" + str(messages[-1].content))
            ]
        )

        analyze_case_chain = prompt | self.model.with_config({"temperature": 0.0})
        response = analyze_case_chain.invoke({"messages": messages}, profanity_check=False)

        return {"messages": response.content.strip()}

    def _route_by_flag(self, state: State) -> Command[Literal["check_case", "rag"]]:
        """Маршрутизация: определяет, нужно ли загружать новое дело или использовать существующее."""
        flag = state.get("flag", False)
        current_collection = state.get("collection_name", "")
        last_message = state["messages"][-1].content.strip()
        
        logging.info("*" * 50)
        logging.info(f"Флаг готовности: {flag}")
        logging.info(f"Текущая коллекция: {current_collection}")
        logging.info(f"Последнее сообщение: {last_message}")
        logging.info("*" * 50)

        # Если флаг установлен и есть коллекция - используем существующую
        if flag and current_collection:
            logging.info("Используем существующую коллекцию")
            return Command(update={}, goto="rag")
        
        # Проверяем, является ли ввод похожим на номер дела, ИНН или организацию
        is_likely_new_case = False
        
        # Паттерны для определения нового дела
        case_patterns = [
            r'^\d{10}$',  # ИНН 10 цифр
            r'^\d{12}$',  # ИНН 12 цифр
            r'^[АA]\d+-\d+',  # Номер дела А40-123456
            r'^[АA]\d+/\d+',  # Номер дела А40/123456
        ]
        
        for pattern in case_patterns:
            if re.match(pattern, last_message.upper()):
                is_likely_new_case = True
                break
        
        # Если ввод похож на новое дело, загружаем
        if is_likely_new_case:
            logging.info("Обнаружен новый случай - загружаем документы")
            return Command(update={"flag": False, "collection_name": None}, goto="check_case")
        
        # По умолчанию - загружаем новое дело
        logging.info("Загружаем новое дело")
        return Command(update={"flag": False, "collection_name": None}, goto="check_case")

    def _build_graph(self, state: State):
        workflow = StateGraph(state)

        workflow.add_node("route_by_flag", self._route_by_flag)
        workflow.add_node("check_case", self._check_case)
        workflow.add_node("search", self._search)
        workflow.add_node("rag", self._rag)
        workflow.add_node("generate", self._generate)

        workflow.add_edge(START, "route_by_flag")

        workflow.add_edge("check_case", "search")
        workflow.add_edge("search", "rag")
        workflow.add_edge("rag", "generate")

        workflow.add_edge("generate", END)

        return workflow.compile(checkpointer=self.memory)

    def reset_state_for_chat(self, chat_id):
        """Сбрасывает состояние графа для конкретного чата."""
        import uuid
        # Создаем новый thread_id для сброса состояния
        new_thread_id = str(uuid.uuid4())
        self.config = {"configurable": {"thread_id": new_thread_id}}
        logging.info(f"Graph: Состояние сброшено для чата {chat_id}, новый thread_id: {new_thread_id}")

    def invoke(self, user_prompt, reset_state=False, existing_collection=None):
        save_graph_png(self.graph)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "Ты - текстовый агент, который должен помогать судьям."),
                ("user", "{user_prompt}")
            ]
        )

        message = prompt.invoke({"user_prompt": user_prompt}, profanity_check=False)
        message = message.to_messages()
        logging.info(f"Graph invoke: Сообщение: {message}")

        # Если нужно сбросить состояние, создаем новый конфиг
        if reset_state:
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        else:
            config = self.config

        # Если передана существующая коллекция, инициализируем состояние с ней
        initial_state = {}
        if existing_collection:
            initial_state = {
                "collection_name": existing_collection,
                "flag": True  # Указываем, что документы уже загружены
            }

        return self.graph.invoke(
            {"messages": message, **initial_state},
            config=config
        )

if __name__ == "__main__":
    graph = Graph()
    user_input = input("Ваш текст: ")
    while user_input != "0":
        logging.info(graph.invoke(user_input)["messages"][-1].content)
        logging.info("*"*50)
        user_input = input("Ваш текст: ")

#А40-312285