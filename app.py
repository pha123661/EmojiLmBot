import logging
import os
import re
import sys
from multiprocessing import Process

from dotenv import load_dotenv
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (JoinEvent, LeaveEvent, MessageEvent, TextMessage,
                            TextSendMessage, UnfollowEvent)

load_dotenv()
flask_app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))


def InitLogger(log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s")

    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.INFO)

    fileHandler = logging.FileHandler(log_path, encoding='utf8')
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    return rootLogger


logger = InitLogger('./log.log')


@flask_app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    flask_app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.fatal(
            "Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(JoinEvent)
def handle_group_join(event: JoinEvent):
    print(event)
    if event.source.type == 'group':
        send_welcome_message(event.source.group_id)


def send_welcome_message(id):
    line_bot_api.push_message(id, TextSendMessage(
        text=f"Hi! 跟我說「幫我加emoji」，我就會幫加在下句話上了ㄛ"))


@handler.add(LeaveEvent)
def handle_group_leave(event: LeaveEvent):
    logger.warning(f'幹被踢了啦 {event.source.group_id}')


@handler.add(UnfollowEvent)
def handle_group_leave(event: UnfollowEvent):
    logger.warning(f'幹被封鎖了啦 {event.source.user_id}')


def preprocess_input_text(input_text):
    # remove space, tab, newline with re
    input_text = input_text.strip()
    input_text = re.sub(r'\s+', '', input_text)
    input_text = re.sub(r'[\u2000-\u200d\u202f\u205f\u3000]+', '', input_text)
    return input_text


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    input_text = event.message.text
    input_text = preprocess_input_text(input_text)
    if not (input_text == "幫我加emoji"):
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=f'哈哈 屁眼')
    )


if __name__ == "__main__":
    Process(
        target=flask_app.run,
        args=('localhost', ),
        kwargs={}
    ).start()
