import os
import datetime
import logging
import jwt  # type: ignore
from flask import Blueprint, jsonify, request
try:
    from flask_bcrypt import Bcrypt  # type: ignore
except Exception:  # 运行时兜底，若未安装也可使用明文
    Bcrypt = None  # type: ignore

auth_bp = Blueprint("auth_bp", __name__, url_prefix="/api/auth")

# 首次启动时，如果没有密码哈希与环境密码，则生成一次性随机密码并打印到日志
try:
    from config import config_manager
    _auth_conf = (config_manager.get() or {}).get("auth", {})
    if not _auth_conf.get("password_hash") and not os.getenv(
            "AUTH_PASSWORD_HASH", "") and not os.getenv("AUTH_PASSWORD", ""):
        import secrets, string
        _alphabet = string.ascii_letters + string.digits
        _random_pw = ''.join(secrets.choice(_alphabet) for _ in range(12))
        os.environ["AUTH_PASSWORD"] = _random_pw
        logging.warning("首次启动未检测到密码，已生成临时登录密码（请尽快修改）：%s", _random_pw)
        logging.warning("默认用户名：admin；登录后请前往 账户 设置中修改用户名与密码。")
except Exception as _e:
    logging.error("初始化临时密码时发生错误: %s", _e)


def _get_bcrypt(app=None):
    # 延迟创建，避免循环导入；若未安装则抛错
    if Bcrypt is None:  # type: ignore
        raise RuntimeError("Flask-Bcrypt 未安装，无法校验哈希密码。")
    return Bcrypt(app) if app is not None else Bcrypt()


def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if secret:
        return secret
    
    # 如果没有设置JWT_SECRET，使用基于用户名和密码的动态密钥
    # 这样每次重启或配置变更后密钥会变化，强制重新登录
    from config import config_manager
    import hashlib
    
    auth_conf = (config_manager.get() or {}).get("auth", {})
    username = auth_conf.get("username") or os.getenv("AUTH_USERNAME", "admin")
    password_hash = auth_conf.get("password_hash") or os.getenv("AUTH_PASSWORD_HASH", "")
    password_plain = os.getenv("AUTH_PASSWORD", "")
    
    # 创建基于认证信息的动态密钥
    auth_info = f"{username}:{password_hash or password_plain}"
    dynamic_secret = hashlib.sha256(auth_info.encode()).hexdigest()
    
    logging.info("使用基于认证信息的动态JWT密钥（重启后需要重新登录）")
    return dynamic_secret


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    # 优先使用配置文件中的凭据，其次回退到环境变量
    from config import config_manager
    auth_conf = (config_manager.get() or {}).get("auth", {})
    conf_user = auth_conf.get("username") or os.getenv("AUTH_USERNAME",
                                                       "admin")
    conf_hash = auth_conf.get("password_hash") or os.getenv(
        "AUTH_PASSWORD_HASH", "")
    conf_plain = os.getenv("AUTH_PASSWORD", "") if not conf_hash else ""

    if username != conf_user:
        return jsonify({"success": False, "message": "用户名或密码错误"}), 401

    # 校验密码：优先使用哈希
    if conf_hash and Bcrypt is not None:
        bcrypt = _get_bcrypt()
        if not bcrypt.check_password_hash(conf_hash, password):  # type: ignore
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401
    else:
        if not conf_plain or conf_plain != password:
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401

    payload = {
        "sub":
        username,
        "iat":
        int(datetime.datetime.utcnow().timestamp()),
        "exp":
        int((datetime.datetime.utcnow() +
             datetime.timedelta(days=7)).timestamp()),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")

    # 判断是否使用临时密码（没有配置文件中的密码哈希，只有环境变量密码）
    is_temp_password = not conf_hash and bool(conf_plain)
    
    return jsonify({
        "success": True, 
        "token": token,
        "is_temp_password": is_temp_password,
        "must_change_password": is_temp_password or auth_conf.get("must_change_password", False)
    })


@auth_bp.route("/status", methods=["GET"])
def auth_status():
    from config import config_manager
    auth_conf = (config_manager.get() or {}).get("auth", {})
    return jsonify({
        "success":
        True,
        "username":
        auth_conf.get("username", "admin"),
        "must_change_password":
        bool(auth_conf.get("must_change_password", True))
    })


@auth_bp.route("/change_password", methods=["POST"])
def change_password():
    if Bcrypt is None:
        return jsonify({
            "success": False,
            "message": "服务器未安装 bcrypt，无法修改密码"
        }), 500
    data = request.get_json(silent=True) or {}
    new_username = (data.get("username") or "").strip() or "admin"
    new_password = data.get("password") or ""
    old_password = data.get("old_password") or ""
    if len(new_password) < 6:
        return jsonify({"success": False, "message": "密码至少 6 位"}), 400

    from config import config_manager
    conf = config_manager.get()
    bcrypt = _get_bcrypt()

    # 校验旧密码
    auth_conf = (conf or {}).get("auth", {})
    current_hash = auth_conf.get("password_hash") or ""
    env_hash = os.getenv("AUTH_PASSWORD_HASH", "")
    env_plain = os.getenv("AUTH_PASSWORD", "")

    if current_hash:
        if not old_password or not bcrypt.check_password_hash(
                current_hash, old_password):  # type: ignore
            return jsonify({"success": False, "message": "当前密码不正确"}), 401
    else:
        # 无持久化哈希：允许使用环境变量中的明文或哈希进行一次性校验
        if env_hash:
            if not old_password or not bcrypt.check_password_hash(
                    env_hash, old_password):  # type: ignore
                return jsonify({"success": False, "message": "当前密码不正确"}), 401
        elif env_plain:
            if not old_password or old_password != env_plain:
                return jsonify({"success": False, "message": "当前密码不正确"}), 401
        else:
            # 同时没有哈希和环境密码（极少见），放行修改
            pass
    pw_hash = bcrypt.generate_password_hash(new_password).decode(
        "utf-8")  # type: ignore
    conf.setdefault("auth", {})
    conf["auth"]["username"] = new_username
    conf["auth"]["password_hash"] = pw_hash
    conf["auth"]["must_change_password"] = False
    if config_manager.save(conf):
        # 清除可能存在的临时密码
        if os.environ.get("AUTH_PASSWORD"):
            try:
                del os.environ["AUTH_PASSWORD"]
            except Exception:
                pass
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "保存失败"}), 500
