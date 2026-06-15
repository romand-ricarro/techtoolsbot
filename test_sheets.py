import json, gspread
from oauth2client.service_account import ServiceAccountCredentials

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials/credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("TechTools Dashboard")
print("Available worksheets:")
for worksheet in sheet.worksheets():
    print(f"- {worksheet.title}")