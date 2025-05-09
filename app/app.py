import asyncio
import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from typing import Protocol
from urllib.parse import parse_qsl

from aiohttp import web
from aiohttp.web_runner import TCPSite
from emojilm_openai import EmojiLmOpenAi
from linebot.v3 import WebhookParser, messaging
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (AsyncApiClient, AsyncMessagingApi,
                                  Configuration, QuickReply, QuickReplyItem,
                                  ReplyMessageRequest,
                                  ShowLoadingAnimationRequest, TextMessage)
from linebot.v3.webhooks import (FollowEvent, JoinEvent, LeaveEvent,
                                 MessageEvent, PostbackEvent,
                                 TextMessageContent, UnfollowEvent)
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, String,
                        Text)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

logger = logging.getLogger()
Base = declarative_base()


class EmojiLm(Protocol):
    async def generate(self, input_text) -> tuple[str, set[str]]:
        ...


class UserStatus(Base):
    __tablename__ = 'user_status'
    id = Column(String, primary_key=True)
    block = Column(Boolean, default=False)
    last_block = Column(DateTime)
    help_count = Column(Integer, default=0)
    msg_count = Column(Integer, default=0)
    first_use = Column(DateTime)
    last_use = Column(DateTime)


class GroupStatus(Base):
    __tablename__ = 'group_status'
    id = Column(String, primary_key=True)
    leave = Column(Boolean, default=False)
    msg_count = Column(Integer, default=0)
    first_use = Column(DateTime)
    last_use = Column(DateTime)


class EmojiStatus(Base):
    __tablename__ = 'emoji_status'
    id = Column(Integer, primary_key=True, autoincrement=True)
    # Define fields if used


class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(Integer, primary_key=True, autoincrement=True)
    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=False)
    user_id = Column(String, ForeignKey('user_status.id'))
    create_time = Column(DateTime, default=datetime.utcnow)
    preference = Column(Integer)
    user = relationship('UserStatus')


class Handler:
    BOT_NAME = "哈哈狗"

    def __init__(
        self,
        line_bot_api: AsyncMessagingApi,
        parser: WebhookParser,
        emojilm: EmojiLm,
        database_url: str
    ):
        self.line_bot_api = line_bot_api
        self.parser = parser
        self.emojilm = emojilm

        self.engine = create_async_engine(database_url, echo=False)
        self.Session = sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def handle_callback(self, request):
        signature = request.headers['X-Line-Signature']
        body = await request.text()
        try:
            events = self.parser.parse(body, signature)
        except InvalidSignatureError:
            logger.error("Invalid signature.")
            return web.Response(status=400, text='Invalid signature')

        async with self.Session() as session:
            for event in events:
                if isinstance(event, JoinEvent):
                    await self.send_help_message(event)
                    stmt = insert(GroupStatus).values(
                        id=event.source.group_id,
                        leave=False,
                        first_use=datetime.fromtimestamp(event.timestamp/1000)
                    ).on_conflict_do_update(
                        index_elements=[GroupStatus.id],
                        set_={"leave": False}
                    )
                    await session.execute(stmt)
                elif isinstance(event, FollowEvent):
                    pass  # no DB action
                elif isinstance(event, LeaveEvent):
                    stmt = insert(GroupStatus).values(
                        id=event.source.group_id,
                        leave=True
                    ).on_conflict_do_update(
                        index_elements=[GroupStatus.id],
                        set_={"leave": True}
                    )
                    await session.execute(stmt)
                elif isinstance(event, UnfollowEvent):
                    stmt = insert(UserStatus).values(
                        id=event.source.user_id,
                        block=True,
                        last_block=datetime.fromtimestamp(event.timestamp/1000)
                    ).on_conflict_do_update(
                        index_elements=[UserStatus.id],
                        set_={"block": True, "last_block": datetime.fromtimestamp(
                            event.timestamp/1000)}
                    )
                    await session.execute(stmt)
                elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                    await self.handle_text_message(event, session)
                elif isinstance(event, PostbackEvent):
                    await self.handle_post_back(event, session)
            await session.commit()
        return web.Response(text="OK\n")

    async def send_help_message(self, event):
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text=f"在訊息前或後+上 @{self.BOT_NAME} 就會幫你+emoji\nEX: @{self.BOT_NAME} 那你很厲害誒")]
            )
        )

    async def handle_text_message(self, event, session: AsyncSession):
        input_text = event.message.text.strip()
        await self.line_bot_api.show_loading_animation(
            ShowLoadingAnimationRequest(
                chatId=event.source.user_id, loadingSeconds=60)
        )
        if input_text == f"{self.BOT_NAME}幫幫我":
            await self.send_help_message(event)
            stmt = insert(UserStatus).values(
                id=event.source.user_id,
                help_count=1,
                first_use=datetime.fromtimestamp(event.timestamp/1000)
            ).on_conflict_do_update(
                index_elements=[UserStatus.id],
                set_={"help_count": UserStatus.help_count + 1}
            )
            await session.execute(stmt)
            return
        # extract mention
        if input_text.startswith(f"@{self.BOT_NAME}") or input_text.startswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[len(f"@{self.BOT_NAME}"):]
        elif input_text.endswith(f"@{self.BOT_NAME}") or input_text.endswith(f"＠{self.BOT_NAME}"):
            input_text = input_text[:-len(f"@{self.BOT_NAME}")]
        else:
            return
        if not input_text:
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(
                        text="請給我一點文字啦 EX: @{self.BOT_NAME} 那你很厲害誒")]
                )
            )
            return
        try:
            output_text_with_emoji, output_emoji_set = await self.emojilm.generate(input_text)
        except Exception:
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="AI服務暫時壞了 sorry la 稍後再試")]
                )
            )
            return
        if not output_emoji_set:
            await self.line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=output_text_with_emoji)]
                )
            )
            return
        # insert feedback
        feedback = Feedback(
            input_text=input_text,
            output_text=output_text_with_emoji,
            user_id=event.source.user_id,
            create_time=datetime.fromtimestamp(event.timestamp/1000)
        )
        session.add(feedback)
        await session.flush()
        feedback_id = feedback.id
        # reply
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text=output_text_with_emoji,
                    quickReply=construct_quick_reply(feedback_id)
                )]
            )
        )
        # update counts
        if event.source.type == "group":
            stmt = insert(GroupStatus).values(
                id=event.source.group_id,
                msg_count=1,
                first_use=datetime.fromtimestamp(event.timestamp/1000),
                last_use=datetime.fromtimestamp(event.timestamp/1000)
            ).on_conflict_do_update(
                index_elements=[GroupStatus.id],
                set_={
                    "msg_count": GroupStatus.msg_count + 1,
                    "last_use": datetime.fromtimestamp(event.timestamp/1000)
                }
            )
            await session.execute(stmt)
        stmt = insert(UserStatus).values(
            id=event.source.user_id,
            msg_count=1,
            first_use=datetime.fromtimestamp(event.timestamp/1000),
            last_use=datetime.fromtimestamp(event.timestamp/1000)
        ).on_conflict_do_update(
            index_elements=[UserStatus.id],
            set_={
                "msg_count": UserStatus.msg_count + 1,
                "last_use": datetime.fromtimestamp(event.timestamp/1000)
            }
        )
        await session.execute(stmt)

    async def handle_post_back(self, event, session: AsyncSession):
        backdata = dict(parse_qsl(event.postback.data))
        if backdata.keys() != {'action', 'feedback_id'}:
            raise ValueError("Invalid quickreply!")
        preference_value = 1 if backdata['action'] == 'like' else -1
        fb_id = int(backdata['feedback_id'])
        stmt = insert(Feedback).values(
            id=fb_id,
            preference=preference_value
        ).on_conflict_do_update(
            index_elements=[Feedback.id],
            set_={"preference": preference_value}
        )
        await session.execute(stmt)
        await self.line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="感謝回饋🐶")]
            )
        )


def construct_quick_reply(feedback_id):
    from linebot.v3.messaging import QuickReply, QuickReplyItem
    return QuickReply.from_dict({
        "items": [
            {"type": "action", "action": {"type": "postback", "label": "讚啦😎",
                                          "data": f"action=like&feedback_id={feedback_id}", "displayText": "讚啦😎"}},
            {"type": "action", "action": {"type": "postback", "label": "爛啦🥲",
                                          "data": f"action=dislike&feedback_id={feedback_id}", "displayText": "爛啦🥲"}},
        ]
    })


async def main(args):
    InitLogger(logger, 'app.log')
    CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
    CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not all([CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN, DATABASE_URL]):
        print(
            "Please set LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, and DATABASE_URL.")
        sys.exit(1)
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    async_api_client = AsyncApiClient(configuration)
    line_bot_api = AsyncMessagingApi(async_api_client)
    parser = WebhookParser(CHANNEL_SECRET)
    emojilm = await EmojiLmOpenAi.create(
        OPENAI_API_URL=os.getenv('LLAMA_CPP_SERVER_URL'),
        OPENAI_API_KEY="no_key_required",
        concurrency=8,
        sentence_limit=500
    )
    handler = Handler(line_bot_api, parser, emojilm, DATABASE_URL)
    await handler.init_db()
    app = web.Application()
    app.add_routes([web.post('/callback', handler.handle_callback)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = TCPSite(runner=runner, port=args.port)
    await site.start()
    try:
        while True:
            await asyncio.sleep(600)
    finally:
        await site.stop()
        await runner.cleanup()
        await async_api_client.close()
        await emojilm.close()


def InitLogger(rootLogger, log_path: str) -> logging.Logger:
    logFormatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(module)-16s:%(lineno)-4s] %(message)s"
    )
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
    parser.add_argument('--port', type=int, default=7778)
    args = parser.parse_args()
    if os.getenv('DEBUG', '0').lower() in ('true', '1', 't'):
        setattr(args, 'debug', True)
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Server stopped.")
