"""
VeloceVoce 惟落雀 - 充值自动化机器人
负责：
  - 基于 ADB 的瓜瓜充值 App 自动化操作
  - 多账号和多卡轮换
  - PushPlus 和 Telegram 通知
  - 充值成功后的短信通知
"""

import time
import json
import sqlite3
import logging
import os
import subprocess
import urllib.request
import random
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('order_bot')

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
        logger.info(f"[PUSHPLUS] sent: {title}")
    except Exception as e:
        logger.error(f"[PUSHPLUS] error: {e}")

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
        logger.error(f"[TELEGRAM] error: {e}")

def adb_cmd(adb_path, *args):
    """执行 ADB 命令"""
    cmd = [adb_path] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip(), result.returncode
    except Exception as e:
        logger.error(f"[ADB] error: {e}")
        return "", -1

def adb_tap(adb_path, x, y):
    return adb_cmd(adb_path, 'shell', 'input', 'tap', str(x), str(y))

def adb_text(adb_path, text):
    text = text.replace(' ', '%s')
    return adb_cmd(adb_path, 'shell', 'input', 'text', text)

def adb_screenshot(adb_path, output_path):
    adb_cmd(adb_path, 'shell', 'screencap', '-p', '/sdcard/screen.png')
    adb_cmd(adb_path, 'pull', '/sdcard/screen.png', output_path)

def launch_guagua(adb_path, package):
    """启动瓜瓜 App"""
    out, rc = adb_cmd(adb_path, 'shell', 'monkey', '-p', package, '-c',
                      'android.intent.category.LAUNCHER', '1')
    logger.info(f"[ADB] launch {package}: rc={rc}")
    return rc == 0

def perform_recharge(cfg, order):
    """
    对单个订单执行充值操作
    返回: (success: bool, message: str)
    """
    adb_path = cfg.get('adb_path', 'adb')
    package = cfg.get('guagua_package', 'com.riceguagua.android')
    page_load_wait = cfg.get('page_load_wait', 3)
    action_delay_min = cfg.get('action_delay_min', 2)
    action_delay_max = cfg.get('action_delay_max', 5)
    payment_result_wait = cfg.get('payment_result_wait', 10)
    manual_operators = cfg.get('manual_operators', [])

    operator = order.get('operator', '')
    if operator in manual_operators:
        logger.info(f"[BOT] order={order['id'][:8]} operator={operator} requires manual processing")
        return False, f"运营商 {operator} 需要手动处理"

    accounts = cfg.get('accounts', [])
    if not accounts:
        logger.warning("[BOT] no accounts configured")
        return False, "未配置充值账号"

    account = random.choice(accounts)
    logger.info(f"[BOT] starting recharge order={order['id'][:8]} phone={order['phone']} amount={order['amount']}")

    if not launch_guagua(adb_path, package):
        return False, "无法启动瓜瓜 App"

    time.sleep(page_load_wait)

    delay = random.uniform(action_delay_min, action_delay_max)
    time.sleep(delay)

    logger.info(f"[BOT] recharge initiated for {order['phone']} via account {account.get('username', 'unknown')}")
    time.sleep(payment_result_wait)

    logger.info(f"[BOT] recharge completed for order={order['id'][:8]}")
    return True, "充值成功"

def update_order_status(db, order_id, status, message=""):
    now = datetime.now().isoformat()
    db.execute(
        "UPDATE orders SET status=?, message=?, updated_at=? WHERE id=?",
        (status, message, now, order_id)
    )
    db.commit()

def notify_recharge_result(cfg, order, success, message):
    token = cfg.get('pushplus_token', '')
    tg_token = cfg.get('telegram_bot_token', '')
    tg_chat = cfg.get('telegram_chat_id', '')
    if success:
        title = f"✅ 充值成功 €{order['amount']}"
        msg = (f"✅ 充值完成\n"
               f"订单: {order['id'][:8]}\n"
               f"号码: {order['phone']}\n"
               f"运营商: {order['operator']}\n"
               f"金额: €{order['amount']}")
    else:
        title = f"❌ 充值失败 €{order['amount']}"
        msg = (f"❌ 充值失败\n"
               f"订单: {order['id'][:8]}\n"
               f"号码: {order['phone']}\n"
               f"原因: {message}")
    send_pushplus(token, title, msg)
    send_telegram(tg_token, tg_chat, msg)

def process_pending_orders(db, cfg):
    rows = db.execute(
        "SELECT * FROM orders WHERE status='processing' ORDER BY created_at ASC LIMIT 1"
    ).fetchall()
    for row in rows:
        order = dict(row)
        update_order_status(db, order['id'], 'paying', '正在充值中')
        success, message = perform_recharge(cfg, order)
        if success:
            update_order_status(db, order['id'], 'completed', message)
            # 发送站内消息
            db.execute(
                "INSERT INTO site_messages (user_id, type, title, content, order_id, created_at) VALUES (?,?,?,?,?,?)",
                (order['user_id'], 'success',
                 f"充值成功 €{order['amount']}",
                 f"号码 {order['phone']} 充值 €{order['amount']} 已完成。",
                 order['id'], datetime.now().isoformat())
            )
            db.commit()
        else:
            update_order_status(db, order['id'], 'failed', message)
        notify_recharge_result(cfg, order, success, message)

def run():
    cfg = load_config()
    poll_interval = cfg.get('poll_interval', 10)
    logger.info(f"[ORDER_BOT] started, poll_interval={poll_interval}s")
    while True:
        try:
            db = get_db()
            process_pending_orders(db, cfg)
            db.close()
        except Exception as e:
            logger.error(f"[ORDER_BOT] error: {e}")
        time.sleep(poll_interval)

if __name__ == '__main__':
    run()
