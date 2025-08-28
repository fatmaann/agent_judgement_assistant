import os
from dotenv import load_dotenv
from langchain_gigachat.chat_models import GigaChat
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

class SudebChatModel(GigaChat):
    def __init__(self, **kwargs) -> None:
        api_key = os.environ.get("GIGACHAT_API_KEY")
        scope = "GIGACHAT_API_CORP"
        verify_ssl_certs = False
        super().__init__(
            credentials=api_key,
            scope=scope,
            verify_ssl_certs=verify_ssl_certs,
            profanity_check=False,
            # timeout=300
            **kwargs
        )
    
    def analyze_case(self, user_input: str, rag_answ: str | None) -> str:

        if rag_answ == None:
            return "Не удалось получить контекст для анализа дела."
        
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", """Ты - эксперт по анализу судебных дел. Анализируй документы с заглавием «определение», «решение», «постановление».

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
Начни с краткого описания сторон и предмета спора, затем изложи ход рассмотрения по инстанциям с указанием ключевых решений и их дат."""),
                ("user", "Контекст:\n" + rag_answ + "\n\nВопрос:\n" + user_input)
            ]
        )

        analyze_case_chain = prompt | self.with_config({"temperature": 0.0})

        response = analyze_case_chain.invoke({"user_input": user_input}, profanity_check=False)

        return response.content.strip()    

if __name__ == "__main__":
    model = SudebChatModel()
    import logging
    logging.basicConfig(level=logging.INFO)
    logging.info(model.check_type_of_case("А40-312285"))