"""
VeloceVoce 惟落雀 - 付款提醒机器人
负责：
  - 对 awaiting_payment 订单发送4级提醒
  - 逾期付款的短信提醒
  - 每日报告生成
  - 通过 JSON 文件追踪提醒状态
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
logger = logging.getLogger('payment_bot')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'recharge.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'bot_config.json')
REMINDERS_FILE = os.path.join(BASE_DIR, 'payment_reminders.json')

# 4级提醒计划（小时）
REMINDER_SCHEDULE = [1, 6, 24, 72]

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def load_reminders():
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_reminders(data):
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

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

def send_sms_reminder(cfg, phone, order_id, amount, level):
    """发送短信付款提醒"""
    secret_id = cfg.get('sms_secret_id', '')
    secret_key = cfg.get('sms_secret_key', '')
    if not secret_id or not secret_key:
        logger.warning("[SMS] SMS credentials not configured, skipping reminder")
        return
    logger.info(f"[SMS] reminder level={level} to phone={phone} order={order_id[:8]} amount={amount}")

def process_payment_reminders(db, cfg):
    reminders = load_reminders()
    rows = db.execute(
        "SELECT o.*, u.phone as user_phone, u.email FROM orders o "
        "LEFT JOIN users u ON o.user_id=u.id "
        "WHERE o.status='awaiting_payment' ORDER BY o.created_at ASC"
    ).fetchall()
    changed = False
    for row in rows:
        order = dict(row)
        oid = order['id']
        created = datetime.fromisoformat(order['created_at'])
        state = reminders.get(oid, {"level": 0, "last_sent": None})
        current_level = state["level"]
        if current_level >= len(REMINDER_SCHEDULE):
            continue
        hours_elapsed = (datetime.now() - created).total_seconds() / 3600
        next_remind_at = sum(REMINDER_SCHEDULE[:current_level + 1])
        if hours_elapsed >= next_remind_at:
            level = current_level + 1
            logger.info(f"[REMINDER] order={oid[:8]} level={level} elapsed={hours_elapsed:.1f}h")
            tg_token = cfg.get('telegram_bot_token', '')
            tg_chat = cfg.get('telegram_chat_id', '')
            msg = (f"💳 付款提醒 (第{level}次)\n"
                   f"订单: {oid[:8]}\n"
                   f"金额: €{order['amount']}\n"
                   f"号码: {order['phone']}\n"
                   f"已等待: {hours_elapsed:.1f}小时")
            send_telegram(tg_token, tg_chat, msg)
            if order.get('user_phone'):
                send_sms_reminder(cfg, order['user_phone'], oid, order['amount'], level)
            state["level"] = level
            state["last_sent"] = datetime.now().isoformat()
            reminders[oid] = state
            changed = True
    if changed:
        save_reminders(reminders)
    # 清理已完成/取消订单的记录
    cleanup_ids = [oid for oid in reminders if oid not in [dict(r)['id'] for r in rows]]
    if cleanup_ids:
        for oid in cleanup_ids:
            completed = db.execute(
                "SELECT status FROM orders WHERE id=?", (oid,)
            ).fetchone()
            if completed and completed['status'] not in ('awaiting_payment',):
                del reminders[oid]
                changed = True
    if changed:
        save_reminders(reminders)

def generate_daily_report(db, cfg):
    today = datetime.now().strftime('%Y-%m-%d')
    stats = {}
    stats['total_orders'] = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE created_at LIKE ?", (today + '%',)
    ).fetchone()['c']
    stats['completed'] = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status='completed' AND updated_at LIKE ?", (today + '%',)
    ).fetchone()['c']
    stats['awaiting_payment'] = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status='awaiting_payment'"
    ).fetchone()['c']
    stats['revenue'] = db.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM orders WHERE status='completed' AND updated_at LIKE ?",
        (today + '%',)
    ).fetchone()['s']
    report = (f"📊 每日报告 {today}\n"
              f"今日订单: {stats['total_orders']}\n"
              f"完成订单: {stats['completed']}\n"
              f"待付款: {stats['awaiting_payment']}\n"
              f"今日收入: €{stats['revenue']:.2f}")
    logger.info(f"[REPORT] {report}")
    tg_token = cfg.get('telegram_bot_token', '')
    tg_chat = cfg.get('telegram_chat_id', '')
    send_telegram(tg_token, tg_chat, report)

def run():
    cfg = load_config()
    poll_interval = cfg.get('poll_interval', 60)
    logger.info(f"[PAYMENT_BOT] started, poll_interval={poll_interval}s")
    last_report_date = None
    while True:
        try:
            db = get_db()
            process_payment_reminders(db, cfg)
            today = datetime.now().strftime('%Y-%m-%d')
            report_hour = datetime.now().hour
            if today != last_report_date and report_hour >= 9:
                generate_daily_report(db, cfg)
                last_report_date = today
            db.close()
        except Exception as e:
            logger.error(f"[PAYMENT_BOT] error: {e}")
        time.sleep(poll_interval)

if __name__ == '__main__':
    run()
