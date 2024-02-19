import asyncio
import os
from asyncio import AbstractEventLoop
from typing import List, Optional

import discord
from dataclasses import dataclass

from dotenv import dotenv_values


@dataclass
class QueuedMessage:
    channel_id: int
    message: str


class DiscordNotifier:
    def __init__(self, token):
        intents = discord.Intents.default()
        intents.message_content = True
        self.__client = discord.Client(intents=intents)
        self.__config = dotenv_values(".env") if os.path.exists(".env") else {}
        self.__client.on_ready = self.__on_ready
        self.__message_queue: List[QueuedMessage] = []
        self.__token = token

    async def __on_ready(self):
        print("On ready")
        while len(self.__message_queue):
            message = self.__message_queue.pop()
            print("Send message")
            channel = await self.__client.fetch_channel(message.channel_id)
            await channel.send(message.message)
        await self.__client.close()

    def send_message(self, channel_id, message):
        self.__message_queue.append(QueuedMessage(channel_id, message))

    def flush(self):
        self.__client.run(self.__token)
