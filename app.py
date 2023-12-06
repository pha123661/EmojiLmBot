# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import re
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


class Handler:
    INPUT_TASK_PREFIX = "emoji: "
    API_URL = "https://api-inference.huggingface.co/models/liswei/EmojiLMSeq2SeqLoRA"
    HF_API_HEADER = {"Authorization": f"Bearer {hf_api_token}"}

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
        input_text = preprocess_input_text(event.message.text)
        output = await query({"inputs": f"{self.INPUT_TASK_PREFIX+input_text}"}, self.HF_API_HEADER, self.API_URL)
        print(output)
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=output)]
            )
        )


async def query(payload, headers, url):
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, json=payload) as response:
            resp = await response.json(encoding='utf-8')

    ret = resp[0]['generated_text']
    return ret


def preprocess_input_text(input_text):
    input_text = input_text.strip()
    input_text = re.sub(r'\s+', '', input_text)
    input_text = re.sub(r'[^\x20-\x7E]', '', input_text)
    return input_text


async def main(port=8000):
    configuration = Configuration(access_token=channel_access_token)
    async_api_client = AsyncApiClient(configuration)

    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(channel_secret)
    handler = Handler(line_bot_api, parser)

    app = web.Application()
    app.add_routes([web.post('/callback', handler.__call__)])

    runner = web.AppRunner(app)
    await runner.setup()
    site = TCPSite(runner=runner, port=port)
    await site.start()

    # sleep forever
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', type=int,
                            default=8000, help='port')
    args = arg_parser.parse_args()

    asyncio.run(main(args.port))
