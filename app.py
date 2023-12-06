import logging
import os
import sys
from datetime import datetime, time, timedelta
from multiprocessing import Process
from time import sleep

import dateparser
import pymongo
from dotenv import load_dotenv
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (JoinEvent, LeaveEvent, MessageEvent, TextMessage,
                            TextSendMessage, UnfollowEvent)
from pycnnum import cn2num

DB_NAME = 'Official-Reminder-Bot-Line'
COLLECTION_NAME = 'Reminders'
ascii_table = list(range(32, 47 + 1)) + \
    list(range(58, 64 + 1)) + \
    list(range(91, 96 + 1)) + \
    list(range(123, 126 + 1))
PREFIXES = {chr(n) for n in ascii_table}

load_dotenv()
flask_app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
mongo_col = pymongo.MongoClient(os.getenv('MONGO_URI'))[
    DB_NAME][COLLECTION_NAME]

'''
Document = {
    'create_time': datetime,
    'remind_time': datetime,

    'by': {
        'type': event.source.type,
        'user_id': event.source.user_id,
        'group_id': event.souce.group_id if hasattr(event.souce, 'group_id') else None,
    }

    'message_id': str,
    'message_text': str,
    ''
}
'''


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
        text="""Hi! 我負責提醒你一下

使用兩個半形符號包圍時間即可使用
範例：
**5 min** 買菜 ➔ 會在 5 分鐘後提醒
__5/1__ 開會 ➔ 會在下個 5/1 提醒
--14:00-- 還錢 ➔ 會在下午兩點提醒

也可以在群組中使用哦！
目前還在測試中，如果常常失敗或是有 bug，可以聯絡開發者改善(frozen)
PS: 儘量避免在描述時間時使用中文效果會更好哦"""))
    sleep(0.5)
    line_bot_api.push_message(id, TextSendMessage(
        text="""原始碼開源於：https://github.com/pha123661/Reminder-Bot
開發者信箱：swli-iagents.9vj9n@slmail.me
輸入「ㄟㄟ教我一下」即可再次顯示教學"""))


@handler.add(LeaveEvent)
def handle_group_leave(event: LeaveEvent):
    logger.warning('幹被踢了啦')


@handler.add(UnfollowEvent)
def handle_group_leave(event: UnfollowEvent):
    logger.warning('幹被封鎖了啦')


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    if event.message.text == "ㄟㄟ教我一下":
        if event.source.type == 'group':
            send_welcome_message(event.source.group_id)
        else:
            send_welcome_message(event.source.user_id)
        return

    if event.message.text[0] != event.message.text[1] or event.message.text[0] not in PREFIXES:
        return

    idx_contain_time = event.message.text.find(event.message.text[:2], 2)
    if idx_contain_time == len(event.message.text):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='沒有偵測到時間，請再試一次')
        )
        return

    message = event.message.text[idx_contain_time + 2:].strip()
    time_str: str = event.message.text[2:idx_contain_time]

    # # preprocess time_str
    # def preprocess_time_str(time_str: str) -> str:
    #     # time_str = ''.join(time_str.split())  # remove all whitespace
    #     time_str = time_str.replace("半", "三十")

    #     chinese_num = set('一二三四五六七八九十')
    #     i = time_str.find("點")
    #     if not 0 < i < len(time_str):
    #         return time_str

    #     j = i - 1
    #     while j >= 0 and time_str[j] in chinese_num:
    #         j -= 1

    #     j += 1

    #     k = i
    #     if i < len(time_str) - 1:
    #         k = i + 1
    #         while k < len(time_str) and time_str[k] in chinese_num:
    #             k += 1
    #         k -= 1
    #     if j == k:
    #         # only "點" exists
    #         time_str = time_str[:i] + ":" + time_str[i + 1:]
    #     else:
    #         time_str = time_str.replace(
    #             time_str[j:k + 1], f" {cn2num(time_str[j:i]) if j != i else ''}:{cn2num(time_str[i+1:k+1]) if k != i else '00:00'}")
    #     return time_str

    # time_str = preprocess_time_str(time_str)
    # print(time_str)
    create_time = datetime.now()
    remind_time = dateparser.parse(
        time_str,
        settings={
            'PREFER_DAY_OF_MONTH': 'first',
            'TO_TIMEZONE': 'Asia/Taipei',
            'DATE_ORDER': 'YMD',
            'PREFER_DATES_FROM': 'future',

        }
    )
    # eng = None
    # if remind_time is None:
    #     eng = tss.google(event.message.text[2:idx_contain_time])
    #     logger.info(
    #         f"{event.message.text[2:idx_contain_time]} failed, trying {eng} instead")
    #     remind_time = dateparser.parse(
    #         eng,
    #         settings={
    #             'PREFER_DAY_OF_MONTH': 'first',
    #             'TO_TIMEZONE': 'Asia/Taipei',
    #             'DATE_ORDER': 'YMD',
    #             'PREFER_DATES_FROM': 'future',

    #         }
    #     )

    if remind_time is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f'“{event.message.text[2:idx_contain_time]}” 內沒有偵測到時間，請再試一次')
        )
        # if eng is not None:
        #     logger.info(f"{eng} failed")
        # else:
        #     logger.info(f"{event.message.text[2:idx_contain_time]} failed")
        return

    if remind_time <= create_time:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f'{remind_time.strftime(r"%Y/%m/%d %H:%M")} 不是未來的時間，請再試一次')
        )
        return
    delta = remind_time - create_time
    if delta >= timedelta(days=400):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f'您也計劃的太久了吧，先考慮 400 天以內的事情就好啦')
        )
        return

    # check if remind_time is in [00:00, 08:00]
    eight_am_flag = False
    if delta > timedelta(days=1) and time(hour=0, minute=0) <= remind_time.time() <= time(hour=8, minute=0):
        remind_time = remind_time.replace(hour=8, minute=0)
        eight_am_flag = True

    by = {
        'type': event.source.type,
        'user_id': event.source.user_id,
        'group_id': event.source.group_id if hasattr(event.source, 'group_id') else None,
    }

    document = {
        'create_time': create_time,
        'remind_time': remind_time,
        'by': by,
        'message_id': event.message.id,
        'message_text': message,
    }
    mongo_col.insert_one(document)

    if remind_time.year != create_time.year:
        time_str = remind_time.strftime(r'%Y/%m/%d %H:%M')
    elif remind_time.month != create_time.month:
        time_str = remind_time.strftime(r'%m/%d %H:%M')
    elif remind_time.day != create_time.day:
        time_str = remind_time.strftime(r'%m/%d %H:%M')
    else:
        time_str = remind_time.strftime(r'今日 %H:%M')

    reply_text = f"將會在 {time_str} 提醒您"
    if eight_am_flag:
        reply_text = reply_text + '\n--提醒時間為上午 8 點'
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
    logger.info(f"New: {message if message else r'“”'} at {time_str}")


def scan_db():
    while True:
        stream = mongo_col.find(
            {
                "remind_time": {
                    "$lte": datetime.now()
                }
            },
            projection=['by', 'message_text', 'create_time'],
        )

        delete_id = []
        for reminder in stream:
            delete_id.append(reminder['_id'])
            to_id = reminder['by']['user_id'] if reminder['by']['type'] == 'user' else reminder['by']['group_id']
            line_bot_api.push_message(
                to_id,
                TextSendMessage(
                    text=f"提醒您：\n{reminder['message_text']}\n-- 來自 {reminder['create_time'].strftime(r'%Y/%m/%d %H:%M')}")
            )
        if delete_id:
            mongo_col.delete_many({'_id': {'$in': delete_id}})

        sleep(5)


if __name__ == "__main__":
    Process(
        target=flask_app.run,
        args=('localhost', ),
        kwargs={}
    ).start()
    Process(target=scan_db).start()
