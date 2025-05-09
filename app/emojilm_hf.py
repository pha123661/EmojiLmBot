'''
This module is not deprecated due to policy changes of huggingface inference API. (I.e., no more free API)
This module is used to generate emojis using the huggingface inference API.
'''

import asyncio
import itertools
import logging
import random
import re
import string
import time
from asyncio import Semaphore

import aiohttp
import fasttext
import nltk
from async_lru import alru_cache

logger = logging.getLogger()
language_model = fasttext.load_model("lid.176.ftz")

class EmojiLmHf:
    KEEP_ALIVE_STR = "👋"
    API_URL = "https://api-inference.huggingface.co/models/liswei/EmojiLMSeq2SeqLoRA"
    SENTENCE_LIMIT = 99
    INPUT_PREFIX = "emoji: "

    def __init__(
        self,
        hf_api_token_list,
        concurrency=3,
        keep_alive_interval=300,  # seconds
    ):
        self.hf_api_token_list = hf_api_token_list
        self.query_semaphore = Semaphore(concurrency)
        self.keep_alive_interval = keep_alive_interval

        self.api_idx = random.randint(0, len(self.hf_api_token_list)-1)
        self.api_header = {
            "Authorization": f"Bearer {self.hf_api_token_list[self.api_idx]}"}
        self.aio_session = aiohttp.ClientSession()

        self.last_query_time = time.time() - self.keep_alive_interval
        self.last_query_time_lock = asyncio.Lock()
        asyncio.create_task(self.keep_serverless_api_alive())

    def update_hf_api_token(self):
        self.api_idx = (self.api_idx + 1) % len(self.hf_api_token_list)
        logger.info(f"Use HF API token {self.api_idx}")
        self.api_header = {
            "Authorization": f"Bearer {self.hf_api_token_list[self.api_idx]}"}

    async def keep_serverless_api_alive(self):
        async def ping_serverless_api():
            # Create a random string to avoid caching
            random_str = ''.join(random.choices(
                string.ascii_letters + string.digits, k=2))
            query_value = self.KEEP_ALIVE_STR + random_str
            await self.query(query_value)
            if hasattr(self.query, "cache_invalidate"):
                self.query.cache_invalidate(query_value)

        while True:
            async with self.last_query_time_lock:
                elapsed_time = time.time() - self.last_query_time

            if elapsed_time < self.keep_alive_interval:
                wait_time = self.keep_alive_interval - elapsed_time
                await asyncio.sleep(wait_time)
                continue

            # Time to send a keep-alive ping.
            await ping_serverless_api()

            # Update the last query time in a thread-safe way.
            current_time = time.time()
            async with self.last_query_time_lock:
                self.last_query_time = current_time

    async def generate(self, input_text):
        text_list, delimiter_list = preprocess_input_text(input_text)
        logger.debug(f"Text list length: {len(text_list)}")

        if len(text_list) > self.SENTENCE_LIMIT:
            logger.warning(f"Input text too long: {len(text_list)}")
            last_sentence_within_limit = text_list[self.SENTENCE_LIMIT-1]
            if len(last_sentence_within_limit) >= 5:
                last_sentence_within_limit = '...' + \
                    last_sentence_within_limit[-5:]
            return f"太長了啦❗️ 你輸入了{len(text_list)}句 目前限制{self.SENTENCE_LIMIT}句話 大概到這邊而已：「{last_sentence_within_limit}」", []

        emojis = await asyncio.gather(*(self.query(self.INPUT_PREFIX + t) for t in text_list))

        output_list = list(itertools.chain.from_iterable(
            zip(text_list, emojis, delimiter_list)))
        min_length = min(len(text_list), len(
            emojis), len(delimiter_list))
        if len(text_list) > min_length:
            output_list.extend(text_list[min_length:])
        if len(emojis) > min_length:
            output_list.extend(emojis[min_length:])
        if len(delimiter_list) > min_length:
            output_list.extend(delimiter_list[min_length:])

        output = "".join(output_list)

        output_emoji_set = set()
        for e in emojis:
            output_emoji_set = output_emoji_set.union(set(e))

        return output, output_emoji_set

    @alru_cache(maxsize=1024)
    async def query(self, input_text):
        logger.debug(f"Query: {input_text}")
        payload = {
            "inputs": input_text,
            "options": {"wait_for_model": True},
            "parameters": {
                "max_new_tokens": 5,
                "do_sample": True,
                "temperature": 1.2,
                'top_p': 0.8
            },
        }

        async with self.query_semaphore:
            try:
                async with self.aio_session.post(self.API_URL, headers=self.api_header, json=payload) as response:
                    resp = await response.json(encoding='utf-8')
                    ret = resp[0]['generated_text']
            except Exception as e:
                logger.exception(e)
                if type(e) == KeyError:
                    logger.debug(f"Response: {resp}")
                # retry once
                self.update_hf_api_token()
                async with self.aio_session.post(self.API_URL, headers=self.api_header, json=payload) as response:
                    resp = await response.json(encoding='utf-8')
                    ret = resp[0]['generated_text']

        ret = post_process_output(ret)
        logger.info(f"Input: `{input_text}` Output: `{ret}`")
        return ret

    async def close(self):
        await self.aio_session.close()


def preprocess_input_text(input_text: str):
    input_text = re.sub(r"https?://\S+|www\.\S+", "", input_text)
    language_label = language_model.predict(
        [input_text.replace("\n", "")])[0][0][0]
    if language_label in ['__label__zh', '__label__ja', '__label__ko']:
        input_text = input_text.strip(" \n")
        parts = re.split(r'([ ，,。.？?！!;\n\s]+)', input_text)
        sentence_list = parts[::2]
        delimiter_list = parts[1::2]

        while len(sentence_list) > 0 and sentence_list[-1] == '':
            sentence_list.pop()
            if len(delimiter_list) > len(sentence_list):
                delimiter_list.pop()
        delimiter_list += [''] * (len(sentence_list) - len(delimiter_list))
        return sentence_list, delimiter_list
    else:
        sentences = nltk.tokenize.sent_tokenize(input_text, language='english')
        delimiter_list = []
        # Regular expression to match trailing punctuation
        pattern = re.compile(r'([^\w\s]+)$')

        cleaned_sentences = []
        for sentence in sentences:
            match = pattern.search(sentence)
            if match:
                delimiter_list.append(match.group(1))  # Extract punctuation
                sentence = sentence[:match.start()]   # Remove punctuation
            else:
                delimiter_list.append("")
            cleaned_sentences.append(sentence)
        return cleaned_sentences, delimiter_list


def post_process_output(output_emoji: str):
    if re.match(r"<(.*?)>", output_emoji):
        try:
            code_points = re.findall(r"<(.*?)>", output_emoji)
            output_emoji = bytes(int(code_unit, 16)
                                 for code_unit in code_points).decode('utf-8')
        except ValueError:
            pass

    # Remove the sad emoji due to the limitation of the model
    if output_emoji == '🥲':
        output_emoji = ""
    return output_emoji
