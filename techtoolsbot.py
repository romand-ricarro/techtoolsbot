import os
import json
import random
import time
import asyncio
import datetime
import uuid

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# Google Sheets imports
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError
from http.client import RemoteDisconnected
from requests.exceptions import RequestException

# ----- Load Environment -----
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))
GUILD_ID = int(os.getenv("GUILD_ID", 0))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Clickup Report")
WORKSHEET_GID = os.getenv("WORKSHEET_GID")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "credentials/credentials.json")

# ----- JSON Configs -----
current_dir = os.path.dirname(__file__)

with open(os.path.join(current_dir, 'intro_messages.json'), 'r', encoding='utf-8') as f:
    intro_data = json.load(f)

with open(os.path.join(current_dir, 'messages.json'), 'r', encoding='utf-8') as f:
    messages = json.load(f)

with open(os.path.join(current_dir, 'questions.json'), 'r', encoding='utf-8') as f:
    questions = json.load(f)

# (Optional) Discord-to-username mappings
discord_to_username = {}
mappings_path = os.path.join(current_dir, 'mappings.json')
if os.path.exists(mappings_path):
    with open(mappings_path, 'r', encoding='utf-8') as f:
        discord_to_username = json.load(f)

# ----- Bot Setup -----
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track active sessions and cooldowns
active_sessions = {}
cooldowns = {}

# Keep a random cycle of intro messages
_intro_list = random.sample(intro_data["intro_messages"], len(intro_data["intro_messages"]))

def get_intro_message() -> str:
    """Return a random 'booting up' message from the JSON, cycling through them."""
    global _intro_list
    if not _intro_list:
        _intro_list = random.sample(intro_data["intro_messages"], len(intro_data["intro_messages"]))
    return _intro_list.pop()

@bot.event
async def on_ready():
    print(f"[READY] Logged in as {bot.user} (ID: {bot.user.id})")

    # Post initial embed with wand reaction
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            embed = discord.Embed(
                title="🧙‍♂️ Hi, I'm Harry Botter – your wizarding guide to all things support!",
                description="Ready for a magical journey? Click the wand below and let's make some tech magic! 🪄💫",
                color=0x00ff00
            )
            msg = await channel.send(
                "Step into the enchanted gateway – your Portkey 🌀 to wizarding support and magical solutions! ✨",
                embed=embed
            )
            await msg.add_reaction('🪄')  # Add reaction
        except discord.HTTPException as e:
            print(f"[ERROR] Failed to send embed or add reaction: {e}")
    else:
        print("[WARNING] Bot could not find the specified CHANNEL_ID.")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    print("[DEBUG] on_raw_reaction_add triggered.")
    print(f"[DEBUG] payload = {payload}")

    # 1) Must be wand emoji
    if str(payload.emoji) != '🪄':
        print(f"[DEBUG] Reaction is not the wand emoji, ignoring. (emoji={payload.emoji})")
        return
    else:
        print("[DEBUG] Reaction is the wand emoji.")

    # 2) Must be in correct channel
    if payload.channel_id != CHANNEL_ID:
        print(f"[DEBUG] Reaction channel {payload.channel_id} != {CHANNEL_ID}, ignoring.")
        return
    else:
        print(f"[DEBUG] Reaction channel matches CHANNEL_ID = {CHANNEL_ID}.")

    # 3) Ignore if from the bot itself
    if payload.user_id == bot.user.id:
        print("[DEBUG] on_raw_reaction_add from bot user, ignoring.")
        return

    # Fetch the user & channel
    user = await bot.fetch_user(payload.user_id)
    channel = bot.get_channel(payload.channel_id)

    print(f"[DEBUG] user = {user}, channel = {channel}")
    if not user or not channel:
        print("[DEBUG] User or channel is None, cannot proceed.")
        return

    # 4) Check cooldown
    if user.id in cooldowns:
        if time.time() < cooldowns[user.id]:
            remaining = cooldowns[user.id] - time.time()
            print(f"[DEBUG] User {user.id} is on cooldown. time left ~ {remaining} seconds.")
            await notify_cooldown(user)
            # Try to remove reaction with proper error handling
            try:
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, user)
            except discord.errors.Forbidden:
                print("[WARNING] Could not remove reaction - bot lacks 'Manage Messages' permission.")
            except Exception as e:
                print(f"[ERROR] Error removing reaction: {e}")
            return
        else:
            print(f"[DEBUG] User {user.id} cooldown expired, proceeding.")
    else:
        print(f"[DEBUG] No cooldown record for user {user.id}, proceeding.")

    # 5) Check active session
    if user.id in active_sessions:
        print(f"[DEBUG] User {user.id} is already in an active session, sending notice.")
        await user.send(messages["active_session"])
        # Try to remove reaction with proper error handling
        try:
            msg = await channel.fetch_message(payload.message_id)
            await msg.remove_reaction(payload.emoji, user)
        except discord.errors.Forbidden:
            print("[WARNING] Could not remove reaction - bot lacks 'Manage Messages' permission.")
        except Exception as e:
            print(f"[ERROR] Error removing reaction: {e}")
        return
    else:
        print(f"[DEBUG] No active session for user {user.id}, starting new flow.")

    # Start Q&A flow
    active_sessions[user.id] = {}
    print(f"[DEBUG] Set active_sessions[{user.id}]. Running QA flow.")
    await run_qa_flow(user)

    # Try to remove reaction with proper error handling
    try:
        msg = await channel.fetch_message(payload.message_id)
        await msg.remove_reaction(payload.emoji, user)
        print("[DEBUG] Reaction removed after starting QA flow.")
    except discord.errors.Forbidden:
        print("[WARNING] Could not remove reaction - bot lacks 'Manage Messages' permission.")
    except Exception as e:
        print(f"[ERROR] Error removing reaction: {e}")

@bot.event
async def on_message(message: discord.Message):
    """
    If user DMs "hello"/"hi"/"hey", start the Q&A flow.
    We must manually process commands first.
    """
    await bot.process_commands(message)

    if not isinstance(message.channel, discord.DMChannel):
        return
    if message.author == bot.user:
        return

    if message.content.lower() in ["hello", "hi", "hey"]:
        user = message.author

        # Check cooldown
        if user.id in cooldowns and time.time() < cooldowns[user.id]:
            await notify_cooldown(user)
            return

        # Check active session
        if user.id in active_sessions:
            await user.send(messages["active_session"])
            return

        # Start Q&A
        active_sessions[user.id] = {}
        await run_qa_flow(user)

async def run_qa_flow(user: discord.User):
    print(f"[DEBUG] Starting Q&A flow for user {user.id}")

    try:
        # First check if credentials exist to avoid starting a conversation that will fail
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            error_msg = f"Credentials file not found at {SERVICE_ACCOUNT_FILE}"
            print(f"[ERROR] {error_msg}")
            await user.send(f"Yikes! Something went wrong while preparing: {error_msg}")
            end_session(user.id)
            return

        # Intro
        await user.send(get_intro_message())
        print("[DEBUG] Sent intro message.")
        await asyncio.sleep(2)

        # 1) tasks
        task_name = await prompt_until_valid(
            user,
            question=questions["task_name"],
            error_msg=messages["task_name_empty"],
            validator=lambda txt: len(txt.strip()) > 0
        )
        print("[DEBUG] Received task_name response: ", task_name)
        if not task_name:
            print("[DEBUG] No valid task_name, ending session.")
            end_session(user.id)
            return

        # 2) description
        task_desc = await prompt_until_valid(
            user,
            question=questions["task_description"],
            error_msg=messages["task_description_empty"],
            validator=lambda txt: len(txt.strip()) > 0
        )
        print("[DEBUG] Received task_desc response: ", task_desc)
        if not task_desc:
            print("[DEBUG] No valid description, ending session.")
            end_session(user.id)
            return

        # 3) relevant link (optional)
        relevant_link = await prompt_until_valid(
            user,
            question=questions["relevant_link"],
            error_msg="",  # No error message needed as it's optional
            validator=None  # No validation needed as it's optional
        )
        print("[DEBUG] Received relevant_link response: ", relevant_link)
        if not relevant_link or relevant_link.lower() == 'skip':
            relevant_link = ""

        # 4) urgency -> priority
        valid_priorities = ["urgent", "high", "medium", "low"]
        user_urgency = await prompt_until_valid(
            user,
            question=questions["task_urgency"],
            error_msg=messages["invalid_priority"],
            validator=lambda txt: txt.lower() in valid_priorities
        )
        print("[DEBUG] Received urgency: ", user_urgency)
        if not user_urgency:
            print("[DEBUG] No valid urgency, ending session.")
            end_session(user.id)
            return

        # 5) assignee
        assignee = discord_to_username.get(str(user.id), str(user.id))
        print(f"[DEBUG] Mapped user {user.id} to assignee = {assignee}")

        # 6) Submit to Google Sheets
        print("[DEBUG] Submitting to Google Sheets...")
        try:
            result = await submit_to_google_sheets(
                tasks=task_name,
                description=task_desc,
                complexity=user_urgency,
                assignee=assignee,
                relevant_link=relevant_link
            )
            print("[DEBUG] Google Sheets response: ", result)

            if not result.get("ok"):
                err = result.get("error", "Unknown error")
                await user.send(f"Yikes! Something went wrong while creating the task: {err}")
                print("[ERROR] Task creation failure, error:", err)
            else:
                link = result.get("task_url", "No link")
                await user.send(messages["task_creation_success"].format(task_url=link))
                await asyncio.sleep(1)
                await user.send(messages["thank_you"])
                print("[DEBUG] Task creation success. Provided link:", link)
        except Exception as sheet_error:
            error_msg = f"Unexpected error: {str(sheet_error)}"
            await user.send(f"Yikes! Something went wrong while creating the task: {error_msg}")
            print(f"[ERROR] Exception during sheet submission: {sheet_error}")

        # Set cooldown (example: 60s)
        cooldowns[user.id] = time.time() + 60
        print(f"[DEBUG] Set cooldown for user {user.id} to {cooldowns[user.id]}")

    except discord.Forbidden:
        print(f"[ERROR] Forbidden error: Cannot DM user {user.id}.")
    except Exception as e:
        print(f"[ERROR] Exception in run_qa_flow: {e}")
        try:
            await user.send(f"Yikes! Something went wrong: {str(e)}")
        except:
            pass
    finally:
        end_session(user.id)
        print(f"[DEBUG] Ended session for user {user.id}")

def end_session(user_id: int):
    if user_id in active_sessions:
        del active_sessions[user_id]

async def notify_cooldown(user: discord.User):
    remaining = cooldowns[user.id] - time.time()
    mins, secs = divmod(remaining, 60)
    await user.send(messages["cooldown_message"].format(minutes=int(mins), seconds=int(secs)))

async def prompt_until_valid(
    user: discord.User,
    question: str,
    error_msg: str,
    validator=None,
    timeout=300.0
):
    """Prompt the user until validator passes, or user types 'stop', or timeout."""
    while True:
        await user.send(question)
        try:
            msg = await bot.wait_for(
                'message',
                check=lambda m: m.author == user and isinstance(m.channel, discord.DMChannel),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            await user.send(messages["session_timeout"])
            return None

        content = msg.content.strip()
        if content.lower() == "stop":
            await user.send(messages["stop_message"])
            return None

        if validator and not validator(content):
            await user.send(error_msg)
        else:
            return content

# ------------- Google Sheets Integration -------------
def get_sheet(max_retries=3, retry_delay=2):
    retries = 0
    last_exception = None
    while retries < max_retries:
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
            client = gspread.authorize(creds)
            return client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
        except (ConnectionError, RemoteDisconnected, RequestException, APIError) as e:
            last_exception = e
            retries += 1
            print(f"[ERROR] Connection error (attempt {retries}/{max_retries}): {e}")
            if retries < max_retries:
                time.sleep(retry_delay)
                retry_delay *= 2
    raise last_exception

def add_new_task(
    tasks: str,
    description: str,
    requested_by: str,
    priority: str,
    type_value: str = "Request",
    relevant_link: str = "",
    status: str = "Open"
) -> dict:
    """
    Write data into columns B–I (ignoring column A entirely).
    B: Timestamp
    C: Task
    D: Description
    E: Requested By
    F: Relevant Link
    G: Priority
    H: Type
    I: Status
    """
    try:
        sheet = get_sheet()

        # Double-check we can access the sheet
        max_retries = 3
        retry_delay = 2
        current_rows = None
        for attempt in range(max_retries):
            try:
                current_rows = len(sheet.get_all_values())
                break
            except (ConnectionError, RemoteDisconnected, RequestException, APIError) as e:
                if attempt < max_retries - 1:
                    print(f"[ERROR] Connection error on attempt {attempt+1}/{max_retries}: {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    sheet = get_sheet()  # Re-auth
                else:
                    return {
                        "ok": False,
                        "error": f"Failed to access sheet after {max_retries} attempts: {str(e)}"
                    }

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_index = current_rows + 1

        # 8 columns total (for B–I)
        row_data = [
            timestamp,      # B
            tasks,          # C
            description,    # D
            requested_by,   # E
            relevant_link,  # F
            priority,       # G
            type_value,     # H
            status          # I
        ]

        # Update the exact range, ignoring column A
        # This ensures the data lands in B..I
        for attempt in range(max_retries):
            try:
                sheet.update(f"B{row_index}:I{row_index}", [row_data])
                break
            except (ConnectionError, RemoteDisconnected, RequestException, APIError) as e:
                if attempt < max_retries - 1:
                    print(f"[ERROR] Connection error on attempt {attempt+1}/{max_retries}: {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    sheet = get_sheet()
                else:
                    return {
                        "ok": False,
                        "error": f"Failed to update row after {max_retries} attempts: {str(e)}"
                    }

        # Construct a direct link to that row (focusing on column B)
        task_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
        if WORKSHEET_GID:
            task_url += f"#gid={WORKSHEET_GID}&range=B{row_index}"
        else:
            # If no GID, just use the sheet name in the link
            task_url += f"#{WORKSHEET_NAME}&range=B{row_index}"

        return {
            "ok": True,
            "task_url": task_url,
            "row_index": row_index
        }

    except APIError as api_err:
        error_message = str(api_err)
        if hasattr(api_err, 'response') and api_err.response:
            try:
                error_json = api_err.response.json()
                error_message = error_json.get('error', {}).get('message', str(api_err))
            except:
                error_message = f"API Error: {str(api_err)}"
        return {
            "ok": False,
            "error": error_message
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Unexpected error: {str(e)}"
        }

async def submit_to_google_sheets(
    tasks: str,
    description: str,
    complexity: str,
    assignee: str,
    relevant_link: str = ""
) -> dict:
    try:
        # Check credentials
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            error_msg = f"Credentials file not found at {SERVICE_ACCOUNT_FILE}"
            print(f"[ERROR] {error_msg}")
            return {"ok": False, "error": error_msg}

        # Map user’s “urgency” to a priority
        complexity_map = {
            "urgent": "Urgent",
            "high": "High",
            "medium": "Medium",
            "low": "Low"
        }
        priority = complexity_map.get(complexity.lower(), "Medium")

        # The “type_value” is “Request”
        type_value = "Request"

        # Use the assignee as the “requested_by”
        requested_by = assignee

        # Add new task while ignoring column A
        result = add_new_task(
            tasks=tasks,
            description=description,
            requested_by=requested_by,
            priority=priority,
            type_value=type_value,
            relevant_link=relevant_link,
            status="Open"
        )

        if not result["ok"]:
            print(f"[DEBUG] Failed to add task: {result['error']}")

        return result

    except Exception as e:
        error_msg = f"Failed to submit to Google Sheets: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return {"ok": False, "error": error_msg}

def test_sheets_connection():
    try:
        print("[TEST] Setting up credentials...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]

        print(f"[TEST] Looking for credentials at: {SERVICE_ACCOUNT_FILE}")
        print(f"[TEST] File exists: {os.path.exists(SERVICE_ACCOUNT_FILE)}")

        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            print(f"[TEST] ERROR: Service account file not found at {SERVICE_ACCOUNT_FILE}")
            return False

        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
        print("[TEST] Credentials loaded successfully")

        client = gspread.authorize(creds)
        print("[TEST] Authorization successful")

        if not SPREADSHEET_ID:
            print("[TEST] ERROR: SPREADSHEET_ID not set in environment variables")
            return False

        print(f"[TEST] Attempting to open spreadsheet with ID: {SPREADSHEET_ID}")
        sheet = client.open_by_key(SPREADSHEET_ID)
        print(f"[TEST] Found spreadsheet: {sheet.title}")

        print(f"[TEST] Attempting to access worksheet: {WORKSHEET_NAME}")
        worksheet = sheet.worksheet(WORKSHEET_NAME)
        print(f"[TEST] Accessed worksheet: {worksheet.title}")

        # Just read a single cell for a smoke test
        value = worksheet.acell('A1').value
        print(f"[TEST] Successfully read cell A1: {value}")

        # Show the link that will be used
        print(f"[TEST] Task URL format: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={WORKSHEET_GID}")
        return True

    except Exception as e:
        print(f"[TEST] Error: {str(e)}")
        print(f"[TEST] Error type: {type(e)}")
        return False

# Run the bot
if __name__ == "__main__":
    print("\n=== Testing Google Sheets Connection ===")
    test_sheets_connection()
    print("======================================\n")
    bot.run(DISCORD_TOKEN)
