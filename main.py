import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, WebAppInfo
from aiogram.filters import CommandStart

# ===============================
# CONFIG
# ===============================


BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
SITE_URL = os.getenv("SITE_URL")


# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ===============================
# HANDLERS
# ===============================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """
    Handler for /start command.
    Sends a button with the WebApp mini app link.
    """
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Open Mini App", web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ]
    )
    await message.answer(
        "👋 Hello! Click below to open the mini app:", reply_markup=keyboard
    )


# ===============================
# MAIN ENTRY POINT
# ===============================
async def main():
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
