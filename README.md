# 哈哈狗

[![docker](https://badgen.net/badge/icon/docker?icon=docker&label=)](https://hub.docker.com/r/pha123661/emoji-lm-line-bot)

[👉English README👈](./README-EN.md)

## 使用方法

範例：
> 使用者輸入：@哈哈狗 那你很厲害誒\
> 哈哈狗回覆：那你很厲害誒😎😎😎

1. 在 LINE 上加哈哈狗好友：[@255eanep](https://lin.ee/teUKO7u)\
    ![QR Code](./qr-code.png)
2. 向哈哈狗傳送帶有前綴或後綴 `@哈哈狗` 的文字。\
   例如： "@哈哈狗 我愛你" 或 "我愛你 @哈哈狗"
3. 哈哈狗也可以加入群組使用！

## 在您自己的伺服器上運行哈哈狗！

配置以下環境變量或使用 `.env` 文件：
- `LINE_CHANNEL_SECRET`：LINE 頻道密鑰
- `LINE_CHANNEL_ACCESS_TOKEN`：LINE 頻道訪問令牌
- `HF_API_TOKEN_LIST`：Hugging Face API 令牌列表，由空格分隔

### 建立映像檔

```bash
git clone https://github.com/pha123661/EmojiLmBot.git
docker build -t emoji-lm-line-bot .
```

或者，您可以直接從 Docker Hub 拉取映像檔：

```bash
docker pull pha123661/emoji-lm-line-bot
```

### 運行

```bash
docker run -p 8000:8000 --env-file .env -d --rm --name emoji-lm-line-bot pha123661/emoji-lm-line-bot
```

### 停止

```bash
docker stop emoji-lm-line-bot
# docker rm emoji-lm-line-bot
```
