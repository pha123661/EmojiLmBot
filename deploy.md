## How to deploy the app

1. create a `.env.prod` file (or whatever the name is) in the root directory of the project and add the following environment variables:
```bash
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret
NGROK_AUTHTOKEN=your_ngrok_authtoken
HF_API_TOKEN_LIST=your_huggingface_api_token_1 your_huggingface_api_token_2
```

2. run the following command to start the app:
```bash
docker compose --env-file=.env.config --env-file=.env.prod up -d && sleep 1 && docker compose logs ngrok -n all | grep url=https:
```

3. copy the ngrok url and set the webhook url in your LINE developer console to `https://your_ngrok_url/callback`. (make sure to append `/callback` to the ngrok url)