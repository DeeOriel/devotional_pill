import mysql.connector
from openai import OpenAI
from twilio.rest import Client
from datetime import datetime
import time

# -------------------- CONFIG -------------------- #
OPENAI_API_KEY = "your_openai_key"
TWILIO_SID = "your_sid"
TWILIO_TOKEN = "your_token"
TWILIO_WHATSAPP_NUMBER = "+14155238886"

client = OpenAI(api_key=OPENAI_API_KEY)
twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)

# -------------------- DB -------------------- #
def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="devotional_app"
    )

# -------------------- GET USERS -------------------- #
def get_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number FROM users WHERE phone_number IS NOT NULL")
    users = cursor.fetchall()
    conn.close()
    return [u[0] for u in users]

# -------------------- GET DEVOTIONAL -------------------- #
def get_devotional():
    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input="Give a short Bible devotional with a verse and encouragement."
        )
        return response.output[0].content[0].text
    except:
        return "Trust in the Lord with all your heart. (Proverbs 3:5-6)"

# -------------------- SEND WHATSAPP -------------------- #
def send_whatsapp(to, message):
    return twilio_client.messages.create(
        body=message,
        from_=f'whatsapp:{TWILIO_WHATSAPP_NUMBER}',
        to=f'whatsapp:{to}'
    )

# -------------------- MAIN JOB -------------------- #
def send_daily_devotionals():
    print("Sending devotionals...")
    users = get_users()
    devotional = get_devotional()

    for number in users:
        try:
            send_whatsapp(number, devotional)
            print(f"Sent to {number}")
        except Exception as e:
            print(f"Failed for {number}: {e}")

# -------------------- SCHEDULER LOOP -------------------- #
while True:
    now = datetime.now()

    # ⏰ Set your time here (6:00 AM)
    if now.hour == 6 and now.minute == 0:
        send_daily_devotionals()
        time.sleep(60)  # prevent duplicate sending

    time.sleep(10)