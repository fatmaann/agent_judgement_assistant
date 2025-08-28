from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import time
import re
import logging
from urllib.parse import unquote, urlparse
from datetime import datetime, timedelta

def download_by_query(query, output_folder="pdfs", choose_case="Номер дела"):
    download_dir = os.path.abspath(output_folder)
    os.makedirs(download_dir, exist_ok=True)

    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")  # Устанавливает размер окна браузера
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")  # Отключает обнаружение автоматизации
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])  # Скрывает сообщения об автоматизации
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")  # Устанавливает User-Agent как обычный браузер
    chrome_options.headless = True  # Включает headless режим (без GUI)

    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True, 
        "profile.default_content_settings.popups": 0,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # TODO: Подробнее разобраться с флагами. Уточнить каждый из них и как он откликается при работе докера.
    # Добавляем флаги для работы в Docker
    chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--disable-javascript")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-features=TranslateUI")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    
    # путь к хрому и флаги для докера. 
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--remote-debugging-port=0")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get("https://ras.arbitr.ru/")

        if choose_case.strip().lower() in ["инн", "организация"]:
            txt = WebDriverWait(driver, 15).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "textarea[placeholder='название, ИНН или ОГРН']"))
            )
        else:
            txt = WebDriverWait(driver, 15).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[placeholder='например, А50-5568/08']"))
            )
        txt.clear()
        txt.send_keys(query)

        date_to = datetime.now()
        date_from = date_to - timedelta(days=3*365)
        date_from_str = date_from.strftime('%d.%m.%Y')
        date_to_str = date_to.strftime('%d.%m.%Y')
        date_inputs = driver.find_elements(By.CSS_SELECTOR, "#sug-dates input[placeholder='дд.мм.гггг']")
        if len(date_inputs) >= 2:
            driver.execute_script("arguments[0].value = arguments[1];", date_inputs[0], date_from_str)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", date_inputs[0])
            driver.execute_script("arguments[0].value = arguments[1];", date_inputs[1], date_to_str)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", date_inputs[1])
        else:
            logging.warning("Не удалось найти оба поля для дат!")

        search_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#b-form-submit button[type='submit']"))
        )
        driver.execute_script("arguments[0].click();", search_btn)

        # Ждем появления результатов поиска
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.b-document-list"))
            )
            logging.info("Найдены результаты поиска")
            
            # Проверяем, есть ли сообщение об отсутствии результатов
            try:
                no_results = driver.find_element(By.CSS_SELECTOR, ".b-no-results")
                if no_results:
                    logging.info("Найдено сообщение об отсутствии результатов")
                    return
            except:
                pass
                
        except Exception as e:
            logging.error(f"Не удалось найти результаты поиска: {e}")
            # Сохраняем скриншот для отладки
            driver.save_screenshot("search_error.png")
            logging.info("Сохранен скриншот ошибки: search_error.png")
            return

        time.sleep(3)
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        pdf_links = []
        doc_items = driver.find_elements(By.CSS_SELECTOR, "ul.b-document-list > li")
        logging.info(f"Найдено элементов списка документов: {len(doc_items)}")
        
        # Логируем HTML-код страницы для отладки
        page_source = driver.page_source
        logging.info(f"Длина HTML-кода страницы: {len(page_source)} символов")
        
        # Ищем все возможные селекторы документов
        all_links = driver.find_elements(By.CSS_SELECTOR, "a")
        pdf_links_count = sum(1 for link in all_links if link.get_attribute("href") and ".pdf" in link.get_attribute("href").lower())
        logging.info(f"Найдено ссылок на PDF: {pdf_links_count}")
        
        # Проверяем альтернативные селекторы
        alt_items = driver.find_elements(By.CSS_SELECTOR, ".b-document-item")
        logging.info(f"Найдено элементов с селектором .b-document-item: {len(alt_items)}")
        
        alt_items2 = driver.find_elements(By.CSS_SELECTOR, "[class*='document']")
        logging.info(f"Найдено элементов с классом, содержащим 'document': {len(alt_items2)}")
        
        for i, item in enumerate(doc_items):
            try:
                logging.info(f"Обрабатываю элемент {i+1}/{len(doc_items)}")
                pdf_element = item.find_element(By.CSS_SELECTOR, "a.b-a-blue.js-popupDocumentShow")
                pdf_url = pdf_element.get_attribute("href").strip()
                logging.info(f"Найден PDF URL: {pdf_url}")

                pdf_url = re.sub(r'\s+', '', pdf_url)

                if "download=true" not in pdf_url:
                    if "?" in pdf_url:
                        download_url = pdf_url + "&download=true"
                    else:
                        download_url = pdf_url + "?download=true"
                else:
                    download_url = pdf_url

                parsed_url = urlparse(pdf_url)
                file_name = unquote(os.path.basename(parsed_url.path))

                if not file_name or '.' not in file_name:
                    try:
                        case_num = item.find_element(By.CSS_SELECTOR, "div.case a.b-a-blue").text.strip()
                        file_name = f"{case_num}.pdf"
                    except:
                        file_name = f"document_{int(time.time())}.pdf"

                elif not file_name.lower().endswith('.pdf'):
                    file_name += '.pdf'
                
                file_name = re.sub(r'[\\/*?:"<>|]', "_", file_name)
                file_name = re.sub(r'\s+', '_', file_name)
                
                pdf_links.append((download_url, file_name))
            except Exception as e:
                logging.error(f"Ошибка при обработке элемента: {str(e)}")
                continue

        logging.info(f"Найдено {len(pdf_links)} PDF‑файлов.")

        for url, file_name in pdf_links:
            file_path = os.path.join(download_dir, file_name)
            if os.path.exists(file_path):
                logging.info(f"Файл уже существует, пропуск: {file_name}")
                continue
            try:
                logging.info(f"Скачивание: {file_name}")

                driver.execute_script(f"window.open('{url}');")
                driver.switch_to.window(driver.window_handles[-1])

                time.sleep(5)

                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                
                logging.info(f"Файл скачан: {file_name}")
                
            except Exception as download_error:
                logging.error(f"Ошибка скачивания {file_name}: {download_error}")

        logging.info("Обработка скачанных файлов...")
        time.sleep(5)

        downloaded_files = os.listdir(download_dir)
        logging.info(f"Найдено файлов в папке: {len(downloaded_files)}")

        downloaded_files.sort(key=lambda x: os.path.getmtime(os.path.join(download_dir, x)), reverse=True)

        for i, (url, file_name) in enumerate(pdf_links):
            if i < len(downloaded_files):
                original_path = os.path.join(download_dir, downloaded_files[i])
                new_path = os.path.join(download_dir, file_name)

                counter = 1
                while os.path.exists(new_path):
                    name, ext = os.path.splitext(file_name)
                    new_path = os.path.join(download_dir, f"{name}_{counter}{ext}")
                    counter += 1
                
                os.rename(original_path, new_path)
                logging.info(f"Переименован: {downloaded_files[i]} -> {os.path.basename(new_path)}")
            else:
                logging.warning(f"Нет файла для переименования: {file_name}")

    except Exception as e:
        logging.error(f"Ошибка: {str(e)}")
        driver.save_screenshot("error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    pass
    # Пример: download_by_query("7707083893", choose_case="ИНН")
    # ("А40-312285", choose_case="Номер дела")