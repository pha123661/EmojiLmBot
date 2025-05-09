import asyncio
import itertools
import logging
import re
from asyncio import Semaphore
from urllib.parse import urljoin

import aiohttp
import fasttext
import nltk
from async_lru import alru_cache

logger = logging.getLogger()
language_model = fasttext.load_model("lid.176.ftz")


class EmojiLmOpenAi:

    def __init__(self, OPENAI_API_URL, OPENAI_API_KEY, aio_session, model_id, concurrency, sentence_limit):
        self.OPENAI_API_URL = OPENAI_API_URL
        self.api_key = OPENAI_API_KEY
        self.SENTENCE_LIMIT = sentence_limit

        self.query_semaphore = Semaphore(concurrency)
        self.aio_session = aio_session
        self.model_id = model_id

    @classmethod
    async def create(
        cls,
        OPENAI_API_URL,
        OPENAI_API_KEY,
        concurrency=8,
        sentence_limit=500
    ):
        aio_session = aiohttp.ClientSession()
        model_id = await cls._get_model_id(aio_session, OPENAI_API_URL, OPENAI_API_KEY)
        return cls(OPENAI_API_URL, OPENAI_API_KEY, aio_session, model_id, concurrency, sentence_limit)

    @staticmethod
    async def _get_model_id(aio_session, OPENAI_API_URL, api_key):
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aio_session.get(urljoin(OPENAI_API_URL, "v1/models"), headers=headers) as response:
            resp = await response.json()
            if response.status != 200:
                logger.error(f"Failed to get model id: {resp}")
                raise Exception(f"Failed to get model id: {resp}")
            all_model_id = [model['id']
                            for model in resp['data'] if model['object'] == 'model']
            if not all_model_id:
                logger.error("No model id found")
                raise Exception("No model id found")
            logger.info(f"All Model ids: {all_model_id}")
            model_id = all_model_id[0]
            logger.info(f"Using model id: {model_id}")
            return model_id

    async def generate(self, input_text):
        sentence_list, delimiter_list = preprocess_input_text(input_text)
        logger.debug(f"Text list length: {len(sentence_list)}")

        if len(sentence_list) > self.SENTENCE_LIMIT:
            logger.warning(f"Input text too long: {len(sentence_list)}")
            last_sentence_within_limit = sentence_list[self.SENTENCE_LIMIT-1]
            if len(last_sentence_within_limit) >= 5:
                last_sentence_within_limit = '...' + \
                    last_sentence_within_limit[-5:]
            return f"太長了啦❗️ 你輸入了{len(sentence_list)}句 目前限制{self.SENTENCE_LIMIT}句話 大概到這邊而已：「{last_sentence_within_limit}」", []

        emojis = await asyncio.gather(*(self.query(sentence) for sentence in sentence_list))

        output_list = list(itertools.chain.from_iterable(
            zip(sentence_list, emojis, delimiter_list)))
        min_length = min(len(sentence_list), len(
            emojis), len(delimiter_list))
        if len(sentence_list) > min_length:
            output_list.extend(sentence_list[min_length:])
        if len(emojis) > min_length:
            output_list.extend(emojis[min_length:])
        if len(delimiter_list) > min_length:
            output_list.extend(delimiter_list[min_length:])

        output = "".join(output_list)

        output_emoji_set = set()
        for e in emojis:
            output_emoji_set = output_emoji_set.union(set(e))

        return output, output_emoji_set

    @alru_cache(maxsize=10240)
    async def query(self, input_text):
        logger.debug(f"Query: {input_text}")
        payload = {
            "model": self.model_id,
            "prompt": input_text,
            "max_tokens": 5,
            "temperature": 0.7,
            "frequency_penalty": 1.4,
            "top_p": 0.9,
            "stop": ["\n", "\t", " ", '.'],
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        async with self.query_semaphore:
            try:
                async with self.aio_session.post(urljoin(self.OPENAI_API_URL, "v1/completions"), headers=headers, json=payload) as response:
                    resp = await response.json()
                    ret = resp['choices'][0]['text']
            except Exception as e:
                logger.exception(e)
                # if we are able to get resp variable
                if 'resp' in locals():
                    logger.info(f"Erroneous Response: {resp}")
                # retry once
                async with self.aio_session.post(urljoin(self.OPENAI_API_URL, "v1/completions"), headers=headers, json=payload) as response:
                    resp = await response.json()
                    ret = resp['choices'][0]['text']

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
    return output_emoji


async def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s"
    )

    # Example usage
    openai_api_url = "http://rose.csie.ntu.edu.tw:7777"
    openai_api_key = "no_api_key_needed_for_llama_cpp"
    emoji_lm = await EmojiLmOpenAi.create(
        openai_api_url, openai_api_key, concurrency=8, sentence_limit=500
    )

    input_text = """最近UNIQLO大便事件
有網友抓到去年梯本自駕車禍那件事也是他們家在搞
出事了還在那邊嘻嘻哈哈合照

（老爸是長髮男）
"""
    output, output_emoji_set = await emoji_lm.generate(input_text)
    print(f"Output: {output}")
    print(f"Output Emoji Set: {output_emoji_set}")
    await emoji_lm.close()

if __name__ == "__main__":
    asyncio.run(main())
