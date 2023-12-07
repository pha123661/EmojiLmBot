# Emoji LM Bot

This is a bot that uses a language model to generate emojis based on a given text or paragraph.

## Deploy

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
```

Remove:
```bash
docker rm emoji-lm-line-bot
```
