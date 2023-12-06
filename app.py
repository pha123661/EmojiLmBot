# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import re
import sys
from argparse import ArgumentParser

import aiohttp
from aiohttp import web
from aiohttp.web_runner import TCPSite
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
hf_api_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

logger = logging.getLogger()
session: aiohttp.ClientSession = None


class Handler:
    INPUT_TASK_PREFIX = "emoji: "
    API_URL = "https://api-inference.huggingface.co/models/liswei/EmojiLMSeq2SeqLoRA"
    HF_API_HEADER = {
        "Authorization": f"Bearer {hf_api_token}"}

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
            if isinstance(event, LeaveEvent):
                pass
            if isinstance(event, UnfollowEvent):
                pass
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                await self.handle_text_message(event)

        return web.Response(text="OK\n")

    async def handle_text_message(self, event: MessageEvent):
        text, deli = preprocess_input_text(event.message.text)
        if deli is None:
            out_emoji = await query({"inputs": f"{self.INPUT_TASK_PREFIX+text}", "wait_for_model": True}, self.HF_API_HEADER, self.API_URL)
            output = text + out_emoji
        else:
            output_list = []
            for t in text:
                out_emoji = await query({"inputs": f"{self.INPUT_TASK_PREFIX+t}"}, self.HF_API_HEADER, self.API_URL)
                output_list.append(out_emoji)
            output = "".join([val for triple in zip(text, output_list, deli)
                             for val in triple] + text[len(deli):] + output_list[len(deli):] + deli[len(output_list):])
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=output)]
            )
        )


async def query(payload, headers, url):
    async with session.post(url, headers=headers, json=payload) as response:
        resp = await response.json(encoding='utf-8')

    ret = resp[0]['generated_text']
    rej_list = ["<0xF0><0x9F><0xA7><0xA7>", "<0xF0><0x9F><0xA5><0xB2>",
                "<0xF0><0x9F><0xA5><0xB2><0xF0><0x9F><0xA5><0xB2>"]
    if ret in rej_list:
        ret = ""
    return ret


def preprocess_input_text(input_text):
    input_text = input_text.strip()
    # input_text = re.sub(r'\s+', '', input_text)
    # input_text = re.sub(r'[\u2000-\u200d\u202f\u205f\u3000]+', '', input_text)
    parts = re.split(r'(\s*[ ，。\n]\s*)', input_text)
    if len(parts) == 1:
        return parts[0], None

    while parts[0] in ['', ' ', '\n', '，', '。']:
        parts = parts[1:]

    text_list = parts[::2]
    delimiter_list = parts[1::2]
    return text_list, delimiter_list


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
