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

    If you cannot analyze the image, reply: "Sorry, I couldn't analyze that."
'''

text_prompt = '''
    You are a helpful assistant. Respond to the user's query in a crisp and concise manner.
    Use double asterisks for bold and single underscores for italics as per Telegram Markdown formatting.
    Don not use too much italics
    Use proper formatting for lists and line breaks.
    Use numbering for lists where applicable.
'''

class WelcomeModule:
    @staticmethod
    def welcome_message():
        return "👋 Welcome! Please upload an image of your food to find out its calorie content. You can also chat with me about anything!"

class ConversationModule:
    @staticmethod
    def get_response(user_text, gemini_api_key):
        # Guard rails: block harmful, sexual, or offensive messages
        import re
        block_patterns = [
            r"sex|sexual|porn|nude|naked|violence|kill|murder|hate|racist|abuse|offensive|suicide|self[- ]?harm|terror|bomb|drugs|weapon|assault|molest|rape|harass|bully|exploit|gore|blood|torture|explicit|obscene|curse|swear|profanity|slur"
        ]
        if any(re.search(pat, user_text, re.IGNORECASE) for pat in block_patterns):
            return "Sorry, I can't assist with that."
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        # system_prompt = (
        #     "You are a helpful assistant. Respond to the user's query in a crisp and concise manner."
        #     "Use double asterisks for bold and single underscores for italics as per Telegram Markdown formatting."
        #     "Use proper formatting for lists and line breaks."
        #     "Strictly refuse to answer any harmful, sexual, violent, or offensive requests. If the user asks anything inappropriate, reply: 'Sorry, I can't assist with that.'"
        # )
        contents = [
            {"role": "model", "parts": [{"text": text_prompt}]},
            {"role": "user", "parts": [{"text": user_text}]}
        ]
        response = model.generate_content(contents)
        return response.candidates[0].content.parts[0].text if response.candidates else "Sorry, I couldn't generate a response."

class ImageCalorieModule:
    @staticmethod
    def analyze_image(image_bytes, gemini_api_key, image_url=None, time_elapsed=None):
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        prompt = (
            "You are a nutrition expert. Analyze the food item in this image and reply in the following format, using double asterisks for bold (Telegram markdown):\n"
            "**Food:** <food>\n**Calories:** <calories>\n**Proteins:** <proteins>\n**Carbs:** <carbs>\n**Fat:** <fat>\n"
            "Keep the response crisp and concise."
        )
        contents = [
            {"role": "user", "parts": [
                {"text": image_prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}}
            ]}
        ]
        response = model.generate_content(contents)
        text = response.candidates[0].content.parts[0].text if response.candidates else "Sorry, I couldn't analyze the image."
        import re
        food = calories = proteins = carbs = fat = ""
        food_match = re.search(r"\*\*Food:\*\*\s*(.*)", text)
        calories_match = re.search(r"\*\*Calories:\*\*\s*(\d+)", text)
        proteins_match = re.search(r"\*\*Proteins:\*\*\s*(\d+)", text)
        carbs_match = re.search(r"\*\*Carbs:\*\*\s*(\d+)", text)
        fat_match = re.search(r"\*\*Fat:\*\*\s*(\d+)", text)
        if food_match:
            food = food_match.group(1)
        if calories_match:
            calories = calories_match.group(1)
        if proteins_match:
            proteins = proteins_match.group(1)
        if carbs_match:
            carbs = carbs_match.group(1)
        if fat_match:
            fat = fat_match.group(1)
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
        return entry, text

class GoogleSheetsModule:
    @staticmethod
    def log_chat_history(service, spreadsheet_id, username, user_query, bot_message):
        from datetime import datetime
        now = datetime.now()
        # Get current number of rows for auto-incremental ID
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Chat History!B2:B").execute()
        values = result.get('values', [])
        next_id = len(values) + 1
        row = [next_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), username, user_query, bot_message]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range="Chat History!B1",
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()

    @staticmethod
    def log_meal_tracker(service, spreadsheet_id, client, food, calories, proteins, carbs, fat, picture_url, time_elapsed):
        from datetime import datetime
        now = datetime.now()
        # Get current number of rows for auto-incremental ID
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Meal Tracker!B2:B").execute()
        values = result.get('values', [])
        next_id = len(values) + 1
        row = [next_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), client, food, calories, proteins, carbs, fat, picture_url, time_elapsed]
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
