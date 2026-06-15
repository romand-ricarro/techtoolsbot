import os
import json
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CLICKUP_API_TOKEN = os.getenv('CLICKUP_API_TOKEN')
CLICKUP_LIST_ID = os.getenv('CLICKUP_LIST_ID')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

# Use relative paths if the files are in the same directory as this script
current_dir = os.path.dirname(__file__)

with open(os.path.join(current_dir, 'mappings.json')) as f:
    discord_to_clickup_name = json.load(f)

with open(os.path.join(current_dir, 'questions.json')) as f:
    questions = json.load(f)

with open(os.path.join(current_dir, 'messages.json')) as f:
    messages = json.load(f)

with open(os.path.join(current_dir, 'intro_messages.json')) as f:
    intro_messages = json.load(f)
