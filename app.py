# -*- coding: utf-8 -*-

import asyncio
import itertools
import logging
import os
import re
import sys
from argparse import ArgumentParser

import aiohttp
from aiohttp import web
from aiohttp.web_runner import TCPSite
from async_lru import alru_cache
from dotenv import load_dotenv
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (AsyncApiClient, AsyncMessagingApi,
                                  Configuration, ReplyMessageRequest,
                                  TextMessage)
from linebot.v3.webhooks import (JoinEvent, LeaveEvent, MessageEvent,
                                 TextMessageContent, UnfollowEvent)

load_dotenv()

channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
hf_api_token = os.getenv('HF_API_TOKEN', None)
API_URL = "https://api-inference.huggingface.co/models/liswei/EmojiLMSeq2SeqLoRA"
HF_API_HEADER = {"Authorization": f"Bearer {hf_api_token}"}

if channel_secret is None or channel_access_token is None or hf_api_token is None:
    print(
        "Please set LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN and HF_API_TOKEN environment variables.")
    sys.exit(1)

logger = logging.getLogger()
session: aiohttp.ClientSession = None


class Handler:
    INPUT_TASK_PREFIX = "emoji: "
    BOT_NAME = "哈哈狗"

    def __init__(self, line_bot_api: AsyncMessagingApi, parser: WebhookParser):
        self.line_bot_api = line_bot_api
        self.parser = parser

    async def __call__(self, request):
        signature = request.headers['X-Line-Signature']
        body = await request.text()

        try:
            events = self.parser.parse(body, signature)
        except InvalidSignatureError:
            return web.Response(status=400, text='Invalid signature')

        for event in events:
            if isinstance(event, JoinEvent):
                logger.info(f'加入群組 {event.source.group_id}')
                await self.send_help_message(event)
            if isinstance(event, LeaveEvent):
                logger.warning(f'幹被踢了啦 {event.source.group_id}')
            if isinstance(event, UnfollowEvent):
                logger.warning(f'幹被封鎖了啦 {event.source.user_id}')
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                await self.handle_text_message(event)

        return web.Response(text="OK\n")

    async def send_help_message(self, event: MessageEvent):
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text=f"在訊息前或後+上 ＠{self.BOT_NAME} 就幫你+emoji (但標不到是正常)")]
            )
        )

    async def handle_text_message(self, event: MessageEvent):
        logger.debug(f"Got message: {event.message.text}")
        input_text = event.message.text.strip()

        if input_text == f"{self.BOT_NAME}幫幫我":
            logger.info(f"幫幫我 by {event.source.user_id}")
            await self.send_help_message(event)
            return

        if input_text.startswith(f"@{self.BOT_NAME}"):
            input_text = input_text[len(f"@{self.BOT_NAME}"):]
        elif input_text.endswith(f"@{self.BOT_NAME}"):
            input_text = input_text[:-len(f"@{self.BOT_NAME}")]
        else:
            return

        text_list, delimiter_list = preprocess_input_text(input_text)

        out_emoji_list = []
        for t in text_list:
            out_emoji = await query(self.INPUT_TASK_PREFIX+t)
            if out_emoji.startswith("[!Broke]"):
                await self.line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=out_emoji)]
                    )
                )
                return
            out_emoji_list.append(out_emoji)

        output_list = []
        output_list = list(itertools.chain.from_iterable(
            zip(text_list, out_emoji_list, delimiter_list)))
        min_length = min(len(text_list), len(
            out_emoji_list), len(delimiter_list))
        if len(text_list) > min_length:
            output_list.extend(text_list[min_length:])
        if len(out_emoji_list) > min_length:
            output_list.extend(out_emoji_list[min_length:])
        if len(delimiter_list) > min_length:
            output_list.extend(delimiter_list[min_length:])

        output = "".join(output_list)

        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=output)]
            )
        )


rej_list = ["<0xF0><0x9F><0xA7><0xA7>", "<0xF0><0x9F><0xA5><0xB2>",
            "<0xF0><0x9F><0xA6><0xB8><0xF0><0x9F><0xA6><0xB8>"]
rej_pattern = re.compile("|".join(re.escape(rej) for rej in rej_list))


@alru_cache(maxsize=1024)
async def query(input_text):
    payload = {
        "inputs": input_text,
        "options": {"wait_for_model": True},
        "max_new_tokens": 5,
    }

    async with session.post(API_URL, headers=HF_API_HEADER, json=payload) as response:
        resp = await response.json(encoding='utf-8')
    try:
        ret = resp[0]['generated_text']
    except KeyError:
        logger.error(f"Error: {resp}")
        return "[!Broke]幹太多人用壞掉了 可能下個小時才會好"

    ret = rej_pattern.sub("", ret)

    logger.info(f"Input: `{input_text}` Output: `{ret}`")
    return ret


def preprocess_input_text(input_text: str):
    input_text = input_text.strip(" ，。,.\n")
    parts = re.split(r'(\s*[ ，。\n]\s*)', input_text)

    text_list = parts[::2]
    delimiter_list = parts[1::2]
    return text_list, delimiter_list


async def main(args):
    global session
    session = aiohttp.ClientSession()
    configuration = Configuration(access_token=channel_access_token)
    async_api_client = AsyncApiClient(configuration)

    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(channel_secret)
    handler = Handler(line_bot_api, parser)

    app = web.Application()
    app.add_routes([web.post('/callback', handler.__call__)])

    runner = web.AppRunner(app)
    await runner.setup()
    site = TCPSite(runner=runner, port=args.port)
    await site.start()

    logger.info(f"Server started at port {args.port}")

    try:
        while True:
            await asyncio.sleep(3600)  # Keep the server running
    finally:
        await site.stop()
        await runner.cleanup()
        await async_api_client.close()
        await session.close()


def InitLogger(rootLogger, log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "[!log] %(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s")

    rootLogger.setLevel(logging.DEBUG)

    fileHandler = logging.FileHandler(log_path, encoding='utf8')
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    return rootLogger


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    return parser.parse_args()


if __name__ == "__main__":
    InitLogger(logger, 'app.log')
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Server stopped.")
