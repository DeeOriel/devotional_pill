from fastapi import FastAPI, Request
from datetime import datetime, timedelta
import mysql.connector

app = FastAPI()

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="devotional_app"
    )

# ---------------- ORANGE PAYMENT ---------------- #
@app.post("/pay/orange")
def pay_orange(data: dict):
    # ⚠️ Replace with real Orange API later
    return {
        "payment_url": f"http://localhost:8501?ref=ORANGE_{data['user_id']}_{int(datetime.now().timestamp())}"
    }

# ---------------- WEBHOOK ---------------- #
@app.post("/webhook/orange")
async def orange_webhook(request: Request):
    body = await request.json()

    reference = body.get("reference")
    user_id = body.get("user_id")

    conn = get_connection()
    cursor = conn.cursor()

    expires_at = datetime.now() + timedelta(days=30)

    cursor.execute("""
        INSERT INTO payments (user_id, amount, method, status, reference, created_at, expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (user_id, body.get("amount"), "Orange", "success", reference, datetime.now(), expires_at))

    conn.commit()
    conn.close()

    return {"status": "ok"}