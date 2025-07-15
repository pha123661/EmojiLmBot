# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from typing import Protocol
from urllib.parse import parse_qsl

from aiohttp import web
from aiohttp.web_runner import TCPSite
from emojilm_openai import EmojiLmOpenAi
from linebot.v3 import WebhookParser, messaging
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (AsyncApiClient, AsyncMessagingApi,
                                  Configuration, QuickReply, QuickReplyItem,
                                  ReplyMessageRequest,
                                  ShowLoadingAnimationRequest, TextMessage)
from linebot.v3.webhooks import (FollowEvent, JoinEvent, LeaveEvent,
                                 MessageEvent, PostbackEvent,
                                 TextMessageContent, UnfollowEvent)

logger = logging.getLogger()


class EmojiLm(Protocol):
    async def generate(self, input_text) -> tuple[str, set[str]]:
        ...


class Handler:
    BOT_NAME = "哈哈狗"

    def __init__(
        self,
            line_bot_api: AsyncMessagingApi,
            parser: WebhookParser,
            emojilm: EmojiLm,
            db: 'Database'  # type: ignore[valid-type] --- IGNORE ---,
    ):
        self.line_bot_api = line_bot_api
        self.parser = parser
        self.emojilm = emojilm
        self.db = db

    async def handle_callback(self, request):
        signature = request.headers['X-Line-Signature']
        body = await request.text()

        try:
            events = self.parser.parse(body, signature)
        except InvalidSignatureError:
            logger.error("Invalid signature.")
            return web.Response(status=400, text='Invalid signature')

        for event in events:
            if isinstance(event, JoinEvent):
                logger.info(f'加入群組 {event.source.group_id}')
                await self.send_help_message(event)
                await self.db.upsert_group(
                    group_id=event.source.group_id,
                    leave=False,
                    first_use=datetime.fromtimestamp(event.timestamp/1000)
                )
            elif isinstance(event, FollowEvent):
                logger.info(f'加入好友 {event.source.user_id}')
            elif isinstance(event, LeaveEvent):
                logger.warning(f'幹被踢了啦 {event.source.group_id}')
                await self.db.upsert_group(
                    group_id=event.source.group_id,
                    leave=True
                )
            elif isinstance(event, UnfollowEvent):
                logger.warning(f'幹被封鎖了啦 {event.source.user_id}')
                await self.db.upsert_user(
                    user_id=event.source.user_id,
                    block=True,
                    last_block=datetime.fromtimestamp(event.timestamp/1000)
                )
            elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                try:
                    await asyncio.wait_for(
                        self.handle_text_message(event),
                        timeout=80
                    )
                except asyncio.TimeoutError:
                    logger.warning("Timeout")
                    await self.line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="太多人用卡住了啦 去噴作者 sorry la 稍後再試")]
                        )
                    )
                except messaging.exceptions.ApiException:
                    logger.warning("API Exception")
                    await self.line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="爛 Line 不給傳啦 可能太長了 sorry la 稍後再試")]
                        )
                    )
                except Exception as e:
                    logger.exception(e)
                    await self.line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="服務暫時壞了 sorry la 稍後再試")]
                        )
                    )
            elif isinstance(event, PostbackEvent):
                await self.handle_post_back(event)
        return web.Response(text="OK\n")

    async def send_help_message(self, event: MessageEvent):
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text=f"在訊息前或後+上 @{self.BOT_NAME} 就會幫你+emoji\nEX: @哈哈狗 那你很厲害誒")]
            )
        )

    async def handle_text_message(self, event: MessageEvent):
        logger.debug(f"Got message: {event.message.text}")
        input_text = event.message.text.strip()

        await self.line_bot_api.show_loading_animation(
            ShowLoadingAnimationRequest(
                chatId=event.source.user_id, loadingSeconds=60)
        )

        if input_text == f"{self.BOT_NAME}幫幫我":
            logger.info(f"幫幫我 by {event.source.user_id}")
            await self.send_help_message(event)
            await self.db.upsert_user(
                user_id=event.source.user_id,
                help_count_inc=1,
                first_use=datetime.fromtimestamp(event.timestamp/1000)
            )
            return
        if input_text.startswith(f"@{self.BOT_NAME}") or input_text.startswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[len(f"@{self.BOT_NAME}"):]
        elif input_text.endswith(f"@{self.BOT_NAME}") or input_text.endswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[:-len(f"@{self.BOT_NAME}")]
        else:
            return

        if len(input_text) == 0:
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text="請給我一點文字啦 EX: @哈哈狗 那你很厲害誒")]
                )
            )
            return

        try:
            output_text_with_emoji, output_emoji_set = await self.emojilm.generate(input_text)
        except Exception as e:
            logger.exception(e)
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text="AI服務暫時壞了 sorry la 稍後再試")]
                )
            )
            return

        if len(output_emoji_set) == 0:
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=output_text_with_emoji)]
                )
            )
            return

        try:
            try:
                feedback_id = await asyncio.wait_for(
                    self.db.insert_feedback(
                        input_text=input_text,
                        output_text=output_text_with_emoji,
                        user_id=event.source.user_id,
                        create_time=datetime.fromtimestamp(event.timestamp/1000)
                    ),
                    timeout=1
                )
            except asyncio.TimeoutError:
                feedback_id = None
        except (Exception, TimeoutError) as e:
            logging.exception("Database insertion failed")
            feedback_id = None

        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=output_text_with_emoji,
                        quickReply=construct_quick_reply(feedback_id)
                    )
                ]
            )
        )

        if event.source.type == "group":
            await self.db.upsert_group(
                group_id=event.source.group_id,
                msg_count_inc=1,
                last_use=datetime.fromtimestamp(event.timestamp/1000)
            )

        await self.db.upsert_user(
            user_id=event.source.user_id,
            msg_count_inc=1,
            last_use=datetime.fromtimestamp(event.timestamp/1000)
        )

    async def handle_post_back(self, event: PostbackEvent):
        backdata = dict(parse_qsl(event.postback.data))
        if backdata.keys() != {'action', 'feedback_id'}:
            raise ValueError("Invalid quickreply!")

        if backdata['action'] == "dislike":
            preference_value = -1
        elif backdata['action'] == "like":
            preference_value = 1
        else:
            raise ValueError("Invalid quickreply!")

        try:
            feedback_id = int(backdata["feedback_id"])
        except ValueError:
            logger.error(
                f"Invalid feedback_id in postback data: {backdata['feedback_id']}")
            return

        await self.db.update_feedback_preference(feedback_id, preference_value)
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text="感謝回饋🐶")
                ]
            )
        )


def construct_quick_reply(feedback_id):
    if feedback_id is None:
        return None

    return QuickReply.from_dict({
        "items": [
            QuickReplyItem.from_dict({
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "讚啦😎",
                    "data": f"action=like&feedback_id={feedback_id}",
                    "displayText": "讚啦😎",
                }}),
            QuickReplyItem.from_dict({
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "爛啦🥲",
                    "data": f"action=dislike&feedback_id={feedback_id}",
                    "displayText": "爛啦🥲",
                }}),
        ]
    })


async def main(args):
    InitLogger(logger, '../data/app.log')

    if args.debug:
        logger.info("Running in debug mode")

    CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', None)
    CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

    HF_API_TOKEN = os.getenv('HF_API_TOKEN_LIST', "").split(' ')
    OPENAI_API_URL = os.getenv('LLAMA_CPP_SERVER_URL', None)
    DB_DSN = os.getenv('POSTGRES_DSN', None)

    if DB_DSN is None:
        logger.warning("POSTGRES_DSN is not set, using SQLite fallback.")
        from db_sqlite import Database
        DB_DSN = "../data/emojilm.db"
    else:
        from db_pg import Database

    if CHANNEL_SECRET is None or CHANNEL_ACCESS_TOKEN is None or (len(HF_API_TOKEN) == 0 and OPENAI_API_URL is None):
        print(
            "Please set LINE_CHANNEL_* and (HF_API_TOKEN_LIST or LLAMA_CPP_SERVER_URL).")
        sys.exit(1)

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    async_api_client = AsyncApiClient(configuration)
    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(CHANNEL_SECRET)

    db = await Database.create_and_connect(dsn=DB_DSN)

    emojilm = await EmojiLmOpenAi.create(
        OPENAI_API_URL=OPENAI_API_URL,
        OPENAI_API_KEY="no_key_required",
        concurrency=32,
        sentence_limit=100,
    )

    handler = Handler(
        line_bot_api=line_bot_api,
        parser=parser,
        emojilm=emojilm,
        db=db,
    )

    app = web.Application()
    app.add_routes([web.post('/callback', handler.handle_callback)])

    runner = web.AppRunner(app)
    await runner.setup()
    site = TCPSite(runner=runner, port=args.port)
    await site.start()

    logger.info(f"Server started at port {args.port}")

    try:
        while True:
            await asyncio.sleep(600)
    finally:
        await db.close()
        await site.stop()
        await runner.cleanup()
        await async_api_client.close()
        await emojilm.close()


def InitLogger(rootLogger, log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s")

    rootLogger.setLevel(logging.INFO)

    fileHandler = logging.FileHandler(log_path, encoding='utf8')
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    return rootLogger


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--port', type=int, default=7778)
    parser.add_argument('--debug', action="store_true")

    args = parser.parse_args()
    if os.getenv('DEBUG', '0').lower() in ('true', '1', 't'):
        args.debug = True
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Server stopped.")
