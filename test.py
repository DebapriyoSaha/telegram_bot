# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# import pickle

# SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

# flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
# creds = flow.run_local_server(port=0)

# # Save the credentials for future use
# with open('token.pickle', 'wb') as token:
#     pickle.dump(creds, token)

# drive_service = build('drive', 'v3', credentials=creds)
# sheets_service = build('sheets', 'v4', credentials=creds)
# print('Google Drive and Sheets services are ready!')

# import google.generativeai as genai

# genai.configure(api_key="AIzaSyBwD-T1qemfiCSZdGbEE_s6Jlub5DCcsO4")
# for m in genai.list_models():
#     print(m.name)

import base64
with open("token.pickle", "rb") as f:
    token_b64 = base64.b64encode(f.read()).decode()
    print(token_b64)