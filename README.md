# VeloceVoce 惟落雀 - 意大利手机充值平台

意大利手机话费充值平台，面向在意华人及相关用户，支持 TIM、Vodafone、WindTre、Iliad 等主流运营商。

## 技术栈

- **后端**：Python + FastAPI + SQLite
- **前端**：原生 HTML / CSS / JavaScript
- **自动化**：ADB + 瓜瓜充值 App（order_bot.py）
- **通知**：Telegram Bot、PushPlus、腾讯云短信

## 文件结构

```
.
├── server.py          # FastAPI 主服务
├── dispatcher.py      # 订单状态调度器
├── order_bot.py       # 充值自动化机器人
├── payment_bot.py     # 付款提醒机器人
├── bot_config.json    # 机器人配置（需填写实际 token/密钥）
├── requirements.txt   # Python 依赖
├── index.html         # 用户主页
├── app.js             # 前端应用逻辑
├── style.css          # 样式（暗色主题 + 金色 accent）
├── admin.html         # 管理后台
├── help.html          # 帮助中心
├── cookies.html       # Cookie 政策
├── legal.html         # 法律信息
├── privacy.html       # 隐私政策
└── terms.html         # 服务条款
```

## 快速启动

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python server.py
```

- 用户页面：http://localhost:8000
- 管理后台：http://localhost:8000/admin

### 配置

1. 复制 `bot_config.json`，填入实际的 token 和密钥（详见文件内注释）
2. 通过环境变量设置管理员密码（默认仅用于本地开发）：

```bash
export RECHARGE_ADMIN_PWD=your_secure_password
```

3. 其他可选环境变量：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`SMS_SECRET_ID`、`SMS_SECRET_KEY` 等

### 运行调度器和机器人（可选）

```bash
python dispatcher.py   # 订单状态调度
python order_bot.py    # 充值自动化（需 ADB 环境）
python payment_bot.py  # 付款提醒
```

## 注意事项

- `bot_config.json` 中的所有 token 和密钥均已清空，**部署前必须填写**
- 管理员密码请通过环境变量 `RECHARGE_ADMIN_PWD` 配置
- P.IVA 税号为占位符，**上线前请替换为实际注册税号**
