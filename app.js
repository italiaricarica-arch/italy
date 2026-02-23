/**
 * VeloceVoce 惟落雀 - 前端应用逻辑
 */

const API = '';
let token = localStorage.getItem('vv_token') || '';
let currentUser = null;
let selectedAmount = 0;

// ====== 初始化 ======

document.addEventListener('DOMContentLoaded', () => {
  if (token) {
    loadUser();
  }
  loadPromotions();
});

// ====== 用户状态 ======

async function loadUser() {
  try {
    const data = await apiFetch('/api/me');
    currentUser = data;
    showLoggedIn(data);
  } catch (e) {
    token = '';
    localStorage.removeItem('vv_token');
    showLoggedOut();
  }
}

function showLoggedIn(user) {
  document.getElementById('navGuest').classList.add('hidden');
  document.getElementById('navUser').classList.remove('hidden');
  document.getElementById('heroSection').classList.add('hidden');
  document.getElementById('creditOption').classList.remove('hidden');

  // 更新信用卡显示 (ID: smCreditCard)
  const smCreditCard = document.getElementById('smCreditCard');
  if (smCreditCard) {
    smCreditCard.textContent = `€${(user.credit_amount || 0).toFixed(2)}`;
  }

  // 更新消息铃铛 (ID: msgBell / msgBadge)
  const msgBadge = document.getElementById('msgBadge');
  if (msgBadge) {
    const count = user.unread_messages || 0;
    if (count > 0) {
      msgBadge.textContent = count > 99 ? '99+' : count;
      msgBadge.classList.remove('hidden');
    } else {
      msgBadge.classList.add('hidden');
    }
  }
}

function showLoggedOut() {
  document.getElementById('navGuest').classList.remove('hidden');
  document.getElementById('navUser').classList.add('hidden');
  document.getElementById('heroSection').classList.remove('hidden');
  document.getElementById('creditOption').classList.add('hidden');
  currentUser = null;
}

// ====== 认证弹窗 ======
// openAuth 只在此处定义，避免与 index.html 内联脚本重复定义

function openAuth(mode) {
  mode = mode || 'login';
  switchAuth(mode);
  document.getElementById('authModal').classList.add('active');
}

function closeAuth() {
  document.getElementById('authModal').classList.remove('active');
}

/**
 * switchAuth - 切换登录/注册 tab
 * 使用 authTitle (在 index.html 中已定义该元素)
 */
function switchAuth(mode) {
  const authTitle = document.getElementById('authTitle');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');

  if (mode === 'login') {
    if (authTitle) authTitle.textContent = '登录';
    loginForm.classList.remove('hidden');
    registerForm.classList.add('hidden');
    tabLogin.classList.add('active');
    tabRegister.classList.remove('active');
  } else {
    if (authTitle) authTitle.textContent = '注册';
    loginForm.classList.add('hidden');
    registerForm.classList.remove('hidden');
    tabLogin.classList.remove('active');
    tabRegister.classList.add('active');
  }
}

async function doLogin() {
  const account = document.getElementById('loginAccount').value.trim();
  const password = document.getElementById('loginPassword').value;
  if (!account || !password) {
    showToast('请填写账号和密码', 'error');
    return;
  }
  try {
    const data = await apiFetch('/api/login', 'POST', { account, password });
    token = data.token;
    localStorage.setItem('vv_token', token);
    closeAuth();
    showToast('登录成功', 'success');
    loadUser();
  } catch (e) {
    showToast(e.message || '登录失败', 'error');
  }
}

async function doRegister() {
  const email = document.getElementById('regEmail').value.trim();
  const password = document.getElementById('regPassword').value;
  const name = document.getElementById('regName').value.trim();
  if (!email || !password) {
    showToast('请填写邮箱和密码', 'error');
    return;
  }
  if (password.length < 6) {
    showToast('密码至少6位', 'error');
    return;
  }
  try {
    const data = await apiFetch('/api/register', 'POST', { email, password, name });
    token = data.token;
    localStorage.setItem('vv_token', token);
    closeAuth();
    showToast('注册成功！获得 €10 信用额度', 'success');
    loadUser();
  } catch (e) {
    showToast(e.message || '注册失败', 'error');
  }
}

async function doLogout() {
  try {
    await apiFetch('/api/logout', 'POST');
  } catch (_) {}
  token = '';
  localStorage.removeItem('vv_token');
  showLoggedOut();
  showSection('recharge');
  showToast('已退出登录', 'info');
}

// ====== 用户菜单 ======

function toggleUserMenu() {
  document.getElementById('userDropdown').classList.toggle('hidden');
}

function closeUserMenu() {
  document.getElementById('userDropdown').classList.add('hidden');
}

document.addEventListener('click', (e) => {
  const dd = document.getElementById('userDropdown');
  const btn = document.getElementById('btnUserMenu');
  if (dd && btn && !btn.contains(e.target) && !dd.contains(e.target)) {
    dd.classList.add('hidden');
  }
});

// ====== 充值 ======

function selectAmount(amount) {
  selectedAmount = amount;
  document.querySelectorAll('.amount-btn').forEach(btn => {
    btn.classList.toggle('selected', parseInt(btn.dataset.amount) === amount);
  });
}

async function loadPromotions() {
  try {
    const data = await apiFetch('/api/promotions');
    if (data.cny_active) {
      const bonuses = data.bonuses || {};
      document.querySelectorAll('.amount-btn').forEach(btn => {
        const amt = parseInt(btn.dataset.amount);
        const bonus = bonuses[String(amt)];
        const bonusEl = btn.querySelector('.bonus');
        if (bonus && bonusEl) {
          bonusEl.textContent = `+€${bonus}`;
          bonusEl.style.display = 'block';
        }
      });
    }
  } catch (_) {}
}

async function submitRecharge() {
  if (!currentUser) {
    openAuth('login');
    return;
  }
  const phone = document.getElementById('inputPhone').value.trim();
  const operator = document.getElementById('inputOperator').value;
  const isCredit = document.getElementById('chkCredit').checked;

  if (!phone) { showToast('请输入手机号', 'error'); return; }
  if (!operator) { showToast('请选择运营商', 'error'); return; }
  if (!selectedAmount) { showToast('请选择充值金额', 'error'); return; }

  const btn = document.getElementById('btnRecharge');
  btn.disabled = true;
  btn.textContent = '提交中...';

  try {
    const data = await apiFetch('/api/orders', 'POST', {
      phone, operator, amount: selectedAmount, is_credit: isCredit
    });
    showToast(`订单已提交！编号: ${data.order_id.substring(0, 8)}`, 'success');
    document.getElementById('inputPhone').value = '';
    document.getElementById('inputOperator').value = '';
    selectedAmount = 0;
    document.querySelectorAll('.amount-btn').forEach(b => b.classList.remove('selected'));
    document.getElementById('chkCredit').checked = false;
    loadUser();
  } catch (e) {
    showToast(e.message || '提交失败', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '确认充值';
  }
}

// ====== 板块切换 ======

function showSection(name) {
  document.getElementById('rechargeSection').classList.toggle('hidden', name !== 'recharge');
  document.getElementById('ordersSection').classList.toggle('hidden', name !== 'orders');
  document.getElementById('creditSection').classList.toggle('hidden', name !== 'credit');
  if (name === 'orders') loadOrders();
  if (name === 'credit') loadCreditInfo();
}

async function loadOrders() {
  const el = document.getElementById('orderList');
  if (!el) return;
  el.innerHTML = '<p class="text-muted">加载中...</p>';
  try {
    const data = await apiFetch('/api/orders');
    if (!data.orders || data.orders.length === 0) {
      el.innerHTML = '<p class="text-muted">暂无订单</p>';
      return;
    }
    el.innerHTML = data.orders.map(o => `
      <div class="order-item">
        <div>
          <div style="font-weight:600;">${o.phone} · ${o.operator}</div>
          <div class="text-muted" style="font-size:12px;">${o.created_at.substring(0, 16)}</div>
          ${o.message ? `<div class="text-muted" style="font-size:12px;">${o.message}</div>` : ''}
        </div>
        <div style="text-align:right;">
          <div style="font-size:18px;font-weight:700;color:#c9a84c;">€${o.amount}</div>
          <span class="order-status status-${o.status}">${statusLabel(o.status)}</span>
        </div>
      </div>
    `).join('');
  } catch (e) {
    el.innerHTML = '<p class="text-danger">加载失败</p>';
  }
}

async function loadCreditInfo() {
  try {
    const data = await apiFetch('/api/credit-info');
    document.getElementById('creditAmountDisplay').textContent = `€${(data.credit_amount || 0).toFixed(2)}`;
    document.getElementById('creditLevelDisplay').textContent =
      `信用等级: ${data.credit_level?.icon || ''} ${data.credit_level?.name || ''} · 积分: ${data.credit_score || 0}`;
    if (data.next_level) {
      document.getElementById('creditLevelsInfo').innerHTML =
        `<p class="text-muted">距下一等级「${data.next_level.name}」还需 ${data.next_level.min_score - data.credit_score} 积分</p>`;
    }
  } catch (_) {}
}

function statusLabel(s) {
  const map = {
    pending: '待处理', charged: '已收单', processing: '充值中',
    paying: '支付中', completed: '已完成', failed: '失败',
    cancelled: '已取消', awaiting_payment: '待付款', holding: '排队中'
  };
  return map[s] || s;
}

// ====== 消息通知 ======

function openMessages() {
  document.getElementById('messagesModal').classList.add('active');
  loadMessages();
}

function closeMessages() {
  document.getElementById('messagesModal').classList.remove('active');
}

async function loadMessages() {
  const el = document.getElementById('messageList');
  if (!el) return;
  el.innerHTML = '<p class="text-muted">加载中...</p>';
  try {
    const data = await apiFetch('/api/messages');
    if (!data.messages || data.messages.length === 0) {
      el.innerHTML = '<p class="text-muted">暂无消息</p>';
      return;
    }
    el.innerHTML = data.messages.map(m => `
      <div style="padding:12px;border-bottom:1px solid #333;">
        <div style="font-weight:600;color:${m.type === 'success' ? '#4caf50' : m.type === 'error' ? '#e05252' : '#c9a84c'};">${m.title}</div>
        ${m.content ? `<div class="text-muted" style="font-size:13px;margin-top:4px;">${m.content}</div>` : ''}
        <div class="text-muted" style="font-size:11px;margin-top:4px;">${m.created_at.substring(0, 16)}</div>
      </div>
    `).join('');
    // 消息已读，清除角标
    const msgBadge = document.getElementById('msgBadge');
    if (msgBadge) msgBadge.classList.add('hidden');
  } catch (_) {
    el.innerHTML = '<p class="text-danger">加载失败</p>';
  }
}

// ====== API 工具 ======

async function apiFetch(path, method, body) {
  method = method || 'GET';
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' }
  };
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.detail || `请求失败 (${res.status})`);
  return json;
}

// ====== Toast ======

function showToast(msg, type) {
  type = type || 'info';
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => el.classList.add('show'));
  });
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 350);
  }, 3500);
}
