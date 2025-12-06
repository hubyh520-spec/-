from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
import json
import time
import random
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime  # 统一顶部导入

app = Flask(__name__)
app.secret_key = str(uuid.uuid4())  # 会话加密密钥

# 数据文件
ADMIN_DB = "admin_db.json"       # 管理员账号（仅1个）
CREATE_KEY_DB = "create_key_db.json"  # 一次性创建密钥
ACCOUNT_DB = "account_db.json"   # 用户账号
CARD_DB = "card_db.json"         # 用户卡密
NOTICE_DB = "notice_db.json"     # 公告存储

# 初始化数据库
def init_db(file_path, default_data=None):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default_data or {}

# 初始化默认数据
admin_db = init_db(ADMIN_DB, {"username": "admin", "password_hash": generate_password_hash("admin123")})
create_key_db = init_db(CREATE_KEY_DB)
account_db = init_db(ACCOUNT_DB)
card_db = init_db(CARD_DB)
notice_db = init_db(NOTICE_DB, {"content": "", "update_time": ""})

# 保存数据库
def save_db(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ------------------------------ 页面模板（新增自定义卡密/修改到期时间） ------------------------------
# 1. 管理员登录页（不变）
ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>管理员登录</title>
    <style>
        body { max-width: 400px; margin: 50px auto; font-family: Arial; }
        .container { border: 1px solid #ddd; padding: 25px; border-radius: 8px; }
        input { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 4px; }
        .btn { width: 100%; padding: 12px; background: #2196F3; color: white; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="container">
        <h2>管理员登录</h2>
        <input type="text" id="adminUser" placeholder="管理员账号" value="admin">
        <input type="password" id="adminPwd" placeholder="管理员密码">
        <button class="btn" onclick="adminLogin()">登录</button>
    </div>
    <script>
        async function adminLogin() {
            const user = document.getElementById('adminUser').value;
            const pwd = document.getElementById('adminPwd').value;
            const res = await fetch('/admin/login', {
                method: 'POST',
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({username: user, password: pwd})
            });
            if (res.status === 200) window.location.href = '/admin/dashboard';
            else alert('登录失败');
        }
    </script>
</body>
</html>
"""

# 2. 管理员后台（新增自定义卡密、修改到期时间功能）
ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>管理员后台</title>
    <style>
        body { max-width: 1200px; margin: 20px auto; font-family: Arial; }
        .key-item { padding: 10px; background: #f5f5f5; margin: 10px 0; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .btn { padding: 8px 15px; background: #4CAF50; color: white; border: none; border-radius: 3px; cursor: pointer; }
        .btn-notice { background: #2196F3; margin-left: 10px; }
        .btn-account { background: #FF9800; margin-left: 10px; }
        .btn-card { background: #9C27B0; margin-left: 10px; }
        .btn-add { background: #00BCD4; margin-left: 10px; }
        .btn-edit { background: #FFC107; color: #333; }
        .btn-delete { background: #F44336; }
        .btn-logout { background: #999; margin-left: 10px; }
        .tab { display: flex; margin-bottom: 20px; border-bottom: 1px solid #ddd; }
        .tab-btn { padding: 10px 20px; cursor: pointer; border: none; background: none; }
        .tab-btn.active { border-bottom: 2px solid #2196F3; color: #2196F3; font-weight: bold; }
        .panel { display: none; margin-top: 20px; }
        .panel.active { display: block; }
        .form-group { margin: 10px 0; }
        .form-group input { padding: 8px; margin-right: 10px; width: auto; }
    </style>
</head>
<body>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <h1>管理员后台</h1>
        <div>
            <button class="btn" onclick="generateCreateKey()">生成一次性创建密钥</button>
            <button class="btn btn-notice" onclick="window.location.href='/admin/notice_manage'">公告管理</button>
            <button class="btn btn-account" onclick="switchTab('account')">账号管理</button>
            <button class="btn btn-card" onclick="switchTab('card')">所有卡密管理</button>
            <button class="btn btn-add" onclick="showAddCardForm()">添加自定义卡密</button>
            <button class="btn btn-logout" onclick="logout()">退出</button>
        </div>
    </div>

    <!-- 自定义卡密添加表单（默认隐藏） -->
    <div id="addCardForm" style="display: none; border: 1px solid #ddd; padding: 20px; border-radius: 5px; margin-bottom: 20px;">
        <h3>添加自定义卡密</h3>
        <div class="form-group">
            <input type="text" id="customCardKey" placeholder="输入自定义卡密（如CARD-XXX）" required>
            <input type="text" id="customCardAccount" placeholder="所属账号（必须存在）" required>
            <input type="text" id="customCardType" placeholder="卡密类型" value="自定义卡密">
            <input type="date" id="customCardExpire" required>
            <button class="btn" onclick="addCustomCard()">确认添加</button>
            <button class="btn btn-delete" onclick="hideAddCardForm()">取消</button>
        </div>
    </div>

    <!-- 修改到期时间表单（默认隐藏） -->
    <div id="editExpireForm" style="display: none; border: 1px solid #ddd; padding: 20px; border-radius: 5px; margin-bottom: 20px;">
        <h3>修改卡密到期时间</h3>
        <div class="form-group">
            <input type="hidden" id="editCardKey">
            <span>卡密：<span id="editCardKeyDisplay"></span></span>
            <input type="date" id="newExpireDate" required>
            <button class="btn btn-edit" onclick="updateCardExpire()">确认修改</button>
            <button class="btn btn-delete" onclick="hideEditExpireForm()">取消</button>
        </div>
    </div>

    <!-- 标签页 -->
    <div class="tab">
        <button class="tab-btn active" onclick="switchTab('createKey')">创建密钥管理</button>
        <button class="tab-btn" onclick="switchTab('account')">已注册账号管理</button>
        <button class="tab-btn" onclick="switchTab('card')">所有卡密管理</button>
    </div>

    <!-- 创建密钥管理面板 -->
    <div id="createKey" class="panel active">
        <h3>可用创建密钥（未使用）</h3>
        <div id="availableKeys"></div>
        <h3>已使用创建密钥</h3>
        <div id="usedKeys"></div>
    </div>

    <!-- 已注册账号管理面板 -->
    <div id="account" class="panel">
        <h3>已注册账号列表（含密码哈希）</h3>
        <div id="accountList"></div>
    </div>

    <!-- 所有卡密管理面板 -->
    <div id="card" class="panel">
        <h3>所有卡密列表（支持修改到期时间/删除）</h3>
        <div id="allCardList"></div>
    </div>

    <script>
        // 切换标签页
        function switchTab(type) {
            document.querySelectorAll('.tab-btn').forEach(b 
