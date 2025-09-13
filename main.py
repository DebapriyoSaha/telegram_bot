import os
import re
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import httpx
from modules import WelcomeModule, ConversationModule, ImageCalorieModule, GoogleSheetsModule, GoogleDriveModule
from business_tools import get_current_offers, get_diet_plans, place_order
from dotenv import load_dotenv
import pickle
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build

load_dotenv()

# GROQ API Key for LLMs
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET_FILE")
# GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

app = FastAPI()
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Register a global error handler for Telegram bot
from telegram.ext import ContextTypes
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Telegram error: {context.error}")
    # Try to notify the user if possible
    try:
        if hasattr(update, 'effective_chat') and update.effective_chat:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": update.effective_chat.id,
                        "text": "Sorry, an internal error occurred. Please retry your request.",
                        "parse_mode": "Markdown"
                    }
                )
    except Exception as notify_err:
        print(f"Failed to notify user of error: {notify_err}")
application.add_error_handler(global_error_handler)

# Google API clients using OAuth
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
TOKEN_PICKLE = 'token.pickle'
CLIENT_SECRET_JSON = os.getenv("GOOGLE_CLIENT_SECRET_JSON")

creds = None
# In-memory chat history per user (for prototyping; use a database for production)
user_histories = {}

token_str = os.getenv("GOOGLE_OAUTH_TOKEN_PICKLE")
if token_str:
    creds = pickle.loads(base64.b64decode(token_str))
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            raise Exception("Google OAuth credentials are invalid or expired. Please refresh your token and update the environment variable.")
else:
    raise Exception("OAuth token not found in environment variables")
drive_service = build('drive', 'v3', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

MAX_TELEGRAM_MSG_LENGTH = 4096


# Handler for text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text if update.message else None
    reply = None

    welcome_patterns = [
        r"^hi+$", r"^hey+$", r"^hello+$", r"^hii+$", r"^hel+o+$", r"^heya+$",
        r"^yo+$", r"^greetings+$", r"^sup+$", r"^start$"
    ]

    jailbreak_patterns = [
        r"who (are|r) you", r"who made you", r"who is your creator",
        r"who created you", r"are you real", r"are you sentient",
        r"can you break rules", r"can you ignore instructions",
        r"ignore previous instructions", r"jailbreak",
        r"prompt injection", r"what tools do you use",
        r"show your code", r"reveal your instructions"
    ]

    if update.effective_user:
        first_name = update.effective_user.first_name or ""
        last_name = update.effective_user.last_name or ""
        username = (first_name + " " + last_name).strip() or str(update.effective_user.id)
    else:
        username = "Unknown"

    if username not in user_histories:
        user_histories[username] = []

    history = user_histories[username][-10:]  # Last 10 exchanges
    history_prompt = "".join(f"User: {msg}\nBot: {resp}\n" for msg, resp in history)

    if any(re.search(pat, user_text, re.IGNORECASE) for pat in jailbreak_patterns):
        reply = "I am an AI assistant."
        input_tokens = 0
        output_tokens = 0
    elif any(re.match(pat, user_text.strip().lower()) for pat in welcome_patterns):
        reply = WelcomeModule.welcome_message()
        input_tokens = 0
        output_tokens = 0
    else:
        full_prompt = (history_prompt + f"User: {user_text}\nBot:") if history_prompt else user_text
        reply, input_tokens, output_tokens = ConversationModule.get_response(full_prompt, GROQ_API_KEY)

    # Update history
    user_histories[username].append((user_text, reply))
    user_histories[username] = user_histories[username][-10:]

    GoogleSheetsModule.log_chat_history(
        sheets_service, GOOGLE_SHEET_ID,
        username, user_text, reply, input_tokens, output_tokens
    )

    if len(reply) > MAX_TELEGRAM_MSG_LENGTH:
        reply = reply[:MAX_TELEGRAM_MSG_LENGTH]

    # If the reply contains Markdown structure (e.g., starts with "**" or "_"), don't escape it
    def is_markdown_structured(text):
        return text.startswith("*") or text.startswith("_") or text.startswith("```")

    safe_reply = reply if is_markdown_structured(reply) else sanitize_markdown(reply)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": update.effective_chat.id,
                    "text": safe_reply,
                    "parse_mode": "Markdown"
                }
            )
            if resp.status_code != 200:
                # Fallback: plain text
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": update.effective_chat.id,
                        "text": reply
                    }
                )
    except Exception as e:
        print(f"Error sending message to Telegram: {e}")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": update.effective_chat.id,
                    "text": "Sorry, there was an error delivering your message."
                }
            )

def sanitize_markdown(text):
    import re
    # Escape only problematic MarkdownV2 special characters that break formatting,
    # but allow * _ ( ) . ! - 
    chars_to_escape = r'([\\\[\]])'  # Escape only \ [ ]
    text = re.sub(chars_to_escape, r'\\\1', text)
    return text

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
    entry, text, input_tokens, output_tokens = ImageCalorieModule.analyze_image(image_bytes, GROQ_API_KEY, image_url=picture_url, time_elapsed=None)
    elapsed = time.time() - start_time
    entry.time_elapsed = elapsed
    reply = f"*Analysis Report*\n{text}\n\n_Image uploaded to Google Drive._\n\n_Analysis time: {elapsed:.2f} seconds_"
    # Log to Meal Tracker sheet
    GoogleSheetsModule.log_meal_tracker(
        sheets_service, GOOGLE_SHEET_ID,
        username, entry.food, entry.calories, entry.proteins, entry.carbs, entry.fat, entry.image_url, entry.time_elapsed, input_tokens, output_tokens
    )
    # Store the analysis report in user_histories for context-aware chat
    if username not in user_histories:
        user_histories[username] = []
    user_histories[username].append(("[Image Analysis]", text))
    user_histories[username] = user_histories[username][-10:]
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


from telegram.ext import CommandHandler

# /start command handler
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = WelcomeModule.welcome_message()
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": update.effective_chat.id,
                "text": reply,
                "parse_mode": "Markdown"
            }
        )

# /feedback command handler
async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Please share your feedback."
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": update.effective_chat.id,
                "text": prompt,
                "parse_mode": "Markdown"
            }
        )
    # Set a flag in context to expect feedback next
    context.user_data['awaiting_feedback'] = True

# Feedback message handler
async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_feedback'):
        feedback_text = update.message.text
        # Use full name if available, else fallback to username or user id
        first_name = update.effective_user.first_name or ""
        last_name = update.effective_user.last_name or ""
        name = (first_name + " " + last_name).strip() or update.effective_user.username or str(update.effective_user.id)
        # Store feedback in Google Sheets (Feedback page)
        GoogleSheetsModule.log_feedback(sheets_service, GOOGLE_SHEET_ID, name, feedback_text)
        reply = "Thank you for your feedback!"
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": update.effective_chat.id,
                    "text": reply,
                    "parse_mode": "Markdown"
                }
            )
        context.user_data['awaiting_feedback'] = False
    else:
        await handle_text(update, context)

application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("feedback", feedback_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.initialize()
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        print(f"Webhook error: {e}")
        # Try to send a reply to the user if possible
        try:
            chat_id = None
            if 'message' in data and 'chat' in data['message']:
                chat_id = data['message']['chat']['id']
            elif 'callback_query' in data and 'message' in data['callback_query'] and 'chat' in data['callback_query']['message']:
                chat_id = data['callback_query']['message']['chat']['id']
            if chat_id:
                import httpx
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "Sorry, I couldn't analyze this image. Please upload a food item.",
                            "parse_mode": "Markdown"
                        }
                    )
        except Exception as send_err:
            print(f"Failed to send error reply to user: {send_err}")
        return {"ok": False, "error": "Webhook error occurred. Please retry your request."}

@app.get("/")
def root():
    return {"message": "Telegram Gemini Chatbot is running on Vercel."}
