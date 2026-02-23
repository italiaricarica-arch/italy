"""
VeloceVoce 惟落雀 - 订单调度器
负责监控订单状态转换：
  charged → awaiting_payment (信用) 或 processing (标准)
  holding → processing (前序订单完成后释放)
  processing 超时预警
  paying 状态监控
"""

import time
import json
import sqlite3
import logging
import os
import urllib.request
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('dispatcher')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'recharge.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'bot_config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def send_pushplus(token, title, content, topic=""):
    if not token:
        return
    try:
        data = json.dumps({
            "token": token,
            "title": title,
            "content": content,
            "topic": topic,
            "template": "html"
        }).encode('utf-8')
        req = urllib.request.Request(
            "http://www.pushplus.plus/send",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error(f"[PUSHPLUS] {e}")

def send_telegram(token, chat_id, msg):
    if not token or not chat_id:
        return
    try:
        data = json.dumps({
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML"
        }).encode('utf-8')
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error(f"[TELEGRAM] {e}")

def process_charged_orders(db, cfg):
    """将 charged 状态的订单推进到下一步"""
    rows = db.execute(
        "SELECT * FROM orders WHERE status='charged' ORDER BY created_at ASC"
    ).fetchall()
    for row in rows:
        order = dict(row)
        now = datetime.now().isoformat()
        if order.get('is_credit'):
            # 信用订单 → 等待付款
            db.execute(
                "UPDATE orders SET status='awaiting_payment', updated_at=? WHERE id=?",
                (now, order['id'])
            )
            logger.info(f"[DISPATCH] {order['id'][:8]} charged → awaiting_payment (credit)")
        else:
            # 标准订单 → 检查是否有前序 holding 订单
            db.execute(
                "UPDATE orders SET status='processing', updated_at=? WHERE id=?",
                (now, order['id'])
            )
            logger.info(f"[DISPATCH] {order['id'][:8]} charged → processing")
        db.commit()

def release_holding_orders(db, cfg):
    """将 holding 状态的订单释放为 processing（当前序订单完成后）"""
    holding = db.execute(
        "SELECT * FROM orders WHERE status='holding' ORDER BY created_at ASC"
    ).fetchall()
    for row in holding:
        order = dict(row)
        user_id = order['user_id']
        # 检查该用户是否有进行中的 processing 订单
        in_progress = db.execute(
            "SELECT COUNT(*) as c FROM orders WHERE user_id=? AND status IN ('processing','paying') AND id!=?",
            (user_id, order['id'])
        ).fetchone()['c']
        if in_progress == 0:
            now = datetime.now().isoformat()
            db.execute(
                "UPDATE orders SET status='processing', updated_at=? WHERE id=?",
                (now, order['id'])
            )
            db.commit()
            logger.info(f"[DISPATCH] {order['id'][:8]} holding → processing (slot available)")

def check_processing_timeout(db, cfg, timeout_minutes=30):
    """检查 processing 超时订单"""
    threshold = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
    rows = db.execute(
        "SELECT * FROM orders WHERE status='processing' AND (updated_at < ? OR (updated_at='' AND created_at < ?))",
        (threshold, threshold)
    ).fetchall()
    for row in rows:
        order = dict(row)
        logger.warning(f"[TIMEOUT] order={order['id'][:8]} processing for >{timeout_minutes}min")
        token = cfg.get('pushplus_token', '')
        tg_token = cfg.get('telegram_bot_token', '')
        tg_chat = cfg.get('telegram_chat_id', '')
        msg = (f"⚠️ 充值超时\n订单: {order['id'][:8]}\n"
               f"号码: {order['phone']}\n运营商: {order['operator']}\n"
               f"金额: €{order['amount']}\n超时: {timeout_minutes}分钟")
        send_pushplus(token, "充值超时预警", msg)
        send_telegram(tg_token, tg_chat, msg)

def check_paying_status(db, cfg, timeout_minutes=60):
    """检查 paying 状态超时"""
    threshold = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
    rows = db.execute(
        "SELECT * FROM orders WHERE status='paying' AND (updated_at < ? OR (updated_at='' AND created_at < ?))",
        (threshold, threshold)
    ).fetchall()
    for row in rows:
        order = dict(row)
        logger.warning(f"[PAYING_TIMEOUT] order={order['id'][:8]}")
        tg_token = cfg.get('telegram_bot_token', '')
        tg_chat = cfg.get('telegram_chat_id', '')
        msg = (f"⚠️ 支付超时\n订单: {order['id'][:8]}\n"
               f"号码: {order['phone']}\n金额: €{order['amount']}")
        send_telegram(tg_token, tg_chat, msg)

def run():
    cfg = load_config()
    poll_interval = cfg.get('poll_interval', 10)
    logger.info(f"[DISPATCHER] started, poll_interval={poll_interval}s")
    while True:
        try:
            db = get_db()
            process_charged_orders(db, cfg)
            release_holding_orders(db, cfg)
            check_processing_timeout(db, cfg)
            check_paying_status(db, cfg)
            db.close()
        except Exception as e:
            logger.error(f"[DISPATCHER] error: {e}")
        time.sleep(poll_interval)

if __name__ == '__main__':
    run()
