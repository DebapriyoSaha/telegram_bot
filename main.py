import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import google.generativeai as genai
from business_tools import get_current_offers, get_diet_plans, place_order
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI()
application = Application.builder().token(TELEGRAM_TOKEN).build()

MAX_TELEGRAM_MSG_LENGTH = 4096

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    system_prompt = "You are a helpful assistant. Greet the user initially and respond to the user's query in a crisp and concise manner."
    user_text_lower = user_text.lower()
    if "offer" in user_text_lower or "plan" in user_text_lower:
        reply = get_current_offers()
    elif "diet" in user_text_lower:
        reply = get_diet_plans()
    elif "order" in user_text_lower:
        reply = place_order(user_text)
    else:
        contents = [
            {"role": "model", "parts": [{"text": system_prompt}]},
            {"role": "user", "parts": [{"text": user_text}]}
        ]
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("models/gemma-3-27b-it")
        response = model.generate_content(contents)
        reply = response.candidates[0].content.parts[0].text if response.candidates else "Sorry, I couldn't generate a response."
    if len(reply) > MAX_TELEGRAM_MSG_LENGTH:
        reply = reply[:MAX_TELEGRAM_MSG_LENGTH]
    await update.message.reply_text(reply)

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.initialize()
    await application.process_update(update)
    return {"ok": True}

@app.get("/")
def root():
    return {"message": "Telegram Gemini Chatbot is running on Vercel."}
