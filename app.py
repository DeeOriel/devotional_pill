# app.py
import streamlit as st
import mysql.connector
from openai import OpenAI
from hashlib import sha256
from datetime import datetime
import base64
import pandas as pd
from twilio.rest import Client
import requests

# -------------------- CONFIG -------------------- #
st.set_page_config(page_title="Advanced Devotional App", page_icon="🙏", layout="wide")

# -------------------- OPENAI & TWILIO SETUP -------------------- #
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
twilio_client = Client(st.secrets["TWILIO_ACCOUNT_SID"], st.secrets["TWILIO_AUTH_TOKEN"])
twilio_whatsapp_number = st.secrets["TWILIO_PHONE_NUMBER"]

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
        "SELECT id, username, role FROM users WHERE username=%s AND password=%s",
        (username, hash_password(password))
    )
    user = cursor.fetchone()
    conn.close()
    if user:
        return {"user_id": user[0], "username": user[1], "role": user[2]}
    return None

def register_user(username, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, hash_password(password), "user")
        )
        conn.commit()
        conn.close()
        return True
    except:
        return False

# -------------------- SESSION STATE -------------------- #
for key, default in {
    "logged_in": False,
    "username": "",
    "role": "user",
    "last_devotional": "",
    "user_id": None,
    "refresh_news": True
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# -------------------- SEND WHATSAPP -------------------- #
def send_whatsapp(to_number, message):
    msg = twilio_client.messages.create(
        body=message,
        from_=f'whatsapp:{twilio_whatsapp_number}',
        to=f'whatsapp:{to_number}'
    )
    return msg.sid

# -------------------- SIDEBAR -------------------- #
st.sidebar.title("🔐 Account")

if not st.session_state["logged_in"]:
    menu = st.sidebar.radio("Choose", ["Login", "Register"])
    username_input = st.sidebar.text_input("Username")
    password_input = st.sidebar.text_input("Password", type="password")

    if menu == "Login" and st.sidebar.button("Login"):
        user = authenticate(username_input, password_input)
        if user:
            st.session_state.update({
                "logged_in": True,
                "username": user["username"],
                "role": user["role"],
                "user_id": user["user_id"]
            })
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
        for key in ["logged_in", "username", "role", "user_id", "last_devotional", "refresh_news"]:
            st.session_state[key] = False if key=="logged_in" else "" if key in ["username","role"] else None
        st.success("Logged out")

# -------------------- MAIN TABS -------------------- #
if st.session_state["logged_in"]:
    tabs = ["Home", "Profile", "Devotionals", "Chat"]
    if st.session_state["role"] == "admin":
        tabs.append("Admin Dashboard")
    tab_objs = st.tabs(tabs)

    # -------------------- HOME (News Feed + Admin News) -------------------- #
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

            # --- NewsAPI ---
            NEWS_API_KEY = st.secrets.get("NEWS_API_KEY")
            NEWS_URL = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWS_API_KEY}"
            try:
                response = requests.get(NEWS_URL)
                data = response.json()
                if data['status'] == 'ok' and data['totalResults'] > 0:
                    st.subheader("🌎 Global News")
                    for article in data['articles'][:10]:
                        title = article.get('title', 'No Title')
                        desc = article.get('description', '')
                        source = article['source']['name']
                        url = article.get('url', '#')
                        img_url = article.get('urlToImage')

                        card_html = f"""
                        <div style='
                            background-color: #f8f9fa;
                            border-radius: 10px;
                            padding: 20px;
                            margin-bottom: 20px;
                            box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
                        '>
                            <h3 style='margin-bottom:5px'>{title}</h3>
                            <p style='color:#555'>{desc}</p>
                            <p style='font-size:0.85em;color:#888'>Source: {source}</p>
                            {'<img src="'+img_url+'" width="100%" style="border-radius:5px;margin-top:10px">' if img_url else '' }
                            <a href="{url}" target="_blank">Read more...</a>
                        </div>
                        """
                        st.markdown(card_html, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error fetching news: {e}")

            st.session_state['refresh_news'] = False

    # -------------------- PROFILE -------------------- #
    with tab_objs[1]:
        st.header("👤 My Profile")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_number, profile_pic FROM users WHERE username=%s", (st.session_state["username"],))
        user_data = cursor.fetchone()
        conn.close()
        phone = user_data[0] if user_data[0] else ""
        pic_b64 = user_data[1]

        new_phone = st.text_input("WhatsApp Number", value=phone)
        if st.button("Update Profile"):
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET phone_number=%s WHERE username=%s",
                           (new_phone, st.session_state["username"]))
            conn.commit()
            conn.close()
            st.success("Profile updated ✅")

        st.subheader("Profile Picture")
        uploaded_pic = st.file_uploader("Upload Picture", type=["png", "jpg", "jpeg"])
        if uploaded_pic:
            pic_b64_new = base64.b64encode(uploaded_pic.read()).decode()
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_pic=%s WHERE username=%s",
                           (pic_b64_new, st.session_state["username"]))
            conn.commit()
            conn.close()
            st.success("Profile picture updated ✅")
        if pic_b64:
            st.image(base64.b64decode(pic_b64), width=150)

    # -------------------- DEVOTIONALS -------------------- #
    with tab_objs[2]:
        st.header("📖 Devotionals")
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

        st.subheader("✍️ Add Manual Devotional")
        title = st.text_input("Title")
        verse = st.text_input("Verse")
        content = st.text_area("Content")
        user_id = st.session_state.get("user_id")
        if st.button("Add Devotional"):
            if title and verse and content:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO devotionals (title, verse, content, created_at, created_by, user_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    (title, verse, content, datetime.now(), st.session_state["username"], user_id)
                )
                conn.commit()
                conn.close()
                st.success("Manual devotional added ✅")
            else:
                st.warning("Fill all fields")

        if st.checkbox("📜 Show Manual Devotionals"):
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title, verse, content, created_at, created_by FROM devotionals ORDER BY created_at DESC LIMIT 20")
            rows = cursor.fetchall()
            conn.close()
            if rows:
                df = pd.DataFrame(rows, columns=["Title", "Verse", "Content", "Created At", "Created By"])
                st.dataframe(df)
            else:
                st.info("No manual devotionals found.")

    # -------------------- CHAT -------------------- #
    with tab_objs[3]:
        st.header("💬 Devotional Assistant Chat")
        user_input = st.text_area("Ask something:")
        if st.button("Get Response"):
            if user_input.strip():
                try:
                    resp = client.responses.create(
                        model="gpt-4.1-mini",
                        input=f"Devotional assistant:\nUser: {user_input}"
                    )
                    answer = resp.output[0].content[0].text
                    st.markdown(f"**Response:** {answer}")
                except:
                    st.error("Failed to get response")
            else:
                st.warning("Enter a message")

    # -------------------- ADMIN DASHBOARD -------------------- #
    if st.session_state["role"] == "admin":
        with tab_objs[-1]:
            st.header("🛠️ Admin Dashboard")

            # --- Stats ---
            conn = get_connection(); cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users"); total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM devotionals"); total_devos = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM messages"); total_messages = cursor.fetchone()[0]
            conn.close()

            cols = st.columns(3)
            colors = ["#4A90E2", "#7ED321", "#F5A623"]
            icons = ["👥", "📖", "💬"]
            labels = ["Total Users", "Total Devotionals", "Total Messages"]
            values = [total_users, total_devos, total_messages]

            for col, color, icon, label, value in zip(cols, colors, icons, labels, values):
                col.markdown(f"""
                    <div style='background-color:{color};padding:20px;border-radius:10px;text-align:center;color:white'>
                        <h3>{icon} {label}</h3>
                        <h2>{value}</h2>
                    </div>
                """, unsafe_allow_html=True)

            # --- Broadcast ---
            st.subheader("📢 Broadcast Message")
            broadcast_msg = st.text_area("Message", key="broadcast_message")
            if st.button("Send Broadcast"):
                if broadcast_msg.strip():
                    conn = get_connection(); cursor = conn.cursor()
                    cursor.execute("SELECT username, phone_number FROM users WHERE phone_number IS NOT NULL")
                    all_users = cursor.fetchall(); conn.close()
                    success, failed = 0, 0
                    for uname, phone in all_users:
                        try: send_whatsapp(phone, broadcast_msg); success += 1
                        except: failed += 1
                    st.success(f"✅ Broadcast sent to {success} users")
                    if failed>0: st.warning(f"⚠️ Failed for {failed} users")
                else:
                    st.warning("Enter a message")

            # --- Users Management ---
            st.subheader("👥 Users List with Search & Filter")
            search_query = st.text_input("🔍 Search by username or phone number")
            role_filter = st.selectbox("Filter by role", ["All", "user", "admin"])

            conn = get_connection(); cursor = conn.cursor()
            cursor.execute("SELECT username, phone_number, role, profile_pic FROM users")
            users = cursor.fetchall(); conn.close()

            filtered_users = []
            for uname, phone, role, pic in users:
                if (search_query.lower() in uname.lower() or (phone and search_query in phone)) and (role_filter=="All" or role==role_filter):
                    filtered_users.append((uname, phone, role, pic))

            for uname, phone, role, pic in filtered_users:
                cols = st.columns([1, 2, 2, 3])
                if pic: cols[0].image(base64.b64decode(pic), width=50)
                else: cols[0].write("No Pic")
                cols[1].write(uname)
                cols[2].write(f"{role} | {phone if phone else 'No Number'}")
                
                with cols[3]:
                    del_btn = st.button("🗑️ Delete", key=f"del_{uname}")
                    reset_btn = st.button("🔑 Reset Password", key=f"reset_{uname}")
                    role_btn = st.button("⚙️ Change Role", key=f"role_{uname}")

                    if del_btn and st.confirm(f"Are you sure you want to delete `{uname}`?"):
                        conn = get_connection(); cursor = conn.cursor()
                        cursor.execute("DELETE FROM users WHERE username=%s", (uname,))
                        conn.commit(); conn.close()
                        st.success(f"User `{uname}` deleted ✅")
                    
                    if reset_btn and st.confirm(f"Reset password for `{uname}` to default `123456`?"):
                        conn = get_connection(); cursor = conn.cursor()
                        cursor.execute("UPDATE users SET password=%s WHERE username=%s",
                                       (hash_password("123456"), uname))
                        conn.commit(); conn.close()
                        st.success(f"Password for `{uname}` reset ✅")
                    
                    if role_btn:
                        new_role = st.selectbox("Select new role", ["user", "admin"], key=f"role_sel_{uname}")
                        if st.button("Update Role", key=f"update_role_{uname}"):
                            conn = get_connection(); cursor = conn.cursor()
                            cursor.execute("UPDATE users SET role=%s WHERE username=%s", (new_role, uname))
                            conn.commit(); conn.close()
                            st.success(f"Role for `{uname}` updated to `{new_role}` ✅")

            # --- Admin News Management ---
            st.subheader("📰 Manage News Feed")
            news_action = st.selectbox("Action", ["View News", "Add News", "Edit News", "Delete News"])

            conn = get_connection(); cursor = conn.cursor(dictionary=True)

            # View News
            if news_action == "View News":
                cursor.execute("SELECT * FROM admin_news ORDER BY created_at DESC")
                news_list = cursor.fetchall()
                for n in news_list:
                    st.markdown(f"**{n['title']}** - {n['created_at']}")
                    st.write(n['content'])
                    st.markdown("---")

            # Add News
            elif news_action == "Add News":
                new_title = st.text_input("Title", key="add_news_title")
                new_content = st.text_area("Content", key="add_news_content")
                if st.button("Add News Item"):
                    if new_title and new_content:
                        cursor.execute("INSERT INTO admin_news (title, content) VALUES (%s, %s)",
                                       (new_title, new_content))
                        conn.commit()
                        st.success("News added ✅")
                    else:
                        st.warning("Fill all fields")

            # Edit News
            elif news_action == "Edit News":
                cursor.execute("SELECT id, title FROM admin_news ORDER BY created_at DESC")
                news_list = cursor.fetchall()
                selected = st.selectbox("Select news to edit", [f"{n['id']}: {n['title']}" for n in news_list])
                news_id = int(selected.split(":")[0])
                cursor.execute("SELECT * FROM admin_news WHERE id=%s", (news_id,))
                news_item = cursor.fetchone()

                edited_title = st.text_input("Title", news_item['title'], key="edit_news_title")
                edited_content = st.text_area("Content", news_item['content'], key="edit_news_content")
                if st.button("Update News Item"):
                    cursor.execute("UPDATE admin_news SET title=%s, content=%s WHERE id=%s",
                                   (edited_title, edited_content, news_id))
                    conn.commit()
                    st.success("News updated ✅")

            # Delete News
            elif news_action == "Delete News":
                cursor.execute("SELECT id, title FROM admin_news ORDER BY created_at DESC")
                news_list = cursor.fetchall()
                selected = st.selectbox("Select news to delete", [f"{n['id']}: {n['title']}" for n in news_list])
                news_id = int(selected.split(":")[0])
                if st.button("Delete News Item"):
                    cursor.execute("DELETE FROM admin_news WHERE id=%s", (news_id,))
                    conn.commit()
                    st.success("News deleted ✅")

            conn.close()

else:
    st.title("🙏 Welcome to Devotional App")
    st.info("Please login or register to continue.")