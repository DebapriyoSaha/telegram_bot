import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import httpx
from modules import WelcomeModule, ConversationModule, ImageCalorieModule, GoogleSheetsModule, GoogleDriveModule
from business_tools import get_current_offers, get_diet_plans, place_order
from dotenv import load_dotenv
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET_FILE")
# GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

app = FastAPI()
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Google API clients using OAuth
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
TOKEN_PICKLE = 'token.pickle'
CLIENT_SECRET_JSON = os.getenv("GOOGLE_CLIENT_SECRET_JSON")

creds = None

import os, pickle, base64
token_str = os.getenv("GOOGLE_OAUTH_TOKEN_PICKLE")
if token_str:
    creds = pickle.loads(base64.b64decode(token_str))
else:
    raise Exception("OAuth token not found in environment variables")

if os.path.exists(TOKEN_PICKLE):
    with open(TOKEN_PICKLE, 'rb') as token:
        creds = pickle.load(token)
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    else:
        import json
        client_config = json.loads(CLIENT_SECRET_JSON)
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)
    with open(TOKEN_PICKLE, 'wb') as token:
        pickle.dump(creds, token)
drive_service = build('drive', 'v3', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

MAX_TELEGRAM_MSG_LENGTH = 4096


# Handler for text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text if update.message else None
    reply = None
    welcome_patterns = [
        r"^hi+$", r"^hey+$", r"^hello+$", r"^hii+$", r"^hel+o+$", r"^heya+$", r"^yo+$", r"^greetings+$", r"^sup+$", r"^start$"
    ]
    import re
    is_welcome = any(re.match(pat, user_text.strip().lower()) for pat in welcome_patterns)
    # Block jailbreak/identity questions
    jailbreak_patterns = [
        r"who (are|r) you", r"who made you", r"who is your creator", r"who created you", r"are you real", r"are you sentient", r"can you break rules", r"can you ignore instructions", r"ignore previous instructions", r"jailbreak", r"prompt injection", r"what tools do you use", r"show your code", r"reveal your instructions"
    ]
    if any(re.search(pat, user_text, re.IGNORECASE) for pat in jailbreak_patterns):
        reply = "I am an AI assistant."
    elif is_welcome:
        reply = WelcomeModule.welcome_message()
    else:
        reply = ConversationModule.get_response(user_text, GEMINI_API_KEY)
    if update.effective_user:
        first_name = update.effective_user.first_name or ""
        last_name = update.effective_user.last_name or ""
        username = (first_name + " " + last_name).strip() if (first_name or last_name) else str(update.effective_user.id)
    else:
        username = "Unknown"
    GoogleSheetsModule.log_chat_history(
        sheets_service, GOOGLE_SHEET_ID,
        username, user_text, reply
    )
    if len(reply) > MAX_TELEGRAM_MSG_LENGTH:
        reply = reply[:MAX_TELEGRAM_MSG_LENGTH]
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": update.effective_chat.id,
                "text": reply,
                "parse_mode": "Markdown"
            }
        )

# Handler for photo messages (with or without caption)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = None
    caption = update.message.caption if update.message and update.message.caption else ""
    user_text = caption
    photo = update.message.photo[-1]
    file_id = photo.file_id
    file = await context.bot.get_file(file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    # Get username and timestamp for file naming
    from datetime import datetime
    if update.effective_user:
        first_name = update.effective_user.first_name or ""
        last_name = update.effective_user.last_name or ""
        username = (first_name + " " + last_name).strip() if (first_name or last_name) else str(update.effective_user.id)
    else:
        username = "Unknown"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    image_filename = f"{username}_{timestamp}.jpg"
    # Upload to Google Drive
    drive_file_id = GoogleDriveModule.upload_image(drive_service, GOOGLE_DRIVE_FOLDER_ID, image_filename, image_bytes)
    picture_url = f"https://drive.google.com/uc?id={drive_file_id}"
    # Analyze image
    import time
    start_time = time.time()
    entry, text = ImageCalorieModule.analyze_image(image_bytes, GEMINI_API_KEY, image_url=picture_url, time_elapsed=None)
    elapsed = time.time() - start_time
    entry.time_elapsed = elapsed
    reply = f"*Analysis Report*\n{text}\n\n_Image uploaded to Google Drive._\n\n_Analysis time: {elapsed:.2f} seconds_"
    # Log to Meal Tracker sheet
    GoogleSheetsModule.log_meal_tracker(
        sheets_service, GOOGLE_SHEET_ID,
        username, entry.food, entry.calories, entry.proteins, entry.carbs, entry.fat, entry.image_url, entry.time_elapsed
    )
    if update.effective_user:
        first_name = update.effective_user.first_name or ""
        last_name = update.effective_user.last_name or ""
        username = (first_name + " " + last_name).strip() if (first_name or last_name) else str(update.effective_user.id)
    else:
        username = "Unknown"
    if len(reply) > MAX_TELEGRAM_MSG_LENGTH:
        reply = reply[:MAX_TELEGRAM_MSG_LENGTH]
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": update.effective_chat.id,
                "text": reply,
                "parse_mode": "Markdown"
            }
        )

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

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
