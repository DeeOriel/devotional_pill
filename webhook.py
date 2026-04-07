# app.py
import streamlit as st
import mysql.connector
from openai import OpenAI
from hashlib import sha256
from datetime import datetime, timedelta
import base64
import pandas as pd
from twilio.rest import Client
import requests
import stripe

# -------------------- CONFIG -------------------- #
st.set_page_config(page_title="Advanced Devotional App", page_icon="🙏", layout="wide")

# -------------------- SECRETS -------------------- #
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
TWILIO_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_NUMBER = st.secrets["TWILIO_PHONE_NUMBER"]

STRIPE_SECRET = st.secrets["STRIPE_SECRET_KEY"]
STRIPE_PUB = st.secrets["STRIPE_PUBLISHABLE_KEY"]
STRIPE_PRICE_PREMIUM = st.secrets["STRIPE_PRICE_PREMIUM"]
STRIPE_PRICE_PRO = st.secrets["STRIPE_PRICE_PRO"]
BASE_URL = st.secrets["BASE_URL"]

stripe.api_key = STRIPE_SECRET
client = OpenAI(api_key=OPENAI_API_KEY)
twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

TRIAL_DAYS = 7  # Free trial period

# -------------------- DATABASE -------------------- #
def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="devotional_app"
    )

# -------------------- AUTH -------------------- #
def hash_password(password):
    return sha256(password.encode()).hexdigest()

def authenticate(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, role, is_subscribed, stripe_customer_id, subscription_id, plan, trial_end "
        "FROM users WHERE username=%s AND password=%s",
        (username, hash_password(password))
    )
    user = cursor.fetchone()
    conn.close()
    if user:
        user_dict = {
            "user_id": user[0],
            "username": user[1],
            "role": user[2],
            "is_subscribed": user[3],
            "stripe_customer_id": user[4],
            "subscription_id": user[5],
            "plan": user[6],
            "trial_end": user[7]
        }
        # Auto-expire trial if needed
        if user_dict["plan"] == "trial" and user_dict["trial_end"]:
            if user_dict["trial_end"] < datetime.now():
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET plan='free', trial_start=NULL, trial_end=NULL WHERE id=%s",
                    (user_dict["user_id"],)
                )
                conn.commit(); conn.close()
                user_dict["plan"] = "free"
        return user_dict
    return None

def register_user(username, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, role, plan) VALUES (%s, %s, %s, %s)",
            (username, hash_password(password), "user", "free")
        )
        conn.commit()
        conn.close()
        return True
    except:
        return False

# -------------------- TRIAL -------------------- #
def start_trial(user_id):
    start = datetime.now()
    end = start + timedelta(days=TRIAL_DAYS)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET plan='trial', trial_start=%s, trial_end=%s WHERE id=%s",
        (start, end, user_id)
    )
    conn.commit(); conn.close()
    return end

def is_trial_active(user):
    return user.get("plan") == "trial" and user.get("trial_end") and user["trial_end"] > datetime.now()

# -------------------- STRIPE -------------------- #
def create_checkout_session(user_id, price_id):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{BASE_URL}?success=true",
        cancel_url=f"{BASE_URL}?canceled=true",
        metadata={"user_id": user_id}
    )
    return session.url

def get_subscription(subscription_id):
    return stripe.Subscription.retrieve(subscription_id)

def cancel_subscription(subscription_id):
    return stripe.Subscription.delete(subscription_id)

def get_invoices(customer_id):
    return stripe.Invoice.list(customer=customer_id, limit=10)

# -------------------- SESSION STATE -------------------- #
for key, default in {
    "logged_in": False,
    "username": "",
    "role": "user",
    "last_devotional": "",
    "user_id": None,
    "refresh_news": True,
    "is_subscribed": False,
    "stripe_customer_id": None,
    "subscription_id": None,
    "plan": "free",
    "trial_end": None
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# -------------------- SEND WHATSAPP -------------------- #
def send_whatsapp(to_number, message):
    return twilio_client.messages.create(
        body=message,
        from_=f'whatsapp:{TWILIO_NUMBER}',
        to=f'whatsapp:{to_number}'
    ).sid

# -------------------- SIDEBAR -------------------- #
st.sidebar.title("🔐 Account")
if not st.session_state["logged_in"]:
    menu = st.sidebar.radio("Choose", ["Login", "Register"])
    username_input = st.sidebar.text_input("Username")
    password_input = st.sidebar.text_input("Password", type="password")

    if menu == "Login" and st.sidebar.button("Login"):
        user = authenticate(username_input, password_input)
        if user:
            st.session_state.update(user)
            st.session_state["logged_in"] = True
            st.success(f"Welcome {user['username']} 👋")
        else:
            st.error("Invalid credentials")
    elif menu == "Register" and st.sidebar.button("Register"):
        if register_user(username_input, password_input):
            st.success("Account created! Login now.")
        else:
            st.error("Username already exists")
else:
    st.sidebar.write(f"👋 {st.session_state['username']} ({st.session_state['role']})")
    if st.sidebar.button("Logout"):
        for key in st.session_state.keys():
            st.session_state[key] = False if key=="logged_in" else "" if isinstance(st.session_state[key], str) else None
        st.success("Logged out")

# -------------------- MAIN TABS -------------------- #
if st.session_state["logged_in"]:
    tabs = ["Home", "Profile", "Devotionals", "Chat", "Billing"]
    if st.session_state["role"] == "admin":
        tabs.append("Admin Dashboard")
    tab_objs = st.tabs(tabs)

    # -------------------- HOME -------------------- #
    with tab_objs[0]:
        st.header("📰 Live News Feed")
        st.info("Latest news from Admin and NewsAPI.")
        if st.button("🔄 Refresh News"):
            st.session_state['refresh_news'] = True

        if st.session_state['refresh_news']:
            conn = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM admin_news ORDER BY created_at DESC LIMIT 10")
            admin_news = cursor.fetchall()
            conn.close()

            if admin_news:
                st.subheader("📢 Admin News")
                for news in admin_news:
                    st.markdown(f"**{news['title']}**")
                    st.write(news['content'])
                    st.write(f"*Posted on: {news['created_at']}*")
                    st.markdown("---")
            else:
                st.info("No admin news yet.")

            # NewsAPI
            NEWS_API_KEY = st.secrets.get("NEWS_API_KEY")
            try:
                response = requests.get(f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWS_API_KEY}")
                data = response.json()
                if data['status'] == 'ok' and data['totalResults'] > 0:
                    st.subheader("🌎 Global News")
                    for article in data['articles'][:10]:
                        title = article.get('title', 'No Title')
                        desc = article.get('description', '')
                        url = article.get('url', '#')
                        img_url = article.get('urlToImage', '')
                        st.markdown(f"**{title}**\n{desc}\n[Read more]({url})")
                        if img_url: st.image(img_url, use_column_width=True)
            except:
                st.error("Failed to fetch global news")
            st.session_state['refresh_news'] = False

    # -------------------- PROFILE -------------------- #
    with tab_objs[1]:
        st.header("👤 My Profile")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_number, profile_pic FROM users WHERE username=%s", (st.session_state["username"],))
        user_data = cursor.fetchone()
        conn.close()
        phone = user_data[0] if user_data else ""
        pic_b64 = user_data[1] if user_data else None

        new_phone = st.text_input("WhatsApp Number", value=phone)
        if st.button("Update Profile"):
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET phone_number=%s WHERE username=%s", (new_phone, st.session_state["username"]))
            conn.commit(); conn.close()
            st.success("Profile updated ✅")

        st.subheader("Profile Picture")
        uploaded_pic = st.file_uploader("Upload Picture", type=["png", "jpg", "jpeg"])
        if uploaded_pic:
            pic_b64_new = base64.b64encode(uploaded_pic.read()).decode()
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_pic=%s WHERE username=%s", (pic_b64_new, st.session_state["username"]))
            conn.commit(); conn.close()
            st.success("Profile picture updated ✅")
        if pic_b64:
            st.image(base64.b64decode(pic_b64), width=150)

    # -------------------- DEVOTIONALS -------------------- #
    with tab_objs[2]:
        st.header("📖 Devotionals")
        plan = st.session_state.get("plan")
        trial_active = is_trial_active(st.session_state)
        access_granted = plan in ["premium", "pro"] or trial_active

        if not access_granted:
            st.warning("Upgrade to Premium or start a Free Trial to access AI devotionals")
            if plan == "free":
                if st.button("Start Free 7-Day Trial"):
                    trial_end = start_trial(st.session_state["user_id"])
                    st.session_state["plan"] = "trial"
                    st.session_state["trial_end"] = trial_end
                    st.success(f"Trial started! Expires on {trial_end.strftime('%Y-%m-%d %H:%M')}")

        if access_granted:
            if st.button("Get AI Devotional"):
                try:
                    resp = client.responses.create(
                        model="gpt-4.1-mini",
                        input="Short Bible devotional with verse & encouragement"
                    )
                    st.session_state["last_devotional"] = resp.output[0].content[0].text
                    st.success(st.session_state["last_devotional"])
                except:
                    st.session_state["last_devotional"] = "Trust in the Lord with all your heart. (Proverbs 3:5-6)"
                    st.error("Failed to generate AI devotional, fallback used.")

            if st.session_state.get("last_devotional"):
                st.info(st.session_state["last_devotional"])

    # -------------------- CHAT -------------------- #
    with tab_objs[3]:
        st.header("💬 Devotional Assistant Chat")
        user_input = st.text_area("Ask something:")
        if st.button("Get Response"):
            plan = st.session_state.get("plan")
            trial_active = is_trial_active(st.session_state)
            access_granted = plan in ["premium", "pro"] or trial_active
            if not access_granted:
                st.warning("Premium/Trial access required for unlimited chat")
            elif user_input.strip():
                try:
                    resp = client.responses.create(
                        model="gpt-4.1-mini",
                        input=f"Devotional assistant:\nUser: {user_input}"
                    )
                    st.markdown(f"**Response:** {resp.output[0].content[0].text}")
                except:
                    st.error("Failed to get response")
            else:
                st.warning("Enter a message")

    # -------------------- BILLING -------------------- #
    with tab_objs[4]:
        st.header("💳 Billing Dashboard")
        plan = st.session_state.get("plan")
        sub_id = st.session_state.get("subscription_id")
        cust_id = st.session_state.get("stripe_customer_id")

        st.subheader("📦 Current Plan")
        if plan in ["free", "trial"]:
            st.info(f"Current Plan: {plan.upper()}")
            if plan == "free":
                if st.button("Start Free 7-Day Trial"):
                    trial_end = start_trial(st.session_state["user_id"])
                    st.session_state["plan"] = "trial"
                    st.session_state["trial_end"] = trial_end
                    st.success(f"Trial started! Expires on {trial_end.strftime('%Y-%m-%d %H:%M')}")
            if st.button("Upgrade to Premium"):
                url = create_checkout_session(st.session_state["user_id"], STRIPE_PRICE_PREMIUM)
                st.markdown(f"[👉 Subscribe Now]({url})")
        else:
            st.success(f"Active Plan: {plan.upper()}")
            sub = get_subscription(sub_id)
            st.write(f"Status: {sub.status}")
            st.write(f"Next billing: {datetime.fromtimestamp(sub.current_period_end)}")

            if st.button("Cancel Subscription"):
                cancel_subscription(sub_id)
                st.warning("Subscription canceled at period end")

        st.subheader("🧾 Billing History")
        if cust_id:
            invoices = get_invoices(cust_id)
            for inv in invoices.data:
                st.markdown(f"""
                **Amount:** ${inv.amount_paid / 100}  
                **Status:** {inv.status}  
                [Download Invoice]({inv.hosted_invoice_url})
                """)
                st.markdown("---")

# -------------------- ADMIN DASHBOARD -------------------- #
    if st.session_state["role"] == "admin":
        st.subheader("🛠️ Admin Dashboard")
        st.info("Admin features like user management and news feed are available here.")
        # You can keep your admin logic here as before

else:
    st.title("🙏 Welcome to Devotional App")
    st.info("Please login or register to continue.")