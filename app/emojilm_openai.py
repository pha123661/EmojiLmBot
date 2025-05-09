import asyncio
import itertools
import logging
import re
from asyncio import Semaphore
from urllib.parse import urljoin

import aiohttp
import emoji
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
        sentence_limit=300
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
            "temperature": 0.3,
            "frequency_penalty": 1.1,
            "top_p": 0.7,
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
    ret = ''.join(char for char in output_emoji if emoji.is_emoji(char))

    if output_emoji != ret:
        logger.warning(f"Model output contains non-emoji: `{output_emoji}` Post Processed: `{ret}`")

    return ret


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

12345678

立法院今（9日）三讀通過國民黨立法院黨團與民眾黨立法院黨團版「紀念日及節日實施條例」草案，該案被在野稱為「還假於民」法案。此次新增教師節、光復節、行憲紀念日（同日也是聖誕節）、小年夜等4天休假一天，勞動假從原本僅勞工族群放假一日，改為全國性休假，意即所謂的「4+1」休假。

國民黨立委賴士葆、許宇甄分別擬具「紀念日及節日實施法草案」、藍委牛煦庭、林思銘、葉元之等、民眾黨立法院黨團分別擬具「紀念日及節日實施條例草案」等多項相關草案，經內政委員會協商後，交付由韓國瑜召集的朝野黨團協商，但昨天朝野黨團協商就此並無共識便全案交付二讀。國民黨團與民眾黨9日針對「紀念日及節日實施條例」草案共提出再修正動議。

立法院9日下午1時半許進行逐條表決，全案結果皆為出席110位委員，贊成59位、反對51位，贊成者多數通過。經藍白黨團提議進行三讀，在議事人員宣讀全案後，進行全案表決。立法院長韓國瑜宣告，出席107位委員，贊成57位、反對50位，贊成者多數通過，全案表決通過，「紀念日及節日實施條例」制訂通過。

該案指出，為彰顯紀念日及節日的特殊意義，並規定放假日期及舉行慶祝或紀念活動，以紀念國家發展歷史、傳承各族群傳統民俗及促進多元文化發展，特制定本條例。 根據該條例第4條，孔子誕辰紀念日（教師節，9月28日）、台灣光復暨金門古寧頭大捷紀念日（光復節，10月25日）、行憲紀念日（12月25日）列放假一天。

條例第6條第1項規定，「除夕及春節：自農曆十二月末日之前一日至翌年一月三日，放假五日」；換句話說，「小年夜」被列入假日。根據同條例第2項，勞動節改為全國放假。另外，同條例第3項也寫明，「原住民族歲時祭儀：由原住民依其族別歲時祭儀擇定三日放假」，代表原住民族歲時祭儀從1天增至3天。

條例第9條提及，由於上述第4、6條等放假日調整，「交通運輸、警察、消防、海巡、醫療、關務、矯正等全年無休實施輪班、輪休制度之政府機關或機構，由目的事業主管機關調移之」、「軍事機關基於國防安全考量及因應戰備之需要，由目的事業主管機關視實際需要調移之」。

國民黨團表示，這次「還假於民」的法案，是國民黨團在年初定調的優先民生法案，既然答應要還給勞工國定假日，就必須說到做到。本次修法增加的國定假日不只可以給予勞工更多的休息時間，降低工時、減緩血汗，有更多的時間能夠陪伴家人，想要有更多收入的勞工也能因此獲得雙倍工資。對勞工而言，只贏不輸。

國民黨團說，紀念日及節日實施條例草案三讀，不只是履行國民黨對勞工的承諾，也是國民黨展現，當民進黨傾全國全黨之力在做政治鬥爭、撕裂社會、詐欺治國，國民黨仍然無所畏懼，堅持推動民生議題，堅持做對的事情，為人民的福利而努力。
"""
    output, output_emoji_set = await emoji_lm.generate(input_text)
    print(f"Output: {output}")
    print(f"Output Emoji Set: {output_emoji_set}")
    await emoji_lm.close()

if __name__ == "__main__":
    asyncio.run(main())
