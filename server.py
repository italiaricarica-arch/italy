"""
VeloceVoce 惟落雀 - 意大利手机充值系统 v2.0
启动: python server.py
用户页面: http://localhost:8000
管理后台: http://localhost:8000/admin (密码通过环境变量 RECHARGE_ADMIN_PWD 设置)
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import hashlib
import secrets
import uuid
import time
import json
import os
import re
import random
import hmac
import base64
import urllib.parse
import logging
import asyncio
from datetime import datetime, timedelta
from contextlib import contextmanager
from collections import defaultdict

# ====== 日志 ======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('recharge')

# ====== Telegram 预警通知 ======
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

async def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] {e}")

app = FastAPI(title="VeloceVoce 惟落雀")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 100
RATE_LIMIT_WINDOW = 60

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    rate_limit_store[client_ip] = [t for t in rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    rate_limit_store[client_ip].append(now)
    response = await call_next(request)
    return response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 管理员密码通过环境变量配置，默认值仅用于本地开发
ADMIN_PASSWORD = os.environ.get("RECHARGE_ADMIN_PWD", "recharge2025")
DB_FILE = os.path.join(BASE_DIR, "recharge.db")
NEW_USER_CREDIT = 10.0
FIXED_AMOUNTS = [5, 10, 15, 20, 25, 30, 50]

SMS_SECRET_ID = os.environ.get("SMS_SECRET_ID", "")
SMS_SECRET_KEY = os.environ.get("SMS_SECRET_KEY", "")
SMS_SDK_APP_ID = os.environ.get("SMS_SDK_APP_ID", "")
SMS_TEMPLATE_REGISTER = os.environ.get("SMS_TEMPLATE_REGISTER", "2930156")
SMS_TEMPLATE_LOGIN = os.environ.get("SMS_TEMPLATE_LOGIN", "2930154")
SMS_TEMPLATE_FORGOT = os.environ.get("SMS_TEMPLATE_FORGOT", "2930155")
SMS_TEMPLATE_RECHARGE = os.environ.get("SMS_TEMPLATE_RECHARGE", "2930157")
SMS_TEMPLATE_PAYMENT = os.environ.get("SMS_TEMPLATE_PAYMENT", "2930158")
SMS_TEMPLATE_UNIVERSAL = os.environ.get("SMS_TEMPLATE_UNIVERSAL", "2930159")
SMS_SIGN_NAME = os.environ.get("SMS_SIGN_NAME", "Velocevoce·惟落雀")
SMS_CODE_EXPIRE = 5
SMS_CODE_LENGTH = 6

CAPTCHA_APP_ID = os.environ.get("CAPTCHA_APP_ID", "")
CAPTCHA_APP_SECRET = os.environ.get("CAPTCHA_APP_SECRET", "")

OPERATOR_PREFIXES = {
    "TIM": ["330", "331", "333", "334", "335", "336", "337", "338", "339", "360", "361", "362", "363", "366", "368"],
    "Vodafone": ["340", "341", "342", "343", "344", "345", "346", "347", "348", "349", "383"],
    "WindTre": ["320", "322", "323", "324", "325", "326", "327", "328", "329", "380", "388", "389", "390", "391", "392", "393", "397"],
    "Iliad": ["351", "352", "353"],
    "Very": ["370", "371"],
    "Lycamobile": ["373"],
    "CMLink": ["350"],
    "DailyTelecom": ["375"],
    "ho.": ["377", "378"],
    "Kena": ["354", "355"],
}

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                phone TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                nickname TEXT DEFAULT '',
                phone_model TEXT DEFAULT '',
                register_ip TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                fingerprint TEXT DEFAULT '',
                credit_used INTEGER DEFAULT 0,
                credit_amount REAL DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                phone TEXT NOT NULL,
                operator TEXT NOT NULL,
                amount REAL NOT NULL,
                bonus REAL DEFAULT 0,
                total REAL DEFAULT 0,
                payment TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                is_credit INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS sms_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                code TEXT NOT NULL,
                purpose TEXT DEFAULT 'register',
                ip TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS site_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                type TEXT DEFAULT 'info',
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                order_id TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('online_count', '0')")
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cny_active', '1')")

        for col in ['address', 'city', 'postal_code', 'region', 'country']:
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass

        credit_cols = {
            'credit_score': 'INTEGER DEFAULT 0',
            'credit_level': "TEXT DEFAULT '新手'",
            'total_spent': 'REAL DEFAULT 0',
            'consecutive_success': 'INTEGER DEFAULT 0',
            'unpaid_order_id': "TEXT DEFAULT ''",
            'milestone_100': 'INTEGER DEFAULT 0',
            'milestone_300': 'INTEGER DEFAULT 0',
        }
        for col, col_type in credit_cols.items():
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except Exception:
                pass

init_db()

# ====== Pydantic Models ======

class UserRegister(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str
    sms_code: str = ""
    name: Optional[str] = ""
    fingerprint: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    cap: Optional[str] = ""
    provincia: Optional[str] = ""
    country: Optional[str] = "Italia"

class UserLogin(BaseModel):
    account: str
    password: str
    sms_code: str = ""

class OrderCreate(BaseModel):
    phone: str
    operator: str
    amount: float
    is_credit: Optional[bool] = False

class OrderUpdate(BaseModel):
    status: str
    message: Optional[str] = ""

class AdminLogin(BaseModel):
    password: str

# ====== Helpers ======

def hash_pw(pw):
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + pw).encode()).hexdigest()
    return f"{salt}${hashed}"

def verify_pw(pw, stored_hash):
    if '$' in stored_hash:
        salt, hashed = stored_hash.split('$', 1)
        return hashlib.sha256((salt + pw).encode()).hexdigest() == hashed
    return hashlib.sha256(pw.encode()).hexdigest() == stored_hash

def gen_token():
    return secrets.token_hex(32)

def validate_italian_phone(phone):
    phone = re.sub(r'\D', '', phone)
    if len(phone) == 12 and phone.startswith('39'):
        phone = phone[2:]
    if len(phone) == 13 and phone.startswith('+39'):
        phone = phone[3:]
    if len(phone) != 10:
        return None, "号码必须是10位数字"
    if not phone.startswith('3'):
        return None, "意大利手机号必须3开头"
    return phone, None

def check_operator_match(phone, operator):
    prefix3 = phone[:3]
    matched_ops = []
    for op, prefixes in OPERATOR_PREFIXES.items():
        if prefix3 in prefixes:
            matched_ops.append(op)
    if not matched_ops:
        return True, None
    if operator in matched_ops:
        return True, None
    return False, matched_ops[0]

def get_cny_bonus(amount):
    if amount >= 50:
        return 20
    if amount >= 20:
        return 10
    return 0

def get_user_from_token(token, db):
    if not token:
        return None
    row = db.execute(
        "SELECT s.user_id, u.* FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.token = ? AND s.expires_at > ?",
        (token, datetime.now().isoformat())
    ).fetchone()
    return dict(row) if row else None

CREDIT_LEVELS = [
    {"name": "新手", "icon": "🌱", "min_score": 0,   "credit_limit": 10,  "discount": 1.0, "bonus": 0},
    {"name": "铜牌", "icon": "🥉", "min_score": 50,  "credit_limit": 15,  "discount": 1.0, "bonus": 0},
    {"name": "银牌", "icon": "🥈", "min_score": 150, "credit_limit": 25,  "discount": 1.0, "bonus": 5},
    {"name": "金牌", "icon": "🥇", "min_score": 300, "credit_limit": 50,  "discount": 0.9, "bonus": 0},
    {"name": "钻石", "icon": "💎", "min_score": 500, "credit_limit": 100, "discount": 0.8, "bonus": 10},
]

def get_credit_level(score):
    level = CREDIT_LEVELS[0]
    for lv in CREDIT_LEVELS:
        if score >= lv["min_score"]:
            level = lv
    return level

def get_next_level(score):
    for lv in CREDIT_LEVELS:
        if score < lv["min_score"]:
            return lv
    return None

def update_credit_score(db, user_id, order_amount, is_credit_order=False):
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return
    user = dict(user)

    score = user.get('credit_score', 0) or 0
    total = user.get('total_spent', 0) or 0
    streak = user.get('consecutive_success', 0) or 0
    m100 = user.get('milestone_100', 0) or 0
    m300 = user.get('milestone_300', 0) or 0

    if order_amount >= 30:
        points = 20
    elif order_amount >= 15:
        points = 10
    else:
        points = 5

    if is_credit_order:
        points += 15

    streak += 1
    if streak >= 3 and streak % 3 == 0:
        points += 30
        logger.info(f"[CREDIT] user={user_id} streak={streak} bonus +30")

    score += points
    total += order_amount

    if total >= 100 and not m100:
        score += 50
        m100 = 1
        logger.info(f"[CREDIT] user={user_id} milestone 100€ bonus +50")
    if total >= 300 and not m300:
        score += 100
        m300 = 1
        logger.info(f"[CREDIT] user={user_id} milestone 300€ bonus +100")

    old_level = get_credit_level(user.get('credit_score', 0) or 0)
    new_level = get_credit_level(score)

    db.execute("""
        UPDATE users SET credit_score = ?, credit_level = ?, total_spent = ?,
        consecutive_success = ?, milestone_100 = ?, milestone_300 = ?,
        credit_amount = ?
        WHERE id = ?
    """, (score, new_level["name"], total, streak, m100, m300,
          new_level["credit_limit"], user_id))

    if new_level["name"] != old_level["name"] and new_level["bonus"] > 0:
        logger.info(f"[CREDIT] user={user_id} LEVEL UP: {old_level['name']} → {new_level['name']}, bonus €{new_level['bonus']}")

    logger.info(f"[CREDIT] user={user_id} +{points}pts, total={score}, level={new_level['name']}")
    return {"points_added": points, "new_score": score, "new_level": new_level}

def get_credit_discount(user):
    score = user.get('credit_score', 0) or 0
    level = get_credit_level(score)
    return level["discount"]

def check_unpaid_order(db, user_id):
    unpaid = db.execute(
        "SELECT id, amount, created_at FROM orders WHERE user_id = ? AND is_credit = 1 AND status = 'completed' AND payment = 'credit'",
        (user_id,)
    ).fetchone()
    if unpaid:
        return dict(unpaid)
    return None

def check_anti_fraud(db, email=None, phone=None, ip=None, fingerprint=None):
    reasons = []
    if email:
        existing = db.execute("SELECT COUNT(*) as c FROM users WHERE email = ?", (email,)).fetchone()
        if existing['c'] > 0:
            reasons.append("该邮箱已注册")
    if phone:
        existing = db.execute("SELECT COUNT(*) as c FROM users WHERE phone = ?", (phone,)).fetchone()
        if existing['c'] > 0:
            reasons.append("该手机号已注册")
    if ip:
        since = (datetime.now() - timedelta(hours=24)).isoformat()
        ip_count = db.execute(
            "SELECT COUNT(*) as c FROM users WHERE register_ip = ? AND created_at > ?",
            (ip, since)
        ).fetchone()
        if ip_count['c'] >= 3:
            reasons.append("注册过于频繁，请稍后再试")
    if fingerprint and fingerprint != '':
        fp_count = db.execute(
            "SELECT COUNT(*) as c FROM users WHERE fingerprint = ?",
            (fingerprint,)
        ).fetchone()
        if fp_count['c'] >= 2:
            reasons.append("该设备已注册过账号")
    return reasons

def send_site_message(db, user_id, title, content="", msg_type="info", order_id=""):
    db.execute(
        "INSERT INTO site_messages (user_id, type, title, content, order_id, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, msg_type, title, content, order_id, datetime.now().isoformat())
    )

# ====== SMS ======

def send_sms_code(phone, purpose, ip=""):
    if not SMS_SECRET_ID or not SMS_SECRET_KEY:
        logger.warning("[SMS] credentials not configured")
        return False, "短信服务未配置"
    code = ''.join([str(random.randint(0, 9)) for _ in range(SMS_CODE_LENGTH)])
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO sms_codes (phone, code, purpose, ip, created_at) VALUES (?,?,?,?,?)",
                (phone, code, purpose, ip, datetime.now().isoformat())
            )
        logger.info(f"[SMS] code={code} phone={phone} purpose={purpose}")
        return True, code
    except Exception as e:
        logger.error(f"[SMS] error: {e}")
        return False, str(e)

def verify_sms_code(phone, code, purpose):
    with get_db() as db:
        expire_time = (datetime.now() - timedelta(minutes=SMS_CODE_EXPIRE)).isoformat()
        row = db.execute(
            "SELECT id FROM sms_codes WHERE phone=? AND code=? AND purpose=? AND used=0 AND created_at>? ORDER BY id DESC LIMIT 1",
            (phone, code, purpose, expire_time)
        ).fetchone()
        if not row:
            return False
        db.execute("UPDATE sms_codes SET used=1 WHERE id=?", (row['id'],))
        return True

# ====== API Routes ======

@app.get("/", response_class=HTMLResponse)
async def index():
    f = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>VeloceVoce</h1>")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    f = os.path.join(BASE_DIR, "admin.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Admin</h1>")

@app.get("/help", response_class=HTMLResponse)
async def help_page():
    f = os.path.join(BASE_DIR, "help.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Help</h1>")

@app.get("/cookies", response_class=HTMLResponse)
async def cookies_page():
    f = os.path.join(BASE_DIR, "cookies.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Cookies</h1>")

@app.get("/legal", response_class=HTMLResponse)
async def legal_page():
    f = os.path.join(BASE_DIR, "legal.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Legal</h1>")

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    f = os.path.join(BASE_DIR, "privacy.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Privacy</h1>")

@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    f = os.path.join(BASE_DIR, "terms.html")
    if os.path.exists(f):
        return HTMLResponse(open(f, encoding='utf-8').read())
    return HTMLResponse("<h1>Terms</h1>")

@app.get("/app.js")
async def serve_appjs():
    f = os.path.join(BASE_DIR, "app.js")
    if os.path.exists(f):
        return FileResponse(f, media_type="application/javascript")
    raise HTTPException(404)

@app.get("/style.css")
async def serve_css():
    f = os.path.join(BASE_DIR, "style.css")
    if os.path.exists(f):
        return FileResponse(f, media_type="text/css")
    raise HTTPException(404)

# ------ Auth ------

@app.post("/api/register")
async def register(data: UserRegister, request: Request):
    ip = request.client.host if request.client else ""
    if not data.email and not data.phone:
        raise HTTPException(400, "请提供邮箱或手机号")
    if len(data.password) < 6:
        raise HTTPException(400, "密码至少6位")
    with get_db() as db:
        fraud = check_anti_fraud(db, email=data.email, phone=data.phone, ip=ip, fingerprint=data.fingerprint)
        if fraud:
            raise HTTPException(400, fraud[0])
        user_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        try:
            db.execute("""
                INSERT INTO users (id, email, phone, password_hash, nickname, register_ip, user_agent, fingerprint, credit_amount, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (user_id, data.email, data.phone, hash_pw(data.password),
                  data.name or "", ip, "", data.fingerprint or "", NEW_USER_CREDIT, now))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "该账号已注册")
        token = gen_token()
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        db.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                   (token, user_id, now, expires))
        send_site_message(db, user_id, "欢迎加入 VeloceVoce！",
                          f"注册成功，获得 €{NEW_USER_CREDIT} 信用额度，祝您使用愉快！", "success")
        logger.info(f"[REGISTER] user={user_id} email={data.email} phone={data.phone} ip={ip}")
    return {"token": token, "user_id": user_id}

@app.post("/api/login")
async def login(data: UserLogin, request: Request):
    ip = request.client.host if request.client else ""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM users WHERE email=? OR phone=?",
            (data.account, data.account)
        ).fetchone()
        if not row:
            raise HTTPException(401, "账号不存在")
        user = dict(row)
        if user.get('is_blocked'):
            raise HTTPException(403, "该账号已被封禁")
        if not verify_pw(data.password, user['password_hash']):
            raise HTTPException(401, "密码错误")
        token = gen_token()
        now = datetime.now().isoformat()
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        db.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                   (token, user['id'], now, expires))
        db.execute("UPDATE users SET last_login=? WHERE id=?", (now, user['id']))
        logger.info(f"[LOGIN] user={user['id']} ip={ip}")
    return {"token": token, "user_id": user['id']}

@app.post("/api/logout")
async def logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        with get_db() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"ok": True}

@app.post("/api/send-sms")
async def send_sms(request: Request):
    body = await request.json()
    phone = body.get("phone", "")
    purpose = body.get("purpose", "register")
    ip = request.client.host if request.client else ""
    phone, err = validate_italian_phone(phone)
    if err:
        raise HTTPException(400, err)
    ok, result = send_sms_code(phone, purpose, ip)
    if not ok:
        raise HTTPException(500, result)
    return {"ok": True}

@app.get("/api/me")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        unread = db.execute(
            "SELECT COUNT(*) as c FROM site_messages WHERE user_id=? AND is_read=0",
            (user['id'],)
        ).fetchone()['c']
        score = user.get('credit_score', 0) or 0
        level = get_credit_level(score)
        next_lv = get_next_level(score)
    return {
        "id": user['id'],
        "email": user.get('email'),
        "phone": user.get('phone'),
        "nickname": user.get('nickname', ''),
        "credit_amount": user.get('credit_amount', 0),
        "credit_used": user.get('credit_used', 0),
        "credit_score": score,
        "credit_level": level,
        "next_level": next_lv,
        "unread_messages": unread,
    }

@app.get("/api/operators")
async def get_operators():
    return {"operators": list(OPERATOR_PREFIXES.keys())}

@app.get("/api/amounts")
async def get_amounts():
    return {"amounts": FIXED_AMOUNTS}

@app.post("/api/orders")
async def create_order(data: OrderCreate, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        if user.get('is_blocked'):
            raise HTTPException(403, "账号已封禁")

        phone, err = validate_italian_phone(data.phone)
        if err:
            raise HTTPException(400, err)

        match, suggested = check_operator_match(phone, data.operator)
        if not match:
            raise HTTPException(400, f"号码前缀与运营商不匹配，建议选择 {suggested}")

        if data.amount not in FIXED_AMOUNTS:
            raise HTTPException(400, "无效金额")

        cny_active = db.execute("SELECT value FROM settings WHERE key='cny_active'").fetchone()
        bonus = get_cny_bonus(data.amount) if (cny_active and cny_active['value'] == '1') else 0

        credit_limit = user.get('credit_amount', 0)
        if data.is_credit:
            unpaid = check_unpaid_order(db, user['id'])
            if unpaid:
                raise HTTPException(400, f"您有未支付的赊账订单 #{unpaid['id'][:8]}，请先结清")
            if data.amount > credit_limit:
                raise HTTPException(400, f"超出信用额度 €{credit_limit}")

        order_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        status = 'charged' if not data.is_credit else 'charged'
        payment = 'credit' if data.is_credit else ''

        db.execute("""
            INSERT INTO orders (id, user_id, phone, operator, amount, bonus, total, payment, status, is_credit, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (order_id, user['id'], phone, data.operator, data.amount, bonus,
              data.amount + bonus, payment, status, 1 if data.is_credit else 0, now))

        logger.info(f"[ORDER] id={order_id} user={user['id']} phone={phone} operator={data.operator} amount={data.amount} credit={data.is_credit}")
        asyncio.create_task(send_telegram(
            f"🆕 新订单\n用户: {user.get('email') or user.get('phone')}\n号码: {phone}\n运营商: {data.operator}\n金额: €{data.amount}"
        ))

    return {"order_id": order_id, "status": status}

@app.get("/api/orders")
async def list_orders(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        rows = db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (user['id'],)
        ).fetchall()
    return {"orders": [dict(r) for r in rows]}

@app.get("/api/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        row = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, "订单不存在")
    return dict(row)

@app.get("/api/promotions")
async def get_promotions():
    with get_db() as db:
        cny = db.execute("SELECT value FROM settings WHERE key='cny_active'").fetchone()
    return {
        "cny_active": cny['value'] == '1' if cny else False,
        "bonuses": {"50": 20, "20": 10}
    }

@app.get("/api/online-count")
async def online_count():
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key='online_count'").fetchone()
    return {"count": int(row['value']) if row else 0}

@app.post("/api/heartbeat")
async def heartbeat():
    return {"ok": True}

@app.get("/api/messages")
async def get_messages(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        rows = db.execute(
            "SELECT * FROM site_messages WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (user['id'],)
        ).fetchall()
        db.execute("UPDATE site_messages SET is_read=1 WHERE user_id=?", (user['id'],))
    return {"messages": [dict(r) for r in rows]}

@app.get("/api/credit-info")
async def credit_info(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        user = get_user_from_token(token, db)
        if not user:
            raise HTTPException(401, "未登录")
        score = user.get('credit_score', 0) or 0
        level = get_credit_level(score)
        next_lv = get_next_level(score)
        unpaid = check_unpaid_order(db, user['id'])
    return {
        "credit_amount": user.get('credit_amount', 0),
        "credit_used": user.get('credit_used', 0),
        "credit_score": score,
        "credit_level": level,
        "next_level": next_lv,
        "unpaid_order": unpaid,
        "levels": CREDIT_LEVELS,
    }

# ------ Admin ------

def get_admin_from_token(token, db):
    if not token:
        return None
    row = db.execute(
        "SELECT token FROM admin_sessions WHERE token=? AND expires_at>?",
        (token, datetime.now().isoformat())
    ).fetchone()
    return row is not None

@app.post("/api/admin/login")
async def admin_login(data: AdminLogin):
    if not hmac.compare_digest(data.password, ADMIN_PASSWORD):
        raise HTTPException(401, "密码错误")
    token = gen_token()
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(hours=8)).isoformat()
    with get_db() as db:
        db.execute("INSERT INTO admin_sessions (token, created_at, expires_at) VALUES (?,?,?)",
                   (token, now, expires))
    return {"token": token}

@app.post("/api/admin/logout")
async def admin_logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        with get_db() as db:
            db.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
    return {"ok": True}

@app.get("/api/admin/orders")
async def admin_orders(request: Request, status: str = "", page: int = 1, per_page: int = 20):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        offset = (page - 1) * per_page
        if status:
            rows = db.execute(
                "SELECT o.*, u.email, u.phone as user_phone FROM orders o LEFT JOIN users u ON o.user_id=u.id WHERE o.status=? ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                (status, per_page, offset)
            ).fetchall()
            total = db.execute("SELECT COUNT(*) as c FROM orders WHERE status=?", (status,)).fetchone()['c']
        else:
            rows = db.execute(
                "SELECT o.*, u.email, u.phone as user_phone FROM orders o LEFT JOIN users u ON o.user_id=u.id ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            ).fetchall()
            total = db.execute("SELECT COUNT(*) as c FROM orders").fetchone()['c']
    return {"orders": [dict(r) for r in rows], "total": total, "page": page}

@app.put("/api/admin/orders/{order_id}")
async def admin_update_order(order_id: str, data: OrderUpdate, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(404, "订单不存在")
        order = dict(order)
        now = datetime.now().isoformat()
        db.execute("UPDATE orders SET status=?, message=?, updated_at=? WHERE id=?",
                   (data.status, data.message, now, order_id))
        if data.status == 'completed':
            update_credit_score(db, order['user_id'], order['amount'], bool(order['is_credit']))
            send_site_message(db, order['user_id'],
                              f"充值成功 €{order['amount']}",
                              f"号码 {order['phone']} 充值 €{order['amount']} 已完成。",
                              "success", order_id)
            asyncio.create_task(send_telegram(
                f"✅ 订单完成\n#{order_id[:8]}\n号码: {order['phone']}\n金额: €{order['amount']}"
            ))
        elif data.status == 'failed':
            send_site_message(db, order['user_id'],
                              f"充值失败 €{order['amount']}",
                              f"号码 {order['phone']} 充值失败，原因：{data.message or '未知'}",
                              "error", order_id)
        logger.info(f"[ADMIN] order={order_id} status={data.status}")
    return {"ok": True}

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        total_users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
        total_orders = db.execute("SELECT COUNT(*) as c FROM orders").fetchone()['c']
        completed = db.execute("SELECT COUNT(*) as c FROM orders WHERE status='completed'").fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM orders WHERE status IN ('pending','charged','processing')").fetchone()['c']
        revenue = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM orders WHERE status='completed'").fetchone()['s']
        today = datetime.now().strftime('%Y-%m-%d')
        today_orders = db.execute(
            "SELECT COUNT(*) as c FROM orders WHERE created_at LIKE ?",
            (today + '%',)
        ).fetchone()['c']
    return {
        "total_users": total_users,
        "total_orders": total_orders,
        "completed_orders": completed,
        "pending_orders": pending,
        "total_revenue": revenue,
        "today_orders": today_orders,
    }

@app.get("/api/admin/users")
async def admin_users(request: Request, page: int = 1, per_page: int = 20):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT id, email, phone, nickname, credit_amount, credit_score, credit_level, is_blocked, created_at, last_login FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        total = db.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
    return {"users": [dict(r) for r in rows], "total": total}

@app.post("/api/admin/users/{user_id}/block")
async def admin_block_user(user_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        db.execute("UPDATE users SET is_blocked=1 WHERE id=?", (user_id,))
        logger.info(f"[ADMIN] blocked user={user_id}")
    return {"ok": True}

@app.post("/api/admin/users/{user_id}/unblock")
async def admin_unblock_user(user_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        db.execute("UPDATE users SET is_blocked=0 WHERE id=?", (user_id,))
        logger.info(f"[ADMIN] unblocked user={user_id}")
    return {"ok": True}

@app.post("/api/admin/confirm-payment/{order_id}")
async def admin_confirm_payment(order_id: str, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(404, "订单不存在")
        order = dict(order)
        now = datetime.now().isoformat()
        db.execute("UPDATE orders SET status='processing', updated_at=? WHERE id=?", (now, order_id))
        logger.info(f"[ADMIN] confirmed payment for order={order_id}")
    return {"ok": True}

@app.post("/api/admin/toggle-cny")
async def admin_toggle_cny(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    with get_db() as db:
        if not get_admin_from_token(token, db):
            raise HTTPException(401, "未授权")
        row = db.execute("SELECT value FROM settings WHERE key='cny_active'").fetchone()
        new_val = '0' if (row and row['value'] == '1') else '1'
        db.execute("UPDATE settings SET value=? WHERE key='cny_active'", (new_val,))
    return {"cny_active": new_val == '1'}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
