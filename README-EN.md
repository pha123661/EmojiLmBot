# Emoji LM Bot

[![en](https://img.shields.io/badge/lang-en-blue.svg)](./README-EN.md)
[![zh-tw](https://img.shields.io/badge/lang-zh--tw-yellow.svg)](./README.md)

This is a bot that uses a language model to generate emojis based on a given text or paragraph.

## Usage

1. Add the bot as a friend on LINE: [@255eanep](https://lin.ee/teUKO7u)\
    ![QR Code](./qr-code.png)
2. Send a text or paragraph to the bot, with prefix or suffix `@哈哈狗`.\
   EX: "@哈哈狗 我愛你" or "我愛你 @哈哈狗"


## Deploy this bot on your own server

Configure the following environment variables or use a `.env` file:
- `LINE_CHANNEL_SECRET`: LINE channel secret
- `LINE_CHANNEL_ACCESS_TOKEN`: LINE channel access token
- `HF_API_TOKEN_LIST`: Hugging Face API token list, separated by space

Build:
```bash
docker build -t emoji-lm-line-bot .
```

Run:
```bash
docker run -p 8000:8000 -d --name emoji-lm-line-bot emoji-lm-line-bot
```

Stop:
```bash
docker stop emoji-lm-line-bot
docker rm emoji-lm-line-bot
```
