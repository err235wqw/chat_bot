import config
import telebot
from telebot import types
import time
import os
import json
import boto3
import openai
import multiprocessing
from multiprocessing.dummy import Pool

logger = telebot.logger
bot = telebot.TeleBot(config.token)
PROXY_API_KEY = config.proxyAPIkey
YANDEX_KEY_ID = config.YandexKeyID
YANDEX_KEY_SECRET = config.YandexKeySecret
YANDEX_BUCKET = config.YandexBucket

# Обьявление переменных
text_start = config.start
text_studio = config.studio
text_freelance = config.freelance
menu = "main"
text_full_request = ""
text_request = ""

client = openai.Client(api_key=PROXY_API_KEY, base_url="https://api.proxyapi.ru/openai/v1",)

def get_s3_client():
    session = boto3.session.Session(aws_access_key_id=YANDEX_KEY_ID, aws_secret_access_key=YANDEX_KEY_SECRET)
    return session.client(service_name="s3", endpoint_url="https://storage.yandexcloud.net")


def typing(chat_id):
    while True:
        bot.send_chat_action(chat_id, "typing")
        time.sleep(5)


@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    global main
    global text_request
    text_request = "Сгенерируй карточку товара для "
    menu == 'main'
    keyboard = types.ReplyKeyboardMarkup(row_width=3)
    button1 = types.KeyboardButton('Фотостудия')
    button2 = types.KeyboardButton('AI Заполнение')
    button3 = types.KeyboardButton('Фриланс')
    button4 = types.KeyboardButton('Генерация изображения')
    button5 = types.KeyboardButton('Вернуться в главное меню')
    keyboard.add(button1, button2, button3, button4, button5)

    # Отправка сообщения с клавиатурой
    bot.reply_to(message, text_start, reply_markup=keyboard)


def handle_AI(message):
    keyboard = types.ReplyKeyboardMarkup(row_width=3)
    button1 = types.KeyboardButton('Ввести запрос целиком')
    button2 = types.KeyboardButton('Ввести запрос по шаблону')
    button3 = types.KeyboardButton('Вернуться в главное меню')
    keyboard.add(button1, button2, button3)

    bot.reply_to(message, "Выберите, как будете вводить запрос на генерацию карточки", reply_markup=keyboard)

@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_message(message):
    global menu
    global text_request
    if menu == "main":
        if message.text == 'Фотостудия':
            bot.reply_to(message, text_studio)
        elif message.text == 'AI Заполнение':
            menu = "AI_start_page"
            handle_AI(message)
        elif message.text == 'Фриланс':
            bot.reply_to(message, text_freelance)
        elif message.text == 'Генерация изображения':
            bot.reply_to(message, "Сервера OpenAI перегружены, генерация изображений временно невозможна.")
        elif message.text == "Вернуться в главное меню":
            handle_start(message)
        else:
            handle_start(message)
    elif menu == "AI_start_page":
        if message.text == 'Ввести запрос целиком':
            menu = "full request"
            bot.reply_to(message, "Введите запрос:", reply_markup=types.ReplyKeyboardRemove())
        elif message.text == 'Ввести запрос по шаблону':
            menu = "template request"
            bot.reply_to(message, "Введите название товара:", reply_markup=types.ReplyKeyboardRemove())
        elif message.text == "Вернуться в главное меню":
            menu = "main"
            handle_start(message)
    elif menu == "full request":
        menu = 'main'
        text_request ="Сгенерируй описание продукта, учитывая такие данные: название продукта, ключевые слова, размерность продукта, бренд продукта, на основе этой информации:  "
        text_request += message.text
        echo_message(message, text_request)
    elif menu == "template request":
        bot.reply_to(message, "Введите ключевые слова")
        menu = 'key words'
        text_request+=message.text + ', учитывая ключевые слова: '
    elif menu == "key words":
        bot.reply_to(message, "Введите размерность товара")
        menu = "Size"
        text_request+=message.text + ', упомянув размерность товара: '
    elif menu == "Size":
        bot.reply_to(message, "Введите имя Бренда")
        menu = "Brand"
        text_request +=message.text + ", для товара от бренда: "
    elif menu == "Brand":
        menu = "main"
        echo_message(message, text_request)


def echo_message(message, text):
    typing_process = multiprocessing.Process(target=typing, args=(message.chat.id,))
    typing_process.start()
    try:
        ai_response = process_text_message(text, message.chat.id)
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    typing_process.terminate()
    bot.reply_to(message, ai_response)
    handle_start(message)

def process_text_message(text, chat_id) -> str:
    model = "gpt-3.5-turbo"

    # read current chat history
    s3client = get_s3_client()
    history = []
    try:
        history_object_response = s3client.get_object(
            Bucket=YANDEX_BUCKET, Key=f"{chat_id}.json"
        )
        history = json.loads(history_object_response["Body"].read())
    except:
        pass

    history.append({"role": "user", "content": text})

    try:
        chat_completion = client.chat.completions.create(
            model=model, messages=history
        )
    except Exception as e:
        if type(e).__name__ == "BadRequestError":
            clear_history_for_chat(chat_id)
            return process_text_message(text, chat_id)
        else:
            raise e
    ai_response = chat_completion.choices[0].message.content
    history.append({"role": "assistant", "content": ai_response})

    # save current chat history
    s3client.put_object(
        Bucket=YANDEX_BUCKET,
        Key=f"{chat_id}.json",
        Body=json.dumps(history),
    )

    return ai_response


def clear_history_for_chat(chat_id):
    try:
        s3client = get_s3_client()
        s3client.put_object(
            Bucket=YANDEX_BUCKET,
            Key=f"{chat_id}.json",
            Body=json.dumps([]),
        )
    except:
        pass


def handler(event, context):
    message = json.loads(event["body"])
    update = telebot.types.Update.de_json(message)

    if (
        update.message is not None
    ):
        bot.process_new_updates([update])

if __name__ == '__main__':
     bot.infinity_polling()