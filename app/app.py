# -*- coding: utf-8 -*-
import asyncio
import itertools
import logging
import os
import random
import re
import string
import sys
import time
from argparse import ArgumentParser
from asyncio import Semaphore

import aiohttp
from aiohttp import web
from aiohttp.web_runner import TCPSite
from async_lru import alru_cache
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (AsyncApiClient, AsyncMessagingApi,
                                  Configuration, ReplyMessageRequest,
                                  TextMessage)
from linebot.v3.webhooks import (FollowEvent, JoinEvent, LeaveEvent,
                                 MessageEvent, TextMessageContent,
                                 UnfollowEvent)

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', None)
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
HF_API_TOKEN_LIST = os.getenv('HF_API_TOKEN_LIST', None)
HF_API_HEADER: dict = None
API_URL = "https://api-inference.huggingface.co/models/liswei/EmojiLMSeq2SeqLoRA"

if CHANNEL_SECRET is None or CHANNEL_ACCESS_TOKEN is None or HF_API_TOKEN_LIST is None:
    print(
        "Please set LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN and HF_API_TOKEN environment variables.")
    sys.exit(1)

logger = logging.getLogger()
session: aiohttp.ClientSession = None


class Handler:
    INPUT_TASK_PREFIX = "emoji: "
    BOT_NAME = "哈哈狗"
    KEEP_ALIVE_STR = "👋"

    def __init__(self, line_bot_api: AsyncMessagingApi, parser: WebhookParser, workers: int = 10, keep_alive_interval: int = 300):
        '''
        :param workers: Number of workers to limit the number of concurrent queries
        :param keep_alive_interval: Interval to query the serverless API to keep it alive (seconds)
        '''
        self.line_bot_api = line_bot_api
        self.parser = parser
        self.semaphore = Semaphore(workers)

        self.last_query_time = time.time()
        self.last_query_time_lock = asyncio.Lock()
        self.keep_alive_interval = keep_alive_interval
        asyncio.create_task(self.keep_serverless_api_alive())

    async def keep_serverless_api_alive(self):
        async def ping_serverless_api():
            random_str = ''.join(random.choices(
                string.ascii_letters + string.digits, k=3))  # prevent huggingface cache
            await query(self.KEEP_ALIVE_STR + random_str)
            query.cache_invalidate(self.KEEP_ALIVE_STR + random_str)

        await ping_serverless_api()

        while True:
            elapsed_time = time.time() - self.last_query_time
            if elapsed_time >= self.keep_alive_interval:
                await ping_serverless_api()
                last_query_time = time.time()
                async with self.last_query_time_lock:
                    if last_query_time > self.last_query_time:
                        self.last_query_time = last_query_time

            await asyncio.sleep(60)

    async def __call__(self, request):
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
            elif isinstance(event, FollowEvent):
                logger.info(f'加入好友 {event.source.user_id}')
            elif isinstance(event, LeaveEvent):
                logger.warning(f'幹被踢了啦 {event.source.group_id}')
            elif isinstance(event, UnfollowEvent):
                logger.warning(f'幹被封鎖了啦 {event.source.user_id}')
            elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                await self.handle_text_message(event)

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

        if input_text == f"{self.BOT_NAME}幫幫我":
            logger.info(f"幫幫我 by {event.source.user_id}")
            await self.send_help_message(event)
            return

        if input_text.startswith(f"@{self.BOT_NAME}") or input_text.endswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[len(f"@{self.BOT_NAME}"):]
        elif input_text.endswith(f"@{self.BOT_NAME}") or input_text.endswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[:-len(f"@{self.BOT_NAME}")]
        else:
            return

        async with self.semaphore:
            await asyncio.sleep(0.1)
            output = await generate_output(self.INPUT_TASK_PREFIX, input_text)

        last_query_time = time.time()
        async with self.last_query_time_lock:
            if last_query_time > self.last_query_time:
                self.last_query_time = last_query_time

        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=output)]
            )
        )


async def generate_output(prefix, input_text):
    sentences_limit = 35

    text_list, delimiter_list = preprocess_input_text(input_text)
    logger.debug(f"Text list length: {len(text_list)}")

    if len(text_list) > sentences_limit:
        logger.warning(f"Input text too long: {len(text_list)}")
        last_sentence_within_limit = text_list[sentences_limit-1]
        if len(last_sentence_within_limit) >= 5:
            last_sentence_within_limit = '...' + \
                last_sentence_within_limit[-5:]
        return f"太長了啦❗️ 你輸入了{len(text_list)}句 目前限制{sentences_limit}句話 大概到這邊而已：「{last_sentence_within_limit}」"

    out_emoji_list = []
    for text in text_list:
        out_emoji = await query(prefix + text)
        if out_emoji.startswith("[!Broke]"):
            query.cache_invalidate(prefix + text)
            return out_emoji[len("[!Broke]"):]
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

    return output


@alru_cache(maxsize=1024)
async def query(input_text):
    logger.debug(f"Query: {input_text}")
    payload = {
        "inputs": input_text,
        "options": {"wait_for_model": True},
        "parameters": {
            "max_new_tokens": 5,
            "do_sample": False,
        },
    }

    async with session.post(API_URL, headers=HF_API_HEADER, json=payload) as response:
        resp = await response.json(encoding='utf-8')
    try:
        ret = resp[0]['generated_text']
    except KeyError:
        logger.error(f"Error: {resp}")
        set_hf_api_token()
        return "[!Broke]幹太多人用壞掉了 可能下個小時才會好"

    ret = post_process_output(ret)
    logger.info(f"Input: `{input_text}` Output: `{ret}`")
    return ret


def preprocess_input_text(input_text: str):
    input_text = re.sub(r"https?://\S+|www\.\S+", "", input_text)
    input_text = input_text.strip(" ，。,.\n")
    parts = re.split(r'(\s*[ ，。\n]\s*)', input_text)

    text_list = parts[::2]
    delimiter_list = parts[1::2]
    return text_list, delimiter_list


def post_process_output(output_emoji: str):
    if re.match(r"<(.*?)>", output_emoji):
        try:
            code_points = re.findall(r"<(.*?)>", output_emoji)
            output_emoji = bytes(int(code_unit, 16)
                                 for code_unit in code_points).decode('utf-8')
        except ValueError:
            pass
    return output_emoji


async def main(args):
    InitLogger(logger, 'app.log')

    global HF_API_TOKEN_LIST
    HF_API_TOKEN_LIST = HF_API_TOKEN_LIST.split(' ')
    set_hf_api_token(0)

    global session
    session = aiohttp.ClientSession()

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    async_api_client = AsyncApiClient(configuration)

    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(CHANNEL_SECRET)
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
            await asyncio.sleep(600)  # Keep the server running
    finally:
        await site.stop()
        await runner.cleanup()
        await async_api_client.close()
        await session.close()


def InitLogger(rootLogger, log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "[!log] %(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s")

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
    parser.add_argument('--port', type=int, default=8000)
    return parser.parse_args()


def set_hf_api_token(idx=None):
    if idx is None:
        # Randomly choose one token
        import random
        idx = random.randint(0, len(HF_API_TOKEN_LIST)-1)

    logger.info(f"Use HF API token {idx}")
    global HF_API_HEADER
    HF_API_HEADER = {"Authorization": f"Bearer {HF_API_TOKEN_LIST[idx]}"}


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Server stopped.")
