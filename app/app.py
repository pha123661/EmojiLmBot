# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from typing import Protocol
from urllib.parse import parse_qsl

import motor.motor_asyncio
import pymongo
from aiohttp import web
from aiohttp.web_runner import TCPSite
from bson import ObjectId
from emojilm_openai import EmojiLmOpenAi
from linebot.v3 import WebhookParser
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

    def __init__(self,
                 line_bot_api: AsyncMessagingApi,
                 parser: WebhookParser,
                 emojilm: EmojiLm,
                 mongo_uri: str,
                 use_debug_db: bool = False):
        self.line_bot_api = line_bot_api
        self.parser = parser
        self.emojilm = emojilm

        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)

        if use_debug_db:
            self.usercol = client["analysis_debug"]["user_status"]
            self.groupcol = client["analysis_debug"]["group_status"]
            self.msgcol = client["analysis_debug"]["emoji_status"]
            self.fbcol = client["data_debug"]["feedback"]
        else:
            self.usercol = client["analysis"]["user_status"]
            self.groupcol = client["analysis"]["group_status"]
            self.msgcol = client["analysis"]["emoji_status"]
            self.fbcol = client["data"]["feedback"]

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
                await self.groupcol.find_one_and_update({"_id": event.source.group_id}, {"$set": {"leave": False}, "$setOnInsert": {"first_use": datetime.fromtimestamp(event.timestamp/1000)}}, upsert=True)
            elif isinstance(event, FollowEvent):
                logger.info(f'加入好友 {event.source.user_id}')
            elif isinstance(event, LeaveEvent):
                logger.warning(f'幹被踢了啦 {event.source.group_id}')
                await self.groupcol.find_one_and_update({"_id": event.source.group_id}, {"$set": {"leave": True}}, upsert=True)
            elif isinstance(event, UnfollowEvent):
                logger.warning(f'幹被封鎖了啦 {event.source.user_id}')
                await self.usercol.find_one_and_update({"_id": event.source.user_id}, {"$set": {"block": True, "last_block": datetime.fromtimestamp(event.timestamp/1000)}}, upsert=True)
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
                                TextMessage(text="卡住了不知道是怎樣 去噴作者 sorry la 稍後再試")]
                        )
                    )
                except pymongo.errors.ServerSelectionTimeoutError:
                    pass
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
            await self.usercol.find_one_and_update(
                {"_id": event.source.user_id},
                {
                    "$inc": {"help_count": 1},
                    "$setOnInsert": {"first_use": datetime.fromtimestamp(event.timestamp/1000)}
                },
                upsert=True
            )
            return
        if input_text.startswith(f"@{self.BOT_NAME}") or input_text.startswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[len(f"@{self.BOT_NAME}"):]
        elif input_text.endswith(f"@{self.BOT_NAME}") or input_text.endswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[:-len(f"@{self.BOT_NAME}")]
        else:
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

        document = {
            "Input": input_text,
            "Output": output_text_with_emoji,
            "User_ID": event.source.user_id,
            "Create_Time": datetime.fromtimestamp(event.timestamp/1000)
        }

        try:
            # Critical database insertion before reply to user -> Thus set timeout to 1 second
            with pymongo.timeout(1):
                feedback = await self.fbcol.insert_one(document)
            feedback_id = feedback.inserted_id
        except:
            logging.exception("Dead MongoDB")
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
            await self.groupcol.find_one_and_update(
                {"_id": event.source.group_id},
                {
                    "$inc": {"msg_count": 1},
                    "$set": {"last_use": datetime.fromtimestamp(event.timestamp/1000)},
                    "$setOnInsert": {"first_use": datetime.fromtimestamp(event.timestamp/1000)}
                },
                upsert=True
            )

        await self.usercol.find_one_and_update(
            {"_id": event.source.user_id},
            {
                "$inc": {"msg_count": 1},
                "$set": {"last_use": datetime.fromtimestamp(event.timestamp/1000)},
                "$setOnInsert": {"first_use": datetime.fromtimestamp(event.timestamp/1000)}
            },
            upsert=True
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

        feedback_id = ObjectId(backdata["feedback_id"])
        await self.fbcol.find_one_and_update({"_id": feedback_id}, {"$set": {"preference": preference_value}})
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
    InitLogger(logger, 'app.log')

    if args.debug:
        logger.info("Running in debug mode")

    CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', None)
    CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

    MONGO_CLIENT_URI = os.getenv('MONGO_CLIENT', None)
    HF_API_TOKEN = os.getenv('HF_API_TOKEN_LIST', "").split(' ')
    OPENAI_API_URL = os.getenv('LLAMA_CPP_SERVER_URL', None)

    if CHANNEL_SECRET is None or CHANNEL_ACCESS_TOKEN is None:
        print(
            "Please set LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN.")
        sys.exit(1)

    if len(HF_API_TOKEN) == 0 and OPENAI_API_URL is None:
        print("Please set HF_API_TOKEN_LIST or LLAMA_CPP_SERVER_URL.")
        sys.exit(1)

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    async_api_client = AsyncApiClient(configuration)
    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(CHANNEL_SECRET)
    # emojilm = EmojiLmHf(hf_api_token_list=HF_API_TOKEN)
    emojilm = await EmojiLmOpenAi.create(
        OPENAI_API_URL=OPENAI_API_URL   ,
        OPENAI_API_KEY="no_key_reqruied",
        concurrency=8,
        sentence_limit=500
    )

    handler = Handler(line_bot_api, parser, emojilm,
                      MONGO_CLIENT_URI, use_debug_db=args.debug)

    app = web.Application()
    app.add_routes([web.post('/callback', handler.handle_callback)])

    runner = web.AppRunner(app)
    await runner.setup()
    site = TCPSite(runner=runner, port=args.port)
    await site.start()

    logger.info(f"Server started at port {args.port}")

    try:
        while True:
            await asyncio.sleep(600)  # Keep the server running
    finally:
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
