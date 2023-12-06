import logging
import os
import re
import sys

from dotenv import load_dotenv
from flask import Flask, abort, request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (ApiClient, Configuration, MessagingApi,
                                  PushMessageRequest, ReplyMessageRequest,
                                  TextMessage)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import (JoinEvent, LeaveEvent, MessageEvent,
                                 TextMessageContent, UnfollowEvent)

load_dotenv()

app = Flask(__name__)
configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))


def InitLogger(app, log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s")

    rootLogger = app.logger
    rootLogger.setLevel(logging.INFO)

    fileHandler = logging.FileHandler(log_path, encoding='utf8')
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    return rootLogger


@handler.add(JoinEvent)
def handle_group_join(event: JoinEvent):
    print(event)
    if event.source.type == 'group':
        send_welcome_message(event.source.group_id)


def send_welcome_message(reply_token):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            PushMessageRequest(
                to=reply_token,
                messages=[TextMessage(text=f"Hi! 跟我說「幫我加emoji」，我就會幫加在下句話上了ㄛ")]
            )
        )


@handler.add(LeaveEvent)
def handle_group_leave(event: LeaveEvent):
    app.logger.warning(f'幹被踢了啦 {event.source.group_id}')


@handler.add(UnfollowEvent)
def handle_group_leave(event: UnfollowEvent):
    app.logger.warning(f'幹被封鎖了啦 {event.source.user_id}')


def preprocess_input_text(input_text):
    # remove space, tab, newline with re
    input_text = input_text.strip()
    input_text = re.sub(r'\s+', '', input_text)
    input_text = re.sub(r'[\u2000-\u200d\u202f\u205f\u3000]+', '', input_text)
    return input_text


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info(
            "Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

    input_text = event.message.text
    input_text = preprocess_input_text(input_text)
    if not (input_text == "幫我加emoji"):
        return

    line_bot_api.reply_message_with_http_info(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text='哈哈 屁眼')]
        )
    )


if __name__ == "__main__":
    InitLogger(app, './log.log')
    app.run(host="0.0.0.0", ssl_context='adhoc')
