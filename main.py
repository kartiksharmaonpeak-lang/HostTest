
import os
import time
import json
import sqlite3
import string
import secrets
import requests

# ==================================================
# CONFIGURATION
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {8833850065}

CHANNELS = [
    "@auraxkartik",
    "@botsbydevloper"
]

SUPPORT_BOT = "@Kartiksupportbot"
UPI_ID = "abcd1234@fam"

REFERRAL_REWARD = 50

PACKAGES = {
    "p10": (10, 150),
    "p20": (20, 250),
    "p30": (30, 350)
}

API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# ==================================================
# DATABASE
# ==================================================

DB_PATH = os.path.join(
    os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "."),
    "kitkatfiles.db"
)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
cur = db.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    referrer INTEGER,
    verified INTEGER DEFAULT 0,
    referral_paid INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price INTEGER,
    description TEXT,
    file_id TEXT
);

CREATE TABLE IF NOT EXISTS purchases (
    user_id INTEGER,
    file_id INTEGER,
    UNIQUE(user_id, file_id)
);

CREATE TABLE IF NOT EXISTS gift_codes (
    code TEXT PRIMARY KEY,
    amount INTEGER,
    uses_left INTEGER
);

CREATE TABLE IF NOT EXISTS redeemed_codes (
    user_id INTEGER,
    code TEXT,
    UNIQUE(user_id, code)
);
""")

db.commit()

states = {}
offset = 0


# ==================================================
# TELEGRAM API
# ==================================================

def api(method, data=None):
    try:
        response = requests.post(
            API + method,
            data=data,
            timeout=60
        )
        return response.json()

    except Exception as error:
        print("API ERROR:", error)
        return {}


def send(chat_id, message, markup=None):
    data = {
        "chat_id": chat_id,
        "text": message
    }

    if markup:
        data["reply_markup"] = json.dumps(markup)

    return api("sendMessage", data)


def answer_callback(callback_id, message=""):
    return api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": message
    })


# ==================================================
# USER DATABASE FUNCTIONS
# ==================================================

def get_user(user_id):
    return cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def ensure_user(user_id, referrer=None):

    existing = get_user(user_id)

    if existing:
        return

    if referrer == user_id:
        referrer = None

    cur.execute("""
        INSERT INTO users(user_id, balance, referrer)
        VALUES (?, 0, ?)
    """, (user_id, referrer))

    db.commit()


def is_admin(user_id):
    return user_id in ADMIN_IDS


# ==================================================
# KEYBOARDS
# ==================================================

def join_keyboard():

    buttons = []

    for channel in CHANNELS:
        buttons.append([{
            "text": "Join " + channel,
            "url": "https://t.me/" + channel.replace("@", "")
        }])

    buttons.append([{
        "text": "Verify Membership",
        "callback_data": "verify"
    }])

    return {
        "inline_keyboard": buttons
    }


def main_keyboard():

    return {
        "keyboard": [
            ["Buy Files", "My Files"],
            ["Balance", "Support"]
        ],
        "resize_keyboard": True
    }


def welcome_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "Refer and earn",
                    "callback_data": "refer"
                },
                {
                    "text": "Buy Credit",
                    "callback_data": "credits"
                }
            ]
        ]
    }


def admin_keyboard():

    return {
        "inline_keyboard": [
            [{
                "text": "Upload File",
                "callback_data": "admin_upload"
            }],
            [{
                "text": "Add Coins",
                "callback_data": "admin_addcoins"
            }],
            [{
                "text": "Create Gift Code",
                "callback_data": "admin_gift"
            }]
        ]
    }


# ==================================================
# FORCE JOIN SYSTEM
# ==================================================

def check_membership(user_id):

    for channel in CHANNELS:

        result = api("getChatMember", {
            "chat_id": channel,
            "user_id": user_id
        })

        if not result.get("ok"):
            print("Membership check failed:", channel)
            return False

        status = result["result"]["status"]

        if status not in (
            "member",
            "administrator",
            "creator"
        ):
            return False

    return True


def verify_user(user_id, chat_id):

    if not check_membership(user_id):

        send(
            chat_id,
            "Please join both required channels first.\n"
            "After joining, press Verify Membership.",
            join_keyboard()
        )

        return

    ensure_user(user_id)

    cur.execute(
        "UPDATE users SET verified=1 WHERE user_id=?",
        (user_id,)
    )

    user = get_user(user_id)

    # Referral reward is paid once.
    if user["referrer"] and not user["referral_paid"]:

        cur.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (
            REFERRAL_REWARD,
            user["referrer"]
        ))

        cur.execute("""
            UPDATE users
            SET referral_paid=1
            WHERE user_id=?
        """, (user_id,))

    db.commit()

    send(
        chat_id,
        "🔥WELCOME TO KitKatFiles🔥",
        welcome_keyboard()
    )

    send(
        chat_id,
        "Please choose an option from the keyboard below.",
        main_keyboard()
    )


# ==================================================
# REFERRAL SYSTEM
# ==================================================

def referral_link(user_id):

    result = api("getMe")

    if not result.get("ok"):
        return None

    username = result["result"]["username"]

    return f"https://t.me/{username}?start={user_id}"


# ==================================================
# FILE STORE
# ==================================================

def show_files(chat_id):

    items = cur.execute(
        "SELECT * FROM files ORDER BY id DESC"
    ).fetchall()

    if not items:
        send(chat_id, "No files are available right now.")
        return

    for item in items:

        message = (
            f"File: {item['name']}\n"
            f"Description: {item['description']}\n"
            f"Price: {item['price']} credits"
        )

        markup = {
            "inline_keyboard": [[{
                "text": "Buy File",
                "callback_data": f"buyfile_{item['id']}"
            }]]
        }

        send(chat_id, message, markup)


def buy_file(user_id, chat_id, file_id):

    item = cur.execute(
        "SELECT * FROM files WHERE id=?",
        (file_id,)
    ).fetchone()

    if not item:
        send(chat_id, "File not found.")
        return

    purchased = cur.execute("""
        SELECT 1 FROM purchases
        WHERE user_id=? AND file_id=?
    """, (user_id, file_id)).fetchone()

    if purchased:
        send(chat_id, "You have already purchased this file.")
        return

    user = get_user(user_id)

    if not user or user["balance"] < item["price"]:
        send(
            chat_id,
            f"Insufficient balance.\n"
            f"Required: {item['price']} credits."
        )
        return

    try:
        # Deduct credits and record purchase atomically.
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""
            UPDATE users
            SET balance=balance-?
            WHERE user_id=? AND balance>=?
        """, (item["price"], user_id, item["price"]))

        if cur.rowcount != 1:
            db.rollback()
            send(chat_id, "Insufficient balance.")
            return

        cur.execute("""
            INSERT INTO purchases(user_id, file_id)
            VALUES (?, ?)
        """, (user_id, file_id))

        db.commit()

    except sqlite3.IntegrityError:
        db.rollback()
        send(chat_id, "You have already purchased this file.")
        return

    except Exception as error:
        db.rollback()
        print("PURCHASE ERROR:", error)
        send(chat_id, "Purchase failed. Please try again.")
        return

    result = api("sendDocument", {
        "chat_id": chat_id,
        "document": item["file_id"],
        "caption": f"Your purchase: {item['name']}"
    })

    if not result.get("ok"):
        send(
            chat_id,
            "Your payment was recorded, but file delivery failed. "
            "Please contact support."
        )
        return

    send(chat_id, "Purchase successful!")


def my_files(user_id, chat_id):

    items = cur.execute("""
        SELECT files.*
        FROM files
        INNER JOIN purchases
        ON files.id=purchases.file_id
        WHERE purchases.user_id=?
    """, (user_id,)).fetchall()

    if not items:
        send(chat_id, "You have not purchased any files yet.")
        return

    for item in items:

        api("sendDocument", {
            "chat_id": chat_id,
            "document": item["file_id"],
            "caption": item["name"]
        })


# ==================================================
# BUY CREDITS
# ==================================================

def show_packages(chat_id):

    markup = {
        "inline_keyboard": [
            [{
                "text": "₹10 - 150 credits",
                "callback_data": "p10"
            }],
            [{
                "text": "₹20 - 250 credits",
                "callback_data": "p20"
            }],
            [{
                "text": "₹30 - 350 credits",
                "callback_data": "p30"
            }]
        ]
    }

    send(chat_id, "Please Choose A Package", markup)


def package_selected(chat_id, package):

    price, credits = PACKAGES[package]

    message = (
        f"You selected ₹{price} - {credits} credits.\n\n"
        f"Please pay using this UPI ID:\n"
        f"{UPI_ID}\n\n"
        f"After payment, contact support:\n"
        f"{SUPPORT_BOT}\n\n"
        "Your payment must be verified before credits are added. "
        "Please allow up to 24 hours for verification.\n\n"
        "Never share your UPI PIN, OTP, or banking password."
    )

    send(chat_id, message)


# ==================================================
# ADMIN PANEL
# ==================================================

def open_admin(chat_id):

    send(
        chat_id,
        "This is your admin panel:",
        admin_keyboard()
    )


def create_gift_code():

    alphabet = string.ascii_uppercase + string.digits

    return "KITKAT-" + "".join(
        secrets.choice(alphabet)
        for _ in range(10)
    )


def process_admin_text(user_id, chat_id, message):

    state = states.get(user_id)

    if state == "addcoins":

        try:
            parts = message.split()

            if len(parts) != 2:
                raise ValueError

            target_id = int(parts[0])
            amount = int(parts[1])

            if amount <= 0:
                raise ValueError

            ensure_user(target_id)

            cur.execute("""
                UPDATE users
                SET balance=balance+?
                WHERE user_id=?
            """, (amount, target_id))

            db.commit()

            send(chat_id, f"Successfully added {amount} credits.")

            send(
                target_id,
                f"{amount} credits have been added to your balance."
            )

        except Exception:
            send(chat_id, "Invalid format. Send: USER_ID AMOUNT")

        states.pop(user_id, None)
        return True

    if state == "gift":

        try:
            parts = message.split()

            if len(parts) != 2:
                raise ValueError

            amount = int(parts[0])
            uses = int(parts[1])

            if amount <= 0 or uses <= 0:
                raise ValueError

            code = create_gift_code()

            cur.execute("""
                INSERT INTO gift_codes(code, amount, uses_left)
                VALUES (?, ?, ?)
            """, (code, amount, uses))

            db.commit()

            send(
                chat_id,
                f"Gift code created!\n\n"
                f"Code: {code}\n"
                f"Credits: {amount}\n"
                f"Uses: {uses}\n\n"
                f"Users redeem it with:\n"
                f"/redeem {code}"
            )

        except Exception:
            send(chat_id, "Invalid format. Send: AMOUNT USES")

        states.pop(user_id, None)
        return True

    if state == "upload_meta":

        parts = message.split("|", 2)

        if len(parts) != 3:
            send(
                chat_id,
                "Send details in this format:\n"
                "File Name | Price | Description"
            )
            return True

        try:
            name = parts[0].strip()
            price = int(parts[1].strip())
            description = parts[2].strip()

            if not name or price < 0:
                raise ValueError

            states[user_id] = {
                "step": "upload_document",
                "name": name,
                "price": price,
                "description": description
            }

            send(chat_id, "Now send your file as a Telegram document.")

        except Exception:
            send(chat_id, "Invalid file details.")

        return True

    return False


# ==================================================
# GIFT CODE REDEMPTION
# ==================================================

def redeem_code(user_id, chat_id, code):

    code = code.upper().strip()

    try:
        cur.execute("BEGIN IMMEDIATE")

        gift = cur.execute("""
            SELECT * FROM gift_codes
            WHERE code=? AND uses_left>0
        """, (code,)).fetchone()

        if not gift:
            db.rollback()
            send(chat_id, "Invalid or expired gift code.")
            return

        cur.execute("""
            INSERT INTO redeemed_codes(user_id, code)
            VALUES (?, ?)
        """, (user_id, code))

        cur.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (gift["amount"], user_id))

        cur.execute("""
            UPDATE gift_codes
            SET uses_left=uses_left-1
            WHERE code=? AND uses_left>0
        """, (code,))

        if cur.rowcount != 1:
            db.rollback()
            send(chat_id, "This gift code has expired.")
            return

        db.commit()

        send(
            chat_id,
            f"Gift code redeemed successfully!\n"
            f"{gift['amount']} credits added."
        )

    except sqlite3.IntegrityError:
        db.rollback()
        send(chat_id, "You have already redeemed this code.")

    except Exception as error:
        db.rollback()
        print("GIFT ERROR:", error)
        send(chat_id, "Could not redeem this gift code.")


# ==================================================
# MESSAGE HANDLER
# ==================================================

def handle_message(message):

    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    # Admin actions.
    if is_admin(user_id):

        if text == "/admin":
            states.pop(user_id, None)
            open_admin(chat_id)
            return

        if text == "/cancel":
            states.pop(user_id, None)
            send(chat_id, "Current admin action cancelled.")
            return

        state = states.get(user_id)

        if state in ("addcoins", "gift", "upload_meta"):
            if process_admin_text(user_id, chat_id, text):
                return

        if isinstance(state, dict) and state.get("step") == "upload_document":

            document = message.get("document")

            if not document:
                send(chat_id, "Please send the file as a document.")
                return

            cur.execute("""
                INSERT INTO files(name, price, description, file_id)
                VALUES (?, ?, ?, ?)
            """, (
                state["name"],
                state["price"],
                state["description"],
                document["file_id"]
            ))

            db.commit()
            states.pop(user_id, None)

            send(chat_id, "File uploaded successfully.")
            return

    # Start and referral registration.
    if text.startswith("/start"):

        parts = text.split()
        referrer = None

        if len(parts) > 1 and parts[1].isdigit():
            referrer = int(parts[1])

        ensure_user(user_id, referrer)

        if not check_membership(user_id):

            send(
                chat_id,
                "Welcome to KitKatFiles!\n\n"
                "Please join both channels and verify your membership.",
                join_keyboard()
            )

            return

        verify_user(user_id, chat_id)
        return

    user = get_user(user_id)

    if not user:
        send(chat_id, "Please send /start first.")
        return

    if not is_admin(user_id) and not user["verified"]:
        send(
            chat_id,
            "Please complete channel verification first.",
            join_keyboard()
        )
        return

    if text.startswith("/redeem "):

        redeem_code(
            user_id,
            chat_id,
            text.split(maxsplit=1)[1]
        )
        return

    if text == "Buy Files":
        show_files(chat_id)

    elif text == "My Files":
        my_files(user_id, chat_id)

    elif text == "Balance":

        user = get_user(user_id)

        send(
            chat_id,
            f"Your balance: {user['balance']} credits"
        )

    elif text == "Support":

        send(
            chat_id,
            f"Contact support: {SUPPORT_BOT}"
        )

    else:

        send(
            chat_id,
            "Please choose an option from the keyboard."
        )


# ==================================================
# CALLBACK HANDLER
# ==================================================

def handle_callback(callback):

    data = callback["data"]
    user_id = callback["from"]["id"]
    chat_id = callback["message"]["chat"]["id"]

    answer_callback(callback["id"])

    # Force-join verification.
    if data == "verify":

        ensure_user(user_id)
        verify_user(user_id, chat_id)
        return

    # Admin panel callbacks.
    if data.startswith("admin_"):

        if not is_admin(user_id):
            answer_callback(callback["id"], "Not authorized.")
            return

        if data == "admin_upload":

            states[user_id] = "upload_meta"

            send(
                chat_id,
                "Send file details:\n"
                "File Name | Price | Description\n\n"
                "Send /cancel to cancel."
            )

        elif data == "admin_addcoins":

            states[user_id] = "addcoins"

            send(
                chat_id,
                "Send user ID and credit amount:\n"
                "USER_ID AMOUNT\n\n"
                "Send /cancel to cancel."
            )

        elif data == "admin_gift":

            states[user_id] = "gift"

            send(
                chat_id,
                "Send gift-code amount and number of uses:\n"
        
