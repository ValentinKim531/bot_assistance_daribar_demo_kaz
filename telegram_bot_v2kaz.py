import asyncio
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session import aiohttp
from aiogram.filters import CommandStart
from aiogram.dispatcher.router import Router
from dotenv import load_dotenv
import os
from yandex_cloud_api_kaz import recognize_speech, synthesize_speech
from openai_gpt import process_question
import re
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_IAM_TOKEN = os.getenv("YANDEX_IAM_TOKEN")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()


def fetch_medicine_info():
    """Отправка запроса к API для получения данных о лекарстве."""
    url = 'https://prod-backoffice.daribar.com/api/v1/products/search?city=%D0%90%D0%BB%D0%BC%D0%B0%D1%82%D1%8B'
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9,ru;q=0.8',
        'authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjdXN0b21lciI6ZmFsc2UsImV4cCI6MTcxNTcwODM0NiwibmFtZSI6IiIsInBob25lIjoiNzc3NzU4NDY5NjEiLCJyZWZyZXNoIjpmYWxzZSwicm9sZSI6ImFkbWluIiwic2Vzc2lvbl9pZCI6IjE0MGE4ZTg3LWQzZTctNGE4Yi1iODE1LTEyZjE2YjBiZGU0NiJ9.JI2N8d93qDcH5sTOOI0bAo3aRJcjK02ZsMjez_Xd3wQ',  # Убедитесь, что токен актуален
        'content-type': 'application/json',
        'origin': 'https://daribar.kz',
        'referer': 'https://daribar.kz/'
    }
    data = '[{"sku":"75c9de5e-0669-41b0-b07b-d6d545c6711a","count_desired":1}]'
    response = requests.post(url, headers=headers, data=data)
    return response.json()


@router.message(CommandStart())
async def process_start_command(message: types.Message):
    await message.answer('Сәлеметсіз бе! Маған дәрі-дәрмектің аты жазылған дауыстық поштаны жіберіңіз.\n Сондай-ақ операцияның демонстрациялық бейнесін келесі сілтемеден көре аласыз:\nhttps://youtube.com/shorts/6pJ04x-M-XQ')


@router.message(F.voice)
async def handle_voice_message(message: types.Message):
    voice_file_id = message.voice.file_id
    file_info = await bot.get_file(voice_file_id)
    file_url = f'https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}'

    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            if response.status == 200:
                file_content = await response.read()
                logger.info("File downloaded successfully.")
            else:
                logger.error(f"Failed to download file: HTTP status {response.status}")
                return

    try:
        speech_text = recognize_speech(file_content)
        response_text = await process_question(speech_text)
        logger.info(f"Response text from GPT: {response_text}")

        # Получение данных о лекарствах и форматирование ответа
        if response_text.lower().strip() == 'кызылмай' or response_text.lower().strip() == 'кызыл май':
            api_response = fetch_medicine_info()
            formatted_response = format_response(api_response)
            logger.info(f"Formatted response for synthesis: {formatted_response}")

            # Перевод сформированного ответа на казахский язык
            translated_text = translate_text(formatted_response, source_lang='ru', target_lang='kk')
            logger.info(f"Translated text: {translated_text}")

            # Синтез речи из переведенного текста
            audio_response_bytes = synthesize_speech(translated_text)

            mp3_audio_path = "response.mp3"
            with open(mp3_audio_path, "wb") as mp3_audio_file:
                mp3_audio_file.write(audio_response_bytes)

            try:
                await message.answer_voice(voice=types.FSInputFile(mp3_audio_path), caption=translated_text)
                logger.info("Voice response sent successfully.")
            except Exception as e:
                logger.error(f"Failed to send voice response: {e}")
                await message.answer("Failed to send the voice response.")
            finally:
                if os.path.exists(mp3_audio_path):
                    os.remove(mp3_audio_path)
                    logger.info(f"Deleted file {mp3_audio_path}.")

        else:
            await message.answer(
                text='Демонстрацияның бөлігі ретінде «қызыл май» сөзі бар сөйлемді айтыңыз.\n Сондай-ақ операцияның демонстрациялық бейнесін келесі сілтемеден көре аласыз:\nhttps://youtube.com/shorts/6pJ04x-M-XQ')

    except Exception as e:
        logger.error(f"Failed to send voice: {e}")
        await message.answer(
            text='Техникалық себептерге байланысты сұраныс өңделмеді.\nДегенмен, операцияның демонстрациялық бейнесін келесі сілтемеден көре аласыз:\nhttps://youtube.com/shorts/6pJ04x-M-XQ')





def format_response(data):
    """Форматирование данных API в строку ответа."""
    results = []
    for item in data['result'][:3]:
        pharmacy_info = f"Препарат {item['products'][0]['name']}\n Адрес:\n город {item['source']['city']},\n {item['source']['address']},\n стоимость препарата {item['products'][0]['base_price']} тенге\n"
        results.append(pharmacy_info)
    return "\n".join(results)


def remove_annotations(text: str) -> str:
    pattern = r'(\[\[.*?\]\])|(\【[^】]*\】)'
    cleaned_text = re.sub(pattern, '', text)
    return cleaned_text


def translate_text(text, source_lang='ru', target_lang='kk'):
    url = "https://translate.api.cloud.yandex.net/translate/v2/translate"
    headers = {
        'Authorization': f'Bearer {YANDEX_IAM_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'folder_id': YANDEX_FOLDER_ID,
        'texts': [text],
        'targetLanguageCode': target_lang,
        'sourceLanguageCode': source_lang
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        translations = response.json().get('translations', [])
        if translations:
            return translations[0]['text']
        else:
            return "Перевод не найден."
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
        return "Перевод не удался."
    except Exception as err:
        logging.error(f"An error occurred: {err}")
        return "Перевод не удался."


dp.include_router(router)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())