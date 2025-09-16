import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, WebAppInfo
from aiogram.filters import CommandStart

# ===============================
# CONFIG
# ===============================
API_TOKEN = "8474653813:AAGeUtzo0quMo9qLhn9vk5xzWGi5E4l5U60"  # Replace with your actual Telegram Bot token
WEBAPP_URL = "https://a927eadfa197.ngrok-free.app/admin"  # Your Telegram mini app URL

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
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
