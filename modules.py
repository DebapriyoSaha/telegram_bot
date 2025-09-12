import os
from pydantic import BaseModel
from datetime import datetime
class MealTrackerEntry(BaseModel):
    date: str
    time: str
    food: str
    calories: str
    proteins: str
    carbs: str
    fat: str
    image_url: str
    time_elapsed: float
import google.generativeai as genai
from telegram import Update
from telegram.ext import ContextTypes

image_prompt = '''
    You are an expert nutrition assistant. Analyze the food item in the image and respond clearly in this exact format using bold and italics:

    Food: <name of food item>
    Calories: <calories in kcal>
    Proteins: <protein in grams>
    Carbs: <carbs in grams>
    Fat: <fat in grams>

    Do NOT include any additional text or commentary.
    Only respond with the most accurate protein, carbs, and fat values you can infer from the image.
    Strictly mention the sources of protein, carbs and fat you can identify in the food item.
    Strictly use double asterisks for bold and single underscores for italics as per Telegram Markdown formatting.
    If you cannot analyze the image, reply: "Sorry, I couldn't analyze that."
'''

text_prompt = '''
    You are a helpful assistant. Respond to the user's query in a crisp and concise manner.
    Use double asterisks for bold and single underscores for italics as per Telegram Markdown formatting.
    Use limited smileys/emojis to make the response friendly.
    Don not use too much italics
    Use proper formatting for lists and line breaks.
    Use numbering for lists where applicable.
'''

class WelcomeModule:
    @staticmethod
    def welcome_message():
        return "👋 Welcome! Please upload an image of your meal to find out its calorie content. You can also chat with me about anything!"

class ConversationModule:
    @staticmethod
    def get_response(user_text, groq_api_key):
        # Guard rails: block harmful, sexual, or offensive messages
        import re
        import requests
        block_patterns = [
            r"sex|sexual|porn|nude|naked|violence|kill|murder|hate|racist|abuse|offensive|suicide|self[- ]?harm|terror|bomb|drugs|weapon|assault|molest|rape|harass|bully|exploit|gore|blood|torture|explicit|obscene|curse|swear|profanity|slur"
        ]
        if any(re.search(pat, user_text, re.IGNORECASE) for pat in block_patterns):
            return "Sorry, I can't assist with that.", 0, 0
        # Groq API call for text
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openai/gpt-oss-20b",
            "messages": [
                {"role": "system", "content": text_prompt},
                {"role": "user", "content": user_text}
            ],
            "max_tokens": 1024,
            "temperature": 0.7
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                input_tokens = data.get("usage", {}).get("prompt_tokens", 0)
                output_tokens = data.get("usage", {}).get("completion_tokens", 0)
                return content, input_tokens, output_tokens
            else:
                return "Sorry, I couldn't generate a response.", 0, 0
        except Exception:
            return "Sorry, I couldn't generate a response.", 0, 0

class ImageCalorieModule:
    @staticmethod
    def analyze_image(image_bytes, groq_api_key, image_url=None, time_elapsed=None):
        import requests
        import base64
        # Convert image bytes to base64 string
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        image_b64_url = f"data:image/jpeg;base64,{image_b64}"
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": image_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze the food in this image."},
                        {"type": "image_url", "image_url": {"url": image_b64_url}}
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.2
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                input_tokens = data.get("usage", {}).get("prompt_tokens", 0)
                output_tokens = data.get("usage", {}).get("completion_tokens", 0)
            else:
                text = "Sorry, I couldn't analyze the image."
                input_tokens = 0
                output_tokens = 0
        except Exception:
            text = "Sorry, I couldn't analyze the image."
            input_tokens = 0
            output_tokens = 0
        # Log raw response for debugging
        print("Groq raw response:", text)
        import re
        food = calories = proteins = carbs = fat = ""
        # Improved regex: capture ranges, parentheticals, and all text after the label
        def extract_field(label, text):
            # Match lines like: Calories: _Approximately 500-600 kcal (estimated)_
            pattern = rf"{label}:\s*([\*_]*)(.+)"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(2).strip()
                # Remove Markdown formatting
                value = re.sub(r"^[*_]+|[_*]+$", "", value)
                # Remove 'Approximately', 'estimated', etc.
                value = re.sub(r"(?i)approximately|estimated|about|around", "", value).strip()
                return value
            return ""

        food = extract_field("Food", text)
        calories = extract_field("Calories", text)
        proteins = extract_field("Proteins", text)
        carbs = extract_field("Carbs", text)
        fat = extract_field("Fat", text)
        now = datetime.now()
        entry = MealTrackerEntry(
            date=now.strftime('%Y-%m-%d'),
            time=now.strftime('%H:%M:%S'),
            food=food,
            calories=calories,
            proteins=proteins,
            carbs=carbs,
            fat=fat,
            image_url=image_url or "",
            time_elapsed=time_elapsed if time_elapsed is not None else 0.0
        )
        return entry, text, input_tokens, output_tokens

class GoogleSheetsModule:
    @staticmethod
    def log_feedback(service, spreadsheet_id, username, feedback_text):
        from datetime import datetime
        now = datetime.now()
        sheet = service.spreadsheets()
        # Get current number of rows for auto-incremental ID
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Feedback!B2:B").execute()
        values = result.get('values', [])
        next_id = len(values) + 1
        row = [next_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), username, feedback_text]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range="Feedback!B1",
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()
    @staticmethod
    def log_chat_history(service, spreadsheet_id, username, user_query, bot_message, input_tokens=0, output_tokens=0):
        from datetime import datetime
        now = datetime.now()
        # Get current number of rows for auto-incremental ID
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Chat History!B2:B").execute()
        values = result.get('values', [])
        next_id = len(values) + 1
        row = [next_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), username, user_query, bot_message, input_tokens, output_tokens]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range="Chat History!B1",
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()

    @staticmethod
    def log_meal_tracker(service, spreadsheet_id, client, food, calories, proteins, carbs, fat, picture_url, time_elapsed, input_tokens=0, output_tokens=0):
        from datetime import datetime
        now = datetime.now()
        # Get current number of rows for auto-incremental ID
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Meal Tracker!B2:B").execute()
        values = result.get('values', [])
        next_id = len(values) + 1
        row = [next_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), client, food, calories, proteins, carbs, fat, picture_url, time_elapsed, input_tokens, output_tokens]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range="Meal Tracker!B1",
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()

class GoogleDriveModule:
    @staticmethod
    def upload_image(service, folder_id, file_name, image_bytes):
        from googleapiclient.http import MediaIoBaseUpload
        import io
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
