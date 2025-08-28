import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

from graph import Graph
from vec_database import get_collection_for_case
import html

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@dataclass
class ChatState:
    awaiting_input: bool = True  # Ожидание ввода ИНН или номера дела
    awaiting_loaded_choice: bool = False  # Ожидание выбора "загружено или нет"
    ready: bool = False
    case_number: Optional[str] = None
    collection_name: Optional[str] = None  # Текущая коллекция для дела


class BotService:
    def __init__(self) -> None:
        self.chat_id_to_state: Dict[int, ChatState] = {}
        self.graph = Graph()

    def get_state(self, chat_id: int) -> ChatState:
        if chat_id not in self.chat_id_to_state:
            self.chat_id_to_state[chat_id] = ChatState()
        return self.chat_id_to_state[chat_id]


service = BotService()

def format_html(text: str) -> str:
    safe = html.escape(text or "")
    import re
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe

def get_loaded_choice_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Да, уже загружены", callback_data="loaded_yes")],
        [InlineKeyboardButton(text="Нет, нужно загрузить", callback_data="loaded_no")],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Полностью сбрасываем состояние для нового сеанса
    state = ChatState()
    state.awaiting_input = True  
    service.chat_id_to_state[chat_id] = state
    
    # Сбрасываем состояние графа для этого чата
    service.graph.reset_state_for_chat(chat_id)
    
    logging.info(f"Бот: Состояние сброшено для чата {chat_id} через /start, awaiting_input={state.awaiting_input}")
    
    await update.message.reply_text(
        "Добро пожаловать! Введите ИНН организации или номер дела (например, А40-312285):"
    )


async def change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для смены дела - сбрасывает состояние и позволяет ввести новое дело."""
    chat_id = update.effective_chat.id
    
    # Полностью сбрасываем состояние для нового дела
    state = ChatState()
    state.awaiting_input = True  # Явно устанавливаем флаг ожидания ввода
    service.chat_id_to_state[chat_id] = state
    
    # Сбрасываем состояние графа для этого чата
    service.graph.reset_state_for_chat(chat_id)
    
    logging.info(f"Бот: Состояние сброшено для чата {chat_id}, awaiting_input={state.awaiting_input}")
    
    await update.message.reply_text(
        "Состояние сброшено! Введите ИНН организации или номер дела для нового дела (например, А40-312285):"
    )


async def on_loaded_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    state = service.get_state(chat_id)

    if query.data == "loaded_yes":
        logging.info(f"Бот: Пользователь выбрал 'уже загружены' для чата {chat_id}")
        state.ready = True
        state.awaiting_loaded_choice = False
        logging.info(f"Бот: Состояние чата {chat_id}: ready={state.ready}, awaiting_loaded_choice={state.awaiting_loaded_choice}")
        await query.edit_message_text(text="Материалы уже загружены. Теперь вы можете задавать вопросы по делу.")
        return

    if query.data == "loaded_no":
        logging.info(f"Бот: Пользователь выбрал 'нужно загрузить' для чата {chat_id}, дело: {state.case_number}")
        state.ready = False
        state.awaiting_loaded_choice = False
        await query.edit_message_text(text="Загружаю материалы дела, подождите…")

        loop = asyncio.get_running_loop()
        try:
            logging.info(f"Бот: Запускаю загрузку материалов для дела '{state.case_number}'")
            result = await loop.run_in_executor(None, lambda: service.graph.invoke(state.case_number))
            state.ready = True
            logging.info(f"Бот: Материалы успешно загружены для чата {chat_id}")
            await query.message.reply_text("Материалы загружены. Теперь вы можете задавать вопросы по делу.")
        except Exception as e:
            logging.exception("Ошибка загрузки материалов")
            await query.message.reply_text(f"Ошибка загрузки: {e}")
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    state = service.get_state(chat_id)

    # Если пользователь ввел команду /start или /change в тексте, сбрасываем состояние
    if text.lower() in ["/start", "/change"]:
        # Полностью сбрасываем состояние
        state = ChatState()
        state.awaiting_input = True  # Явно устанавливаем флаг ожидания ввода
        service.chat_id_to_state[chat_id] = state
        
        # Сбрасываем состояние графа для этого чата
        service.graph.reset_state_for_chat(chat_id)
        
        command_name = "start" if text.lower() == "/start" else "change"
        logging.info(f"Бот: Состояние сброшено для чата {chat_id} через {command_name}, awaiting_input={state.awaiting_input}")
        await update.message.reply_text(
            "Состояние сброшено! Введите ИНН организации или номер дела для нового дела (например, А40-312285):"
        )
        return

    if state.awaiting_input:
        logging.info(f"Бот: Обрабатываю ввод дела '{text}' для чата {chat_id}")
        
        state.case_number = text
        state.awaiting_input = False
        state.awaiting_loaded_choice = True
        
        # Определяем коллекцию для дела
        case_input = text.strip().upper()
        collection_name = get_collection_for_case(case_input)
        state.collection_name = collection_name
        
        logging.info(f"Бот: Определена коллекция для дела '{text}': {collection_name}")
        logging.info(f"Бот: Состояние чата {chat_id}: awaiting_input={state.awaiting_input}, awaiting_loaded_choice={state.awaiting_loaded_choice}")
        
        await update.message.reply_text(
            f"Дело '{text}' определено. Дела уже загружены?", 
            reply_markup=get_loaded_choice_keyboard()
        )
        return

    if state.awaiting_loaded_choice:
        await update.message.reply_text("Пожалуйста, используйте кнопки для выбора.")
        return

    if state.ready:
        logging.info(f"Бот: Обрабатываю вопрос '{text}' для коллекции '{state.collection_name}' (чат {chat_id})")
        search_message = await update.message.reply_text("Обрабатываю ваш запрос...")
        
        try:
            # Для последующих запросов используем Graph с уже загруженной коллекцией
            result = await asyncio.get_running_loop().run_in_executor(
                None, 
                lambda: service.graph.invoke(text, existing_collection=state.collection_name)
            )
            answer = result["messages"][-1].content
            logging.info(f"Бот: Получен ответ длиной {len(answer)} символов для чата {chat_id}")
            
            try:
                await search_message.delete()
            except Exception as delete_error:
                logging.warning(f"Не удалось удалить сообщение о поиске: {delete_error}")
            
            await update.message.reply_text(format_html(answer)[:4000], parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.exception("Ошибка анализа дела")
            logging.error(f"Бот: Ошибка при обработке вопроса '{text}' для чата {chat_id}: {e}")
            
            # Удаляем сообщение о поиске с обработкой ошибок
            try:
                await search_message.delete()
            except Exception as delete_error:
                logging.warning(f"Не удалось удалить сообщение о поиске: {delete_error}")
            
            await update.message.reply_text(f"Ошибка анализа: {e}")
        return

    # Если не в каком-то из состояний - просим ввести ИНН или номер дела
    logging.warning(f"Бот: Неопределенное состояние для чата {chat_id}: awaiting_input={state.awaiting_input}, awaiting_loaded_choice={state.awaiting_loaded_choice}, ready={state.ready}")
    await update.message.reply_text("Введите ИНН организации или номер дела (например, А40-312285):")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Команды:\n/start — начать работу\n/change — сменить дело\n/help — помощь\n\nКак использовать:\n1. Введите ИНН или номер дела\n2. Выберите, загружены ли документы\n3. Задавайте вопросы по делу\n\nДля смены дела используйте /change"
    )


def build_app(token: str) -> Application:
    return (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )


def run() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в переменных окружения")

    app = build_app(token)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_loaded_choice, pattern="^loaded_(yes|no)$"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))

    logging.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    run()


