# Emoji LM Bot

[![docker](https://badgen.net/badge/icon/docker?icon=docker&label=)](https://hub.docker.com/r/pha123661/emoji-lm-line-bot)

[👉中文版本👈](./README.md)

This is a bot that uses a language model to generate emojis based on a given text or paragraph.

## Usage

Example:
> User prompt：@哈哈狗 I love you\
> 哈哈狗回覆：I😎😎 love🥰🥰 you😎😎

1. Add the bot as a friend on LINE: [@255eanep](https://lin.ee/teUKO7u)\
    ![QR Code](./qr-code.png)
2. Send a text or paragraph to the bot, with prefix or suffix `@哈哈狗`.\
   EX: "@哈哈狗 I love you" or "I love you @哈哈狗"
3. Add 哈哈狗 into groups if you want.

## Deploy this bot on your own server

Configure the following environment variables or use a `.env` file:
- `LINE_CHANNEL_SECRET`: LINE channel secret
- `LINE_CHANNEL_ACCESS_TOKEN`: LINE channel access token
- `HF_API_TOKEN_LIST`: Hugging Face API token list, separated by space

### Build

```bash
git clone https://github.com/pha123661/EmojiLmBot.git
docker build -t emoji-lm-line-bot .
```

Alternatively, you can pull the image directly from Docker Hub:

```bash
docker pull pha123661/emoji-lm-line-bot
```

### Run

```bash
docker run -p 8000:8000 --env-file .env -d --rm --name emoji-lm-line-bot emoji-lm-line-bot
```

### Stop

```bash
docker stop emoji-lm-line-bot
# docker rm emoji-lm-line-bot
```
