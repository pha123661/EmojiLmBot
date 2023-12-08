# 哈哈狗

[![en](https://img.shields.io/badge/lang-en-blue.svg)](./README-EN.md)
[![zh-tw](https://img.shields.io/badge/lang-zh--tw-yellow.svg)](./README.md)

這是一個根據給定文字或段落，生成表情符號的機器人。

範例：
> 使用者輸入：@哈哈狗 那你很厲害誒\
> 哈哈狗回覆：那你很厲害誒😎😎😎

## 使用方法

1. 在 LINE 上添加機器人為好友：[@255eanep](https://lin.ee/teUKO7u)\
    ![QR Code](./qr-code.png)
2. 向機器人發送帶有前綴或後綴 `@哈哈狗` 的文字或段落。\
   例如： "@哈哈狗 我愛你" 或 "我愛你 @哈哈狗"

## 在您自己的伺服器上運行哈哈狗

配置以下環境變量或使用 `.env` 文件：
- `LINE_CHANNEL_SECRET`：LINE 頻道密鑰
- `LINE_CHANNEL_ACCESS_TOKEN`：LINE 頻道訪問令牌
- `HF_API_TOKEN_LIST`：Hugging Face API 令牌列表，由空格分隔

構建：
```bash
docker build -t emoji-lm-line-bot .
```

運行：
```bash
docker run -p 8000:8000 -d --name emoji-lm-line-bot emoji-lm-line-bot
```

停止：
```bash
docker stop emoji-lm-line-bot
docker rm emoji-lm-line-bot
```