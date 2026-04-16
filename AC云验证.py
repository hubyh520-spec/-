# app.py - AC云验证平台 (完整修复版)

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import json
import time
import random
import os
import secrets
import smtplib
import hashlib
import hmac
import base64
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=7)
app.config['SESSION_PERMANENT'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 文件上传配置
UPLOAD_FOLDER = "user_uploads"
API_DOCS_FOLDER = "api_docs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs(API_DOCS_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# ====================== 数据库初始化 ======================
DB_FILES = {
    'users': 'data/users.json',
    'instances': 'data/instances.json',
    'cards': 'data/cards.json',
    'updates': 'data/updates.json',
    'traffic': 'data/traffic.json',
    'settings': 'data/settings.json',
    'announcement': 'data/announcement.json',
    'device_bind': 'data/device_bind.json',
    'login_logs': 'data/login_logs.json',
    'balance_logs': 'data/balance_logs.json',
    'sign_logs': 'data/sign_logs.json',
    'verify_code': 'data/verify_code.json',
    'visit_stats': 'data/visit_stats.json',
    'api_keys': 'data/api_keys.json'
}

for path in DB_FILES.values():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

# 默认设置
DEFAULT_SETTINGS = {
    "site_name": "AC云验证",
    "site_icon": "AC云验证",
    "currency_unit": "元",
    "currency_symbol": "¥",
    "default_balance": 0.00,
    "sign_reward": 0.28,
    "continuous_reward": 0.08,
    "normal_card_price": 0.05,
    "device_card_price": 0.05,
    "create_instance_price": 0.00,
    "month_price": 25.00,
    "season_price": 60.00,
    "half_year_price": 100.00,
    "year_price": 180.00,
    "traffic_1gb_price": 1.50,
    "traffic_10gb_price": 10.00,
    "traffic_30gb_price": 20.00,
    "traffic_100gb_price": 60.00,
    "traffic_500gb_price": 200.00,
    "normal_storage_mb": 100,
    "vip_storage_mb": 1024,
    "admin_account": "AC_ADMIN",
    "admin_password_hash": generate_password_hash("admin123"),
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "",
    "email_password": "",
    "upload_traffic_cost_per_mb": 1,
    "enable_encryption": True,
    "encryption_method": "base64",
    "sign_method": "md5"
}


def read_db(name):
    try:
        with open(DB_FILES[name], 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def save_db(name, data):
    with open(DB_FILES[name], 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_settings():
    settings = read_db('settings')
    if not settings:
        settings = DEFAULT_SETTINGS.copy()
        save_db('settings', settings)
    return settings


def save_settings(settings):
    save_db('settings', settings)


def get_user(user_id):
    users = read_db('users')
    return users.get(user_id)


def get_user_by_email(email):
    users = read_db('users')
    for uid, info in users.items():
        if info.get('email') == email:
            return uid, info
    return None, None


def add_balance(user_id, amount, reason, instance_id=None):
    users = read_db('users')
    if user_id not in users:
        return False
    users[user_id]['balance'] = round(users[user_id].get('balance', 0) + amount, 2)
    save_db('users', users)
    
    logs = read_db('balance_logs')
    if user_id not in logs:
        logs[user_id] = []
    logs[user_id].insert(0, {
        'name': reason,
        'amount': amount,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'balance': users[user_id]['balance'],
        'instance_id': instance_id
    })
    save_db('balance_logs', logs)
    return True


def deduct_balance(user_id, amount, reason, instance_id=None):
    users = read_db('users')
    if user_id not in users:
        return False
    if users[user_id].get('balance', 0) < amount:
        return False
    users[user_id]['balance'] = round(users[user_id]['balance'] - amount, 2)
    save_db('users', users)
    
    logs = read_db('balance_logs')
    if user_id not in logs:
        logs[user_id] = []
    logs[user_id].insert(0, {
        'name': reason,
        'amount': -amount,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'balance': users[user_id]['balance'],
        'instance_id': instance_id
    })
    save_db('balance_logs', logs)
    return True


def get_user_instances(user_id):
    instances = read_db('instances')
    return instances.get(user_id, [])


def save_user_instances(user_id, instance_list):
    all_instances = read_db('instances')
    all_instances[user_id] = instance_list
    save_db('instances', all_instances)


def check_vip(user_id):
    user = get_user(user_id)
    if user:
        vip_expire = user.get('vip_expire', 0)
        if vip_expire > time.time():
            remaining_days = int((vip_expire - time.time()) / 86400)
            return True, remaining_days
    return False, 0


def get_user_storage_used(user_id):
    user_folder = os.path.join(UPLOAD_FOLDER, user_id)
    if not os.path.exists(user_folder):
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(user_folder):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except:
                pass
    return total


def get_user_storage_limit(user_id):
    is_vip, _ = check_vip(user_id)
    settings = get_settings()
    if is_vip:
        return settings.get('vip_storage_mb', 1024) * 1024 * 1024
    return settings.get('normal_storage_mb', 100) * 1024 * 1024


def get_user_traffic(user_id):
    traffic_data = read_db('traffic')
    return traffic_data.get(user_id, {}).get('remaining_bytes', 0)


def add_traffic(user_id, gb, reason):
    traffic_data = read_db('traffic')
    if user_id not in traffic_data:
        traffic_data[user_id] = {'remaining_bytes': 0, 'logs': []}
    add_bytes = gb * 1024 * 1024 * 1024
    traffic_data[user_id]['remaining_bytes'] += add_bytes
    traffic_data[user_id]['logs'].insert(0, {
        'gb': gb,
        'reason': reason,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'remaining_gb': round(traffic_data[user_id]['remaining_bytes'] / (1024**3), 2)
    })
    save_db('traffic', traffic_data)
    return True


def deduct_traffic(user_id, need_bytes, reason):
    traffic_data = read_db('traffic')
    if user_id not in traffic_data:
        return False
    if traffic_data[user_id]['remaining_bytes'] < need_bytes:
        return False
    traffic_data[user_id]['remaining_bytes'] -= need_bytes
    traffic_data[user_id]['logs'].insert(0, {
        'gb': -need_bytes / (1024**3),
        'reason': reason,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'remaining_gb': round(traffic_data[user_id]['remaining_bytes'] / (1024**3), 2)
    })
    save_db('traffic', traffic_data)
    return True


def generate_card_password(prefix="", length=16):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    random_part = ''.join(random.choices(chars, k=length))
    if prefix:
        return f"{prefix}_{random_part}"
    return random_part


def get_instance_config(instance_id):
    """根据实例ID获取实例配置"""
    all_instances = read_db('instances')
    for user_id, instance_list in all_instances.items():
        for inst in instance_list:
            if inst.get('instance_id') == instance_id:
                return inst.get('config', {})
    return {}


def get_instance_by_id(instance_id):
    """获取实例完整信息"""
    all_instances = read_db('instances')
    for user_id, instance_list in all_instances.items():
        for inst in instance_list:
            if inst.get('instance_id') == instance_id:
                return inst, user_id
    return None, None


def check_instance_running(instance_id):
    """检查实例是否运行中"""
    inst, _ = get_instance_by_id(instance_id)
    if inst:
        return inst.get('status') == 'running'
    return False


def base64_encode(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.b64encode(data).decode()


def base64_decode(data):
    return base64.b64decode(data).decode()


def md5_sign(data, key):
    sign_str = f"{data}{key}"
    return hashlib.md5(sign_str.encode()).hexdigest()


def hmac_sha256_sign(data, key):
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()


def verify_sign(data, sign, key, method='md5'):
    if method == 'md5':
        return md5_sign(data, key) == sign
    elif method == 'hmac_sha256':
        return hmac_sha256_sign(data, key) == sign
    return False


def encrypt_request(raw_data, sign_key, method='base64', sign_method='md5'):
    """加密请求数据"""
    if isinstance(raw_data, dict):
        data_str = json.dumps(raw_data, ensure_ascii=False)
    else:
        data_str = str(raw_data)
    
    if method == 'base64':
        encoded_data = base64_encode(data_str)
    else:
        encoded_data = data_str
    
    sign = md5_sign(encoded_data, sign_key) if sign_method == 'md5' else hmac_sha256_sign(encoded_data, sign_key)
    
    return {
        'data': encoded_data,
        'sign': sign,
        'timestamp': int(time.time())
    }


def decrypt_response(encrypted_data, sign_key, method='base64', sign_method='md5'):
    """解密响应数据"""
    if not verify_sign(encrypted_data.get('data', ''), encrypted_data.get('sign', ''), sign_key, sign_method):
        raise Exception("签名验证失败")
    
    if method == 'base64':
        decoded_data = base64_decode(encrypted_data.get('data', ''))
    else:
        decoded_data = encrypted_data.get('data', '')
    
    return json.loads(decoded_data)


# ====================== 邮件发送 ======================
class EmailSender:
    @staticmethod
    def send_email(to_email, subject, html_content):
        settings = get_settings()
        if not settings.get('sender_email') or not settings.get('email_password'):
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = settings['sender_email']
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            server = smtplib.SMTP(settings['smtp_server'], settings['smtp_port'])
            server.starttls()
            server.login(settings['sender_email'], settings['email_password'])
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"邮件发送失败: {e}")
            return False
    
    @staticmethod
    def generate_code():
        return ''.join([str(random.randint(0, 9)) for _ in range(6)])
    
    @staticmethod
    def send_verify_code(email, purpose="register"):
        code = EmailSender.generate_code()
        codes = read_db('verify_code')
        key = f"{email}_{purpose}"
        codes[key] = {
            'code': code,
            'expire': time.time() + 300
        }
        save_db('verify_code', codes)
        
        if purpose == "register":
            subject = "AC云验证注册验证码"
            html = f"<h3>您的注册验证码是：{code}</h3><p>有效期为5分钟</p>"
        elif purpose == "reset":
            subject = "AC云验证重置密码验证码"
            html = f"<h3>您的重置密码验证码是：{code}</h3><p>有效期为5分钟</p>"
        else:
            return False
        return EmailSender.send_email(email, subject, html)
    
    @staticmethod
    def verify_code(email, code, purpose):
        codes = read_db('verify_code')
        key = f"{email}_{purpose}"
        if key not in codes:
            return False
        info = codes[key]
        if time.time() > info['expire']:
            del codes[key]
            save_db('verify_code', codes)
            return False
        if info['code'] != code:
            return False
        del codes[key]
        save_db('verify_code', codes)
        return True


email_sender = EmailSender()

# ====================== 装饰器 ======================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'code': 0, 'message': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            return jsonify({'code': 0, 'message': '需要管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated


def update_visit_stats():
    stats = read_db('visit_stats')
    today = datetime.now().strftime("%Y-%m-%d")
    if not stats:
        stats = {'total': 0, 'today': 0, 'last_date': today}
    if stats.get('last_date') != today:
        stats['today'] = 0
        stats['last_date'] = today
    stats['total'] = stats.get('total', 0) + 1
    stats['today'] = stats.get('today', 0) + 1
    save_db('visit_stats', stats)


# ====================== 路由 ======================
@app.route('/')
def index():
    update_visit_stats()
    stats = read_db('visit_stats')
    settings = get_settings()
    return render_template('首页.html', stats=stats, settings=settings)


@app.route('/login', methods=['GET', 'POST'])
def login():
    update_visit_stats()
    stats = read_db('visit_stats')
    settings = get_settings()
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == settings.get('admin_account') and check_password_hash(settings.get('admin_password_hash', ''), password):
            session['user_id'] = username
            session['role'] = 'admin'
            return redirect('/admin')
        
        user = get_user(username)
        if not user:
            uid, user = get_user_by_email(username)
        else:
            uid = username
        
        if user and check_password_hash(user.get('password_hash', ''), password):
            if user.get('is_banned'):
                return render_template('登录.html', error='账号已被封禁', stats=stats, settings=settings)
            session['user_id'] = uid
            session['role'] = 'user'
            logs = read_db('login_logs')
            if uid not in logs:
                logs[uid] = []
            logs[uid].insert(0, {
                'ip': request.remote_addr,
                'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_db('login_logs', logs)
            return redirect('/dashboard')
        
        return render_template('登录.html', error='用户名/邮箱或密码错误', stats=stats, settings=settings)
    
    return render_template('登录.html', stats=stats, settings=settings)


@app.route('/register', methods=['GET', 'POST'])
def register():
    update_visit_stats()
    stats = read_db('visit_stats')
    settings = get_settings()
    
    if request.method == 'POST':
        email = request.form.get('email')
        code = request.form.get('code')
        user_id = request.form.get('user_id')
        display_name = request.form.get('display_name')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([email, code, user_id, display_name, password]):
            return render_template('注册.html', error='请填写完整信息', stats=stats, settings=settings)
        
        if password != confirm_password:
            return render_template('注册.html', error='两次密码不一致', stats=stats, settings=settings)
        
        if len(password) < 6:
            return render_template('注册.html', error='密码至少6位', stats=stats, settings=settings)
        
        if not re.match(r'^[a-zA-Z0-9_]+$', user_id):
            return render_template('注册.html', error='用户ID只能包含字母、数字和下划线', stats=stats, settings=settings)
        
        if not email_sender.verify_code(email, code, "register"):
            return render_template('注册.html', error='验证码错误或已过期', stats=stats, settings=settings)
        
        users = read_db('users')
        if user_id in users:
            return render_template('注册.html', error='用户ID已存在', stats=stats, settings=settings)
        
        for existing_id, existing_user in users.items():
            if existing_user.get('email') == email:
                return render_template('注册.html', error='邮箱已被注册', stats=stats, settings=settings)
        
        users[user_id] = {
            'user_id': user_id,
            'display_name': display_name,
            'email': email,
            'password_hash': generate_password_hash(password),
            'balance': settings.get('default_balance', 0),
            'is_banned': False,
            'vip_expire': 0,
            'register_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'sign_info': {'continuous_days': 0, 'last_date': '', 'total_count': 0}
        }
        save_db('users', users)
        
        return render_template('注册.html', success='注册成功！请登录', stats=stats, settings=settings)
    
    return render_template('注册.html', stats=stats, settings=settings)


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    if session.get('role') == 'admin':
        return redirect('/admin')
    
    user_id = session['user_id']
    user = get_user(user_id)
    if not user or user.get('is_banned'):
        session.clear()
        return redirect('/login')
    
    settings = get_settings()
    instances = get_user_instances(user_id)
    is_vip, vip_days = check_vip(user_id)
    
    return render_template('用户中心.html', user=user, settings=settings, 
                           instances=instances, is_vip=is_vip, vip_days=vip_days)


@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    settings = get_settings()
    return render_template('管理后台.html', settings=settings)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ====================== 用户API ======================
@app.route('/api/user/info', methods=['GET'])
@login_required
def api_user_info():
    user_id = session['user_id']
    user = get_user(user_id)
    is_vip, vip_days = check_vip(user_id)
    return jsonify({
        'code': 1,
        'user_id': user_id,
        'display_name': user.get('display_name'),
        'email': user.get('email'),
        'balance': user.get('balance', 0),
        'is_vip': is_vip,
        'vip_days': vip_days,
        'vip_expire': user.get('vip_expire', 0)
    })


@app.route('/api/user/signin', methods=['POST'])
@login_required
def api_user_signin():
    user_id = session['user_id']
    user = get_user(user_id)
    settings = get_settings()
    today = datetime.now().strftime("%Y-%m-%d")
    
    sign_info = user.get('sign_info', {})
    if sign_info.get('last_date') == today:
        return jsonify({'code': 0, 'message': '今日已签到'})
    
    reward = settings.get('sign_reward', 0.28)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    if sign_info.get('last_date') == yesterday:
        sign_info['continuous_days'] = sign_info.get('continuous_days', 0) + 1
        reward += settings.get('continuous_reward', 0.08)
    else:
        sign_info['continuous_days'] = 1
    
    sign_info['last_date'] = today
    sign_info['total_count'] = sign_info.get('total_count', 0) + 1
    
    add_balance(user_id, reward, f'签到奖励(连续{sign_info["continuous_days"]}天)')
    user['sign_info'] = sign_info
    save_db('users', {user_id: user})
    
    return jsonify({'code': 1, 'reward': reward, 'balance': user['balance'], 'continuous_days': sign_info['continuous_days']})


@app.route('/api/user/balance/logs', methods=['GET'])
@login_required
def api_balance_logs():
    user_id = session['user_id']
    logs = read_db('balance_logs')
    return jsonify({'code': 1, 'logs': logs.get(user_id, [])})


@app.route('/api/user/login/logs', methods=['GET'])
@login_required
def api_login_logs():
    user_id = session['user_id']
    logs = read_db('login_logs')
    return jsonify({'code': 1, 'logs': logs.get(user_id, [])})


@app.route('/api/user/change_password', methods=['POST'])
@login_required
def api_change_password():
    user_id = session['user_id']
    data = request.json
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    user = get_user(user_id)
    if not check_password_hash(user.get('password_hash', ''), old_password):
        return jsonify({'code': 0, 'message': '原密码错误'})
    if len(new_password) < 6:
        return jsonify({'code': 0, 'message': '新密码至少6位'})
    
    user['password_hash'] = generate_password_hash(new_password)
    save_db('users', {user_id: user})
    return jsonify({'code': 1, 'message': '密码修改成功'})


@app.route('/api/user/update_name', methods=['POST'])
@login_required
def api_update_name():
    user_id = session['user_id']
    data = request.json
    display_name = data.get('display_name')
    
    if not display_name:
        return jsonify({'code': 0, 'message': '名称不能为空'})
    
    user = get_user(user_id)
    user['display_name'] = display_name
    save_db('users', {user_id: user})
    return jsonify({'code': 1, 'message': '名称修改成功'})


# ====================== 实例管理API ======================
@app.route('/api/instances', methods=['GET'])
@login_required
def api_get_instances():
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    return jsonify({'code': 1, 'instances': instances})


@app.route('/api/instances/create', methods=['POST'])
@login_required
def api_create_instance():
    user_id = session['user_id']
    data = request.json
    name = data.get('name')
    instance_id = data.get('instance_id')
    
    if not name or not instance_id:
        return jsonify({'code': 0, 'message': '请填写完整'})
    
    instances = get_user_instances(user_id)
    if any(inst.get('instance_id') == instance_id for inst in instances):
        return jsonify({'code': 0, 'message': '实例ID已存在'})
    
    settings = get_settings()
    price = settings.get('create_instance_price', 0)
    
    if price > 0:
        if not deduct_balance(user_id, price, f'创建应用 {name}', instance_id):
            return jsonify({'code': 0, 'message': f'余额不足，需要{price}元'})
    
    new_instance = {
        'name': name,
        'instance_id': instance_id,
        'status': 'stopped',
        'create_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'config': {
            'encryption_method': 'base64',
            'encryption_key': secrets.token_urlsafe(16),
            'sign_method': 'md5',
            'sign_key': secrets.token_urlsafe(16),
            'announcement': '',
            'current_version': ''
        }
    }
    instances.append(new_instance)
    save_user_instances(user_id, instances)
    
    return jsonify({'code': 1, 'message': '创建成功', 'balance': get_user(user_id).get('balance', 0)})


@app.route('/api/instances/<instance_id>/status', methods=['GET'])
@login_required
def api_instance_status(instance_id):
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    for inst in instances:
        if inst['instance_id'] == instance_id:
            return jsonify({'code': 1, 'status': inst.get('status', 'stopped')})
    return jsonify({'code': 0, 'message': '实例不存在'})


@app.route('/api/instances/<instance_id>/toggle', methods=['POST'])
@login_required
def api_toggle_instance(instance_id):
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    for inst in instances:
        if inst['instance_id'] == instance_id:
            inst['status'] = 'running' if inst.get('status') != 'running' else 'stopped'
            save_user_instances(user_id, instances)
            return jsonify({'code': 1, 'status': inst['status'], 'message': f'已{"启动" if inst["status"] == "running" else "停止"}'})
    return jsonify({'code': 0, 'message': '实例不存在'})


@app.route('/api/instances/<instance_id>/delete', methods=['DELETE'])
@login_required
def api_delete_instance(instance_id):
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    for i, inst in enumerate(instances):
        if inst['instance_id'] == instance_id:
            updates = read_db('updates')
            key = f"{user_id}_{instance_id}"
            if key in updates:
                for version, info in updates[key].items():
                    if os.path.exists(info.get('path', '')):
                        os.remove(info['path'])
                del updates[key]
                save_db('updates', updates)
            
            del instances[i]
            save_user_instances(user_id, instances)
            return jsonify({'code': 1, 'message': '删除成功'})
    return jsonify({'code': 0, 'message': '实例不存在'})


@app.route('/api/instances/<instance_id>/config', methods=['GET', 'POST'])
@login_required
def api_instance_config(instance_id):
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    for inst in instances:
        if inst['instance_id'] == instance_id:
            if request.method == 'GET':
                return jsonify({'code': 1, 'config': inst.get('config', {})})
            else:
                data = request.json
                if 'config' not in inst:
                    inst['config'] = {}
                inst['config'].update(data)
                save_user_instances(user_id, instances)
                return jsonify({'code': 1, 'message': '配置已保存'})
    return jsonify({'code': 0, 'message': '实例不存在'})


# ====================== 卡密管理API ======================
@app.route('/api/cards', methods=['GET'])
@login_required
def api_get_cards():
    user_id = session['user_id']
    all_cards = read_db('cards')
    user_cards = [card for card in all_cards.values() if card.get('owner') == user_id]
    return jsonify({'code': 1, 'cards': user_cards})


@app.route('/api/cards/create', methods=['POST'])
@login_required
def api_create_card():
    user_id = session['user_id']
    data = request.json
    instance_id = data.get('instance_id')
    card_type = data.get('card_type', 'normal')
    valid_days = data.get('valid_days', 1)
    prefix = data.get('prefix', '')
    custom_card = data.get('custom_card', '')
    quantity = data.get('quantity', 1)
    
    instances = get_user_instances(user_id)
    if not any(inst.get('instance_id') == instance_id for inst in instances):
        return jsonify({'code': 0, 'message': '实例不存在'})
    
    settings = get_settings()
    price = settings.get('normal_card_price' if card_type == 'normal' else 'device_card_price', 0.05)
    total_price = price * quantity
    
    if total_price > 0:
        if not deduct_balance(user_id, total_price, f'创建卡密 x{quantity}', instance_id):
            return jsonify({'code': 0, 'message': f'余额不足，需要{total_price}元'})
    
    all_cards = read_db('cards')
    created_cards = []
    
    for _ in range(quantity):
        if custom_card and quantity == 1:
            card_password = custom_card
        else:
            card_password = generate_card_password(prefix, 16 if not prefix else 8)
        
        while card_password in all_cards:
            card_password = generate_card_password(prefix, 16 if not prefix else 8)
        
        expire_time = time.time() + valid_days * 86400 if valid_days > 0 else 0
        
        all_cards[card_password] = {
            'card_password': card_password,
            'instance_id': instance_id,
            'owner': user_id,
            'type': card_type,
            'valid_days': valid_days,
            'used': False,
            'used_by': None,
            'bind_device': None,
            'create_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'expire_time': expire_time
        }
        created_cards.append(card_password)
    
    save_db('cards', all_cards)
    
    return jsonify({'code': 1, 'cards': created_cards, 'price': total_price, 'balance': get_user(user_id).get('balance', 0)})


@app.route('/api/cards/extend', methods=['POST'])
@login_required
def api_extend_card():
    user_id = session['user_id']
    data = request.json
    card_password = data.get('card_password')
    add_days = data.get('add_days', 0)
    
    all_cards = read_db('cards')
    card = all_cards.get(card_password)
    
    if not card or card.get('owner') != user_id:
        return jsonify({'code': 0, 'message': '卡密不存在'})
    
    card['valid_days'] += add_days
    if card['expire_time'] > 0:
        card['expire_time'] = (datetime.fromtimestamp(card['expire_time']) + timedelta(days=add_days)).timestamp()
    save_db('cards', all_cards)
    
    return jsonify({'code': 1, 'message': f'已增加{add_days}天，当前{card["valid_days"]}天'})


@app.route('/api/cards/unbind', methods=['POST'])
@login_required
def api_unbind_card():
    user_id = session['user_id']
    data = request.json
    card_password = data.get('card_password')
    
    all_cards = read_db('cards')
    card = all_cards.get(card_password)
    
    if not card or card.get('owner') != user_id:
        return jsonify({'code': 0, 'message': '卡密不存在'})
    
    if card['type'] != 'device':
        return jsonify({'code': 0, 'message': '只有设备卡可以解绑'})
    
    device_bind = read_db('device_bind')
    if card.get('bind_device') and card['bind_device'] in device_bind:
        del device_bind[card['bind_device']]
        save_db('device_bind', device_bind)
    
    card['used'] = False
    card['used_by'] = None
    card['bind_device'] = None
    save_db('cards', all_cards)
    
    return jsonify({'code': 1, 'message': '解绑成功，卡密可重新使用'})


@app.route('/api/cards/delete', methods=['POST'])
@login_required
def api_delete_card():
    user_id = session['user_id']
    data = request.json
    card_password = data.get('card_password')
    
    all_cards = read_db('cards')
    card = all_cards.get(card_password)
    
    if not card or card.get('owner') != user_id:
        return jsonify({'code': 0, 'message': '卡密不存在'})
    
    del all_cards[card_password]
    save_db('cards', all_cards)
    
    return jsonify({'code': 1, 'message': '删除成功'})


# ====================== 云更新API ======================
@app.route('/api/updates/<instance_id>', methods=['GET'])
@login_required
def api_get_updates(instance_id):
    user_id = session['user_id']
    instances = get_user_instances(user_id)
    if not any(inst.get('instance_id') == instance_id for inst in instances):
        return jsonify({'code': 0, 'message': '实例不存在'})
    
    updates_data = read_db('updates')
    key = f"{user_id}_{instance_id}"
    file_list = []
    
    if key in updates_data:
        for version, info in updates_data[key].items():
            file_list.append({
                'version': version,
                'filename': info.get('filename'),
                'display_name': info.get('display_name', info.get('filename')),
                'size_mb': info.get('size_mb', 0),
                'upload_time': info.get('upload_time'),
                'update_desc': info.get('update_desc', '')
            })
    
    file_list.sort(key=lambda x: x['version'], reverse=True)
    
    used_bytes = get_user_storage_used(user_id)
    limit_bytes = get_user_storage_limit(user_id)
    is_vip, _ = check_vip(user_id)
    
    return jsonify({
        'code': 1,
        'files': file_list,
        'used_storage_mb': round(used_bytes / (1024*1024), 2),
        'limit_storage_mb': round(limit_bytes / (1024*1024), 2),
        'is_vip': is_vip,
        'current_version': file_list[0]['version'] if file_list else None
    })


@app.route('/api/updates/upload', methods=['POST'])
@login_required
def api_upload_update():
    user_id = session['user_id']
    instance_id = request.form.get('instance_id')
    version = request.form.get('version')
    display_name = request.form.get('display_name', '')
    update_desc = request.form.get('update_desc', '')
    file = request.files.get('file')
    
    if not all([instance_id, version, file]):
        return jsonify({'code': 0, 'message': '请填写完整'})
    
    instances = get_user_instances(user_id)
    instance = None
    for inst in instances:
        if inst.get('instance_id') == instance_id:
            instance = inst
            break
    
    if not instance:
        return jsonify({'code': 0, 'message': '实例不存在'})
    
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    used_bytes = get_user_storage_used(user_id)
    limit_bytes = get_user_storage_limit(user_id)
    
    if used_bytes + file_size > limit_bytes:
        return jsonify({'code': 0, 'message': f'存储空间不足，已用{used_bytes//(1024*1024)}MB，限制{limit_bytes//(1024*1024)}MB'})
    
    settings = get_settings()
    cost_mb = file_size / (1024 * 1024)
    cost_traffic_bytes = int(cost_mb * settings.get('upload_traffic_cost_per_mb', 1) * 1024 * 1024)
    
    if cost_traffic_bytes > 0:
        if not deduct_traffic(user_id, cost_traffic_bytes, f'上传更新 {instance_id} v{version}'):
            return jsonify({'code': 0, 'message': '流量不足，请充值'})
    
    user_folder = os.path.join(UPLOAD_FOLDER, user_id, instance_id)
    os.makedirs(user_folder, exist_ok=True)
    filename = secure_filename(file.filename)
    file_path = os.path.join(user_folder, filename)
    file.save(file_path)
    
    updates_data = read_db('updates')
    key = f"{user_id}_{instance_id}"
    if key not in updates_data:
        updates_data[key] = {}
    
    updates_data[key][version] = {
        'filename': filename,
        'display_name': display_name if display_name else filename,
        'version': version,
        'update_desc': update_desc,
        'size_mb': round(file_size / (1024*1024), 2),
        'upload_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'path': file_path
    }
    save_db('updates', updates_data)
    
    return jsonify({'code': 1, 'message': '上传成功', 'size_mb': round(file_size / (1024*1024), 2)})


@app.route('/api/updates/delete', methods=['POST'])
@login_required
def api_delete_update():
    user_id = session['user_id']
    data = request.json
    instance_id = data.get('instance_id')
    version = data.get('version')
    
    updates_data = read_db('updates')
    key = f"{user_id}_{instance_id}"
    
    if key not in updates_data or version not in updates_data[key]:
        return jsonify({'code': 0, 'message': '文件不存在'})
    
    info = updates_data[key][version]
    if os.path.exists(info.get('path', '')):
        os.remove(info['path'])
    
    del updates_data[key][version]
    if not updates_data[key]:
        del updates_data[key]
    save_db('updates', updates_data)
    
    return jsonify({'code': 1, 'message': '删除成功'})


@app.route('/api/updates/set_version', methods=['POST'])
@login_required
def api_set_current_version():
    user_id = session['user_id']
    data = request.json
    instance_id = data.get('instance_id')
    version = data.get('version')
    
    instances = get_user_instances(user_id)
    for inst in instances:
        if inst.get('instance_id') == instance_id:
            if 'config' not in inst:
                inst['config'] = {}
            inst['config']['current_version'] = version
            save_user_instances(user_id, instances)
            return jsonify({'code': 1, 'message': f'当前版本已设置为 {version}'})
    
    return jsonify({'code': 0, 'message': '实例不存在'})


# ====================== 流量管理API ======================
@app.route('/api/traffic/info', methods=['GET'])
@login_required
def api_traffic_info():
    user_id = session['user_id']
    remaining_bytes = get_user_traffic(user_id)
    remaining_gb = round(remaining_bytes / (1024**3), 2)
    return jsonify({'code': 1, 'remaining_gb': remaining_gb, 'remaining_bytes': remaining_bytes})


@app.route('/api/traffic/buy', methods=['POST'])
@login_required
def api_buy_traffic():
    user_id = session['user_id']
    data = request.json
    gb = data.get('gb', 1)
    
    settings = get_settings()
    if gb == 1:
        price = settings.get('traffic_1gb_price', 1.5)
    elif gb == 10:
        price = settings.get('traffic_10gb_price', 10)
    elif gb == 30:
        price = settings.get('traffic_30gb_price', 20)
    elif gb == 100:
        price = settings.get('traffic_100gb_price', 60)
    elif gb == 500:
        price = settings.get('traffic_500gb_price', 200)
    else:
        price = gb * settings.get('traffic_1gb_price', 1.5)
    
    if not deduct_balance(user_id, price, f'购买{gb}GB流量'):
        return jsonify({'code': 0, 'message': f'余额不足，需要{price}元'})
    
    add_traffic(user_id, gb, f'购买{gb}GB流量')
    remaining_gb = get_user_traffic(user_id) / (1024**3)
    
    return jsonify({'code': 1, 'message': f'成功购买{gb}GB流量', 'remaining_gb': round(remaining_gb, 2), 'balance': get_user(user_id).get('balance', 0)})


# ====================== VIP会员API ======================
@app.route('/api/vip/buy', methods=['POST'])
@login_required
def api_buy_vip():
    user_id = session['user_id']
    data = request.json
    months = data.get('months', 1)
    
    settings = get_settings()
    if months == 1:
        price = settings.get('month_price', 25)
    elif months == 3:
        price = settings.get('season_price', 60)
    elif months == 6:
        price = settings.get('half_year_price', 100)
    elif months == 12:
        price = settings.get('year_price', 180)
    else:
        return jsonify({'code': 0, 'message': '无效的时长'})
    
    if not deduct_balance(user_id, price, f'购买VIP {months}个月'):
        return jsonify({'code': 0, 'message': f'余额不足，需要{price}元'})
    
    user = get_user(user_id)
    current_expire = user.get('vip_expire', 0)
    if current_expire > time.time():
        new_expire = current_expire + months * 30 * 86400
    else:
        new_expire = time.time() + months * 30 * 86400
    
    user['vip_expire'] = new_expire
    save_db('users', {user_id: user})
    
    return jsonify({'code': 1, 'message': f'VIP购买成功，有效期至{datetime.fromtimestamp(new_expire).strftime("%Y-%m-%d")}', 'balance': user['balance']})


# ====================== C++对接API ======================
@app.route('/api/verify', methods=['POST'])
def api_verify_card():
    """卡密验证接口 - 供C++客户端调用"""
    data = request.json
    if not data:
        return jsonify({'code': 0, 'message': '参数错误'})
    
    settings = get_settings()
    
    # 处理加密请求
    if settings.get('enable_encryption', True) and 'data' in data and 'sign' in data:
        try:
            instance_id = data.get('instance_id')
            if not instance_id:
                instance_id = data.get('data', {}).get('instance_id')
            
            config = get_instance_config(instance_id)
            if not config:
                return jsonify({'code': 0, 'message': '实例不存在'})
            
            decrypted = decrypt_response(data, config.get('sign_key', ''), 
                                        config.get('encryption_method', 'base64'),
                                        config.get('sign_method', 'md5'))
            data = decrypted
        except Exception as e:
            return jsonify({'code': 0, 'message': f'解密失败: {str(e)}'})
    
    card_password = data.get('card_password')
    instance_id = data.get('instance_id')
    device_id = data.get('device_id', '')
    user_id = data.get('user_id', '')
    
    if not card_password or not instance_id:
        return jsonify({'code': 0, 'message': '缺少必要参数'})
    
    # 检查实例是否存在且运行中
    inst, inst_owner = get_instance_by_id(instance_id)
    if not inst:
        return jsonify({'code': 10003, 'message': '实例不存在'})
    
    if inst.get('status') != 'running':
        return jsonify({'code': 10004, 'message': '实例未运行'})
    
    all_cards = read_db('cards')
    card = all_cards.get(card_password)
    
    if not card:
        return jsonify({'code': 10002, 'message': '卡密不存在'})
    
    if card.get('instance_id') != instance_id:
        return jsonify({'code': 0, 'message': '卡密不属于此应用'})
    
    expire_time = card.get('expire_time', 0)
    if expire_time > 0 and expire_time < time.time():
        return jsonify({'code': 10001, 'message': '卡密已过期'})
    
    card_type = card.get('type', 'normal')
    
    if card_type == 'normal':
        if not card.get('used'):
            card['used'] = True
            card['used_by'] = user_id
            save_db('cards', all_cards)
        
        remaining_days = 0
        if expire_time > 0:
            remaining_days = max(0, int((expire_time - time.time()) / 86400))
        
        response_data = {
            'code': 1,
            'message': '验证成功',
            'card_type': 'normal',
            'valid_days': card.get('valid_days', 0),
            'remaining_days': remaining_days,
            'expire_time': expire_time
        }
        
        config = get_instance_config(instance_id)
        if settings.get('enable_encryption', True):
            return jsonify(encrypt_request(response_data, config.get('sign_key', ''), 
                                          config.get('encryption_method', 'base64'),
                                          config.get('sign_method', 'md5')))
        return jsonify(response_data)
    
    elif card_type == 'device':
        bind_device = card.get('bind_device')
        
        if bind_device is None:
            if not device_id:
                return jsonify({'code': 10011, 'message': '需要设备ID进行绑定'})
            
            card['bind_device'] = device_id
            card['used_by'] = user_id
            card['used'] = True
            save_db('cards', all_cards)
            
            device_bind = read_db('device_bind')
            device_bind[device_id] = {
                'card_password': card_password,
                'instance_id': instance_id,
                'bind_time': time.time(),
                'expire_time': expire_time
            }
            save_db('device_bind', device_bind)
            
            remaining_days = 0
            if expire_time > 0:
                remaining_days = max(0, int((expire_time - time.time()) / 86400))
            
            response_data = {
                'code': 1,
                'message': '设备绑定成功',
                'card_type': 'device',
                'first_bind': True,
                'valid_days': card.get('valid_days', 0),
                'remaining_days': remaining_days,
                'expire_time': expire_time
            }
            
            config = get_instance_config(instance_id)
            if settings.get('enable_encryption', True):
                return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                              config.get('encryption_method', 'base64'),
                                              config.get('sign_method', 'md5')))
            return jsonify(response_data)
        
        elif bind_device == device_id:
            remaining_days = 0
            if expire_time > 0:
                remaining_days = max(0, int((expire_time - time.time()) / 86400))
            
            response_data = {
                'code': 1,
                'message': f'验证成功，剩余{remaining_days}天',
                'card_type': 'device',
                'valid_days': card.get('valid_days', 0),
                'remaining_days': remaining_days,
                'expire_time': expire_time
            }
            
            config = get_instance_config(instance_id)
            if settings.get('enable_encryption', True):
                return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                              config.get('encryption_method', 'base64'),
                                              config.get('sign_method', 'md5')))
            return jsonify(response_data)
        
        else:
            return jsonify({'code': 10012, 'message': '设备卡已绑定其他设备'})
    
    return jsonify({'code': 0, 'message': '未知错误'})


@app.route('/api/check_update', methods=['POST'])
def api_check_update():
    """检查更新接口 - 供C++客户端调用"""
    data = request.json
    if not data:
        return jsonify({'code': 0, 'message': '参数错误'})
    
    settings = get_settings()
    
    if settings.get('enable_encryption', True) and 'data' in data and 'sign' in data:
        try:
            instance_id = data.get('instance_id')
            if not instance_id:
                instance_id = data.get('data', {}).get('instance_id')
            
            config = get_instance_config(instance_id)
            decrypted = decrypt_response(data, config.get('sign_key', ''),
                                        config.get('encryption_method', 'base64'),
                                        config.get('sign_method', 'md5'))
            data = decrypted
        except Exception as e:
            return jsonify({'code': 0, 'message': f'解密失败: {str(e)}'})
    
    user_id = data.get('user_id')
    instance_id = data.get('instance_id')
    current_version = data.get('current_version', '')
    
    if not user_id or not instance_id:
        return jsonify({'code': 0, 'message': '缺少必要参数'})
    
    updates_data = read_db('updates')
    key = f"{user_id}_{instance_id}"
    
    if key not in updates_data:
        response_data = {'code': 1, 'has_update': False}
        config = get_instance_config(instance_id)
        if settings.get('enable_encryption', True):
            return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                          config.get('encryption_method', 'base64'),
                                          config.get('sign_method', 'md5')))
        return jsonify(response_data)
    
    versions = sorted(updates_data[key].keys(), reverse=True)
    latest_version = versions[0] if versions else None
    
    if latest_version and (not current_version or current_version < latest_version):
        info = updates_data[key][latest_version]
        response_data = {
            'code': 1,
            'has_update': True,
            'version': latest_version,
            'display_name': info.get('display_name', info.get('filename')),
            'file_size_mb': info.get('size_mb', 0),
            'file_size_bytes': info.get('size_mb', 0) * 1024 * 1024,
            'update_desc': info.get('update_desc', ''),
            'download_url': f"/api/download/{user_id}/{instance_id}/{latest_version}"
        }
        
        config = get_instance_config(instance_id)
        if settings.get('enable_encryption', True):
            return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                          config.get('encryption_method', 'base64'),
                                          config.get('sign_method', 'md5')))
        return jsonify(response_data)
    
    response_data = {'code': 1, 'has_update': False}
    config = get_instance_config(instance_id)
    if settings.get('enable_encryption', True):
        return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                      config.get('encryption_method', 'base64'),
                                      config.get('sign_method', 'md5')))
    return jsonify(response_data)


@app.route('/api/download/<user_id>/<instance_id>/<version>')
def api_download(user_id, instance_id, version):
    """下载文件接口"""
    updates_data = read_db('updates')
    key = f"{user_id}_{instance_id}"
    
    if key not in updates_data or version not in updates_data[key]:
        return "文件不存在", 404
    
    info = updates_data[key][version]
    file_path = info.get('path')
    
    if not os.path.exists(file_path):
        return "文件不存在", 404
    
    file_size = os.path.getsize(file_path)
    
    if not deduct_traffic(user_id, file_size, f'下载更新 {instance_id} v{version}'):
        return "流量不足，请充值", 403
    
    return send_file(
        file_path, 
        as_attachment=True, 
        download_name=info.get('display_name', info.get('filename')),
        mimetype='application/octet-stream'
    )


@app.route('/api/get_announcement', methods=['POST'])
def api_get_announcement():
    """获取公告接口 - 供C++客户端调用"""
    data = request.json
    if not data:
        return jsonify({'code': 0, 'message': '参数错误'})
    
    settings = get_settings()
    
    # 处理加密请求
    if settings.get('enable_encryption', True) and 'data' in data and 'sign' in data:
        try:
            instance_id = data.get('instance_id')
            if not instance_id:
                instance_id = data.get('data', {}).get('instance_id')
            
            config = get_instance_config(instance_id)
            decrypted = decrypt_response(data, config.get('sign_key', ''),
                                        config.get('encryption_method', 'base64'),
                                        config.get('sign_method', 'md5'))
            data = decrypted
        except Exception as e:
            return jsonify({'code': 0, 'message': f'解密失败: {str(e)}'})
    
    instance_id = data.get('instance_id')
    user_id = data.get('user_id', '')
    
    # 获取实例配置中的公告
    config = get_instance_config(instance_id)
    announcement = config.get('announcement', '')
    
    response_data = {
        'code': 1,
        'announcement': announcement
    }
    
    if settings.get('enable_encryption', True):
        return jsonify(encrypt_request(response_data, config.get('sign_key', ''),
                                      config.get('encryption_method', 'base64'),
                                      config.get('sign_method', 'md5')))
    return jsonify(response_data)


@app.route('/api/get_config', methods=['POST'])
def api_get_config():
    """获取实例配置 - 供C++客户端调用"""
    data = request.json
    if not data:
        return jsonify({'code': 0, 'message': '参数错误'})
    
    settings = get_settings()
    instance_id = data.get('instance_id') or (data.get('data', {}).get('instance_id') if isinstance(data.get('data'), dict) else None)
    
    if not instance_id:
        return jsonify({'code': 0, 'message': '缺少实例ID'})
    
    config = get_instance_config(instance_id)
    
    response_data = {
        'code': 1,
        'encryption_method': config.get('encryption_method', 'base64'),
        'encryption_key': config.get('encryption_key', ''),
        'sign_method': config.get('sign_method', 'md5'),
        'sign_key': config.get('sign_key', ''),
        'current_version': config.get('current_version', ''),
        'enable_encryption': settings.get('enable_encryption', True)
    }
    
    return jsonify(response_data)


@app.route('/api/get_server_time', methods=['GET'])
def api_get_server_time():
    """获取服务器时间"""
    return jsonify({
        'code': 1,
        'server_time': int(time.time()),
        'server_time_str': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ====================== 管理员API ======================
@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def api_admin_stats():
    users = read_db('users')
    instances_data = read_db('instances')
    cards_data = read_db('cards')
    
    total_users = len(users)
    total_instances = sum(len(instances) for instances in instances_data.values())
    total_cards = len(cards_data)
    total_balance = sum(user.get('balance', 0) for user in users.values())
    vip_count = sum(1 for user in users.values() if user.get('vip_expire', 0) > time.time())
    
    return jsonify({
        'code': 1,
        'total_users': total_users,
        'total_instances': total_instances,
        'total_cards': total_cards,
        'total_balance': total_balance,
        'vip_count': vip_count
    })


@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_get_users():
    users = read_db('users')
    user_list = []
    for uid, info in users.items():
        user_list.append({
            'user_id': uid,
            'display_name': info.get('display_name'),
            'email': info.get('email'),
            'balance': info.get('balance', 0),
            'is_banned': info.get('is_banned', False),
            'is_vip': info.get('vip_expire', 0) > time.time(),
            'vip_expire': info.get('vip_expire', 0),
            'register_time': info.get('register_time')
        })
    return jsonify({'code': 1, 'users': user_list})


@app.route('/api/admin/user/ban', methods=['POST'])
@admin_required
def api_admin_ban_user():
    data = request.json
    user_id = data.get('user_id')
    users = read_db('users')
    if user_id in users:
        users[user_id]['is_banned'] = not users[user_id].get('is_banned', False)
        save_db('users', users)
        return jsonify({'code': 1, 'message': '操作成功'})
    return jsonify({'code': 0, 'message': '用户不存在'})


@app.route('/api/admin/user/add_balance', methods=['POST'])
@admin_required
def api_admin_add_balance():
    data = request.json
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    if add_balance(user_id, amount, '管理员充值'):
        return jsonify({'code': 1, 'message': f'已添加{amount}元'})
    return jsonify({'code': 0, 'message': '操作失败'})


@app.route('/api/admin/user/add_vip', methods=['POST'])
@admin_required
def api_admin_add_vip():
    data = request.json
    user_id = data.get('user_id')
    days = data.get('days', 30)
    users = read_db('users')
    if user_id in users:
        current = users[user_id].get('vip_expire', 0)
        if current > time.time():
            users[user_id]['vip_expire'] = current + days * 86400
        else:
            users[user_id]['vip_expire'] = time.time() + days * 86400
        save_db('users', users)
        return jsonify({'code': 1, 'message': f'已添加{days}天VIP'})
    return jsonify({'code': 0, 'message': '用户不存在'})


@app.route('/api/admin/user/add_traffic', methods=['POST'])
@admin_required
def api_admin_add_traffic():
    data = request.json
    user_id = data.get('user_id')
    gb = data.get('gb', 0)
    if add_traffic(user_id, gb, '管理员赠送'):
        return jsonify({'code': 1, 'message': f'已添加{gb}GB流量'})
    return jsonify({'code': 0, 'message': '操作失败'})


@app.route('/api/admin/settings', methods=['GET', 'POST'])
@admin_required
def api_admin_settings():
    if request.method == 'GET':
        settings = get_settings()
        settings['admin_password_hash'] = '***'
        settings['email_password'] = '***'
        return jsonify({'code': 1, **settings})
    
    data = request.json
    settings = get_settings()
    for key, value in data.items():
        if key not in ['admin_password_hash', 'email_password']:
            settings[key] = value
    save_settings(settings)
    return jsonify({'code': 1, 'message': '设置已保存'})


@app.route('/api/admin/all_instances', methods=['GET'])
@admin_required
def api_admin_all_instances():
    instances_data = read_db('instances')
    all_instances = []
    for user_id, instance_list in instances_data.items():
        for inst in instance_list:
            all_instances.append({
                'owner': user_id,
                'name': inst.get('name'),
                'instance_id': inst.get('instance_id'),
                'status': inst.get('status', 'stopped')
            })
    return jsonify({'code': 1, 'instances': all_instances})


@app.route('/api/admin/card_prices', methods=['POST'])
@admin_required
def api_admin_card_prices():
    data = request.json
    settings = get_settings()
    settings['normal_card_price'] = data.get('normal_card_price', 0.05)
    settings['device_card_price'] = data.get('device_card_price', 0.05)
    save_settings(settings)
    return jsonify({'code': 1, 'message': '卡密价格已更新'})


@app.route('/api/admin/encryption', methods=['GET', 'POST'])
@admin_required
def api_admin_encryption():
    if request.method == 'GET':
        settings = get_settings()
        return jsonify({
            'code': 1,
            'enable_encryption': settings.get('enable_encryption', True),
            'encryption_method': settings.get('encryption_method', 'base64'),
            'sign_method': settings.get('sign_method', 'md5')
        })
    
    data = request.json
    settings = get_settings()
    settings['enable_encryption'] = data.get('enable_encryption', True)
    settings['encryption_method'] = data.get('encryption_method', 'base64')
    settings['sign_method'] = data.get('sign_method', 'md5')
    save_settings(settings)
    return jsonify({'code': 1, 'message': '加密设置已保存'})


# ====================== 验证码API ======================
@app.route('/api/send_code', methods=['POST'])
def api_send_code():
    data = request.json
    email = data.get('email')
    purpose = data.get('purpose', 'register')
    
    if not email:
        return jsonify({'code': 0, 'message': '邮箱不能为空'})
    
    if email_sender.send_verify_code(email, purpose):
        return jsonify({'code': 1, 'message': '验证码已发送'})
    return jsonify({'code': 0, 'message': '发送失败，请检查SMTP配置'})


# ====================== API对接文档 ======================
@app.route('/api/docs')
def api_docs():
    settings = get_settings()
    return render_template('api_docs.html', settings=settings)


@app.route('/api/docs/download/<filename>')
def api_docs_download(filename):
    """下载API对接文档"""
    file_path = os.path.join(API_DOCS_FOLDER, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=filename)
    return "文件不存在", 404


@app.route('/api/admin/upload_doc', methods=['POST'])
@admin_required
def api_admin_upload_doc():
    """上传API对接文件"""
    file = request.files.get('file')
    if not file:
        return jsonify({'code': 0, 'message': '请选择文件'})
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(API_DOCS_FOLDER, filename)
    file.save(file_path)
    
    return jsonify({'code': 1, 'message': '上传成功', 'filename': filename})


@app.route('/api/admin/docs_list', methods=['GET'])
@admin_required
def api_admin_docs_list():
    """获取对接文档列表"""
    files = []
    for f in os.listdir(API_DOCS_FOLDER):
        if os.path.isfile(os.path.join(API_DOCS_FOLDER, f)):
            files.append({
                'name': f,
                'size': os.path.getsize(os.path.join(API_DOCS_FOLDER, f)),
                'url': f'/api/docs/download/{f}'
            })
    return jsonify({'code': 1, 'files': files})


# ====================== 启动服务器 ======================
if __name__ == '__main__':
    settings = get_settings()
    print("=" * 60)
    print(f"  {settings.get('site_name', 'AC云验证')} 启动成功！")
    print("=" * 60)
    print("  访问地址: http://127.0.0.1:10211")
    print(f"  管理员账号: {settings.get('admin_account', 'AC_ADMIN')} / admin123")
    print("=" * 60)
    print("  C++对接API接口:")
    print("    POST /api/verify           - 卡密验证")
    print("    POST /api/check_update     - 检查更新")
    print("    GET  /api/download/...     - 下载文件")
    print("    POST /api/get_announcement - 获取公告")
    print("    GET  /api/get_server_time  - 服务器时间")
    print("    POST /api/get_config       - 获取配置")
    print("    GET  /api/docs             - API对接文档")
    print("=" * 60)
    print("  加密传输配置:")
    print(f"    启用加密: {settings.get('enable_encryption', True)}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=10211, debug=False, threaded=True)