import argparse
import os
import time

from flask import Flask, jsonify, request, send_file, send_from_directory

from Scripts.MultiUserService import MultiUserService
from Scripts.Utils import YUKETANG_SERVERS

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WEB_DIST_DIR = os.path.join(BASE_DIR, "WebUI", "dist")
WEB_INDEX_FILE = os.path.join(WEB_DIST_DIR, "index.html")

service = MultiUserService()


def create_app():
    app = Flask(__name__, static_folder=WEB_DIST_DIR, static_url_path="/web")

    def _frontend_not_ready():
        return jsonify(
            {
                "ok": False,
                "message": "前端构建产物不存在，请先执行: cd WebUI-vite && npm install && npm run build",
            }
        ), 503

    @app.get("/")
    def index_page():
        if not os.path.exists(WEB_INDEX_FILE):
            return _frontend_not_ready()
        return send_from_directory(WEB_DIST_DIR, "index.html")

    @app.get("/web/<path:filename>")
    def web_assets(filename):
        if not os.path.exists(WEB_INDEX_FILE):
            return _frontend_not_ready()
        return send_from_directory(WEB_DIST_DIR, filename)

    @app.get("/api/meta")
    def api_meta():
        return jsonify(
            {
                "servers": [
                    {
                        "key": key,
                        "name": item.get("name", key),
                        "host": item.get("host", ""),
                    }
                    for key, item in YUKETANG_SERVERS.items()
                ]
            }
        )

    @app.get("/api/system/overview")
    def api_system_overview():
        return jsonify({"ok": True, "overview": service.get_overview()})

    @app.get("/api/config/default")
    def api_default_config():
        return jsonify({"ok": True, "config": service.get_default_config()})

    @app.put("/api/config/default")
    def api_update_default_config():
        payload = request.get_json(silent=True) or {}
        ok, msg = service.update_default_config(payload)
        return jsonify({"ok": ok, "message": msg, "config": service.get_default_config()})

    @app.get("/api/users")
    def api_users():
        users = service.list_users()
        return jsonify({"users": users})

    @app.get("/api/users/<user_id>/runtime")
    def api_user_runtime(user_id):
        user = service.get_user(user_id)
        if not user:
            return jsonify({"ok": False, "message": "用户不存在"}), 404
        runtime = service.get_user_runtime(user_id)
        return jsonify({"ok": True, "runtime": runtime})

    @app.get("/api/users/<user_id>/logs")
    def api_user_logs(user_id):
        limit_raw = request.args.get("limit", "200")
        keyword = request.args.get("keyword", "")
        types_raw = request.args.get("types", "")
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 200

        message_types = []
        for item in str(types_raw or "").split(","):
            text = item.strip()
            if not text:
                continue
            try:
                message_types.append(int(text))
            except Exception:
                continue

        logs = service.get_user_logs(user_id=user_id, limit=limit, message_types=message_types, keyword=keyword)
        if logs is None:
            return jsonify({"ok": False, "message": "用户不存在"}), 404
        return jsonify({"ok": True, "logs": logs, "is_active": service.is_user_active(user_id)})

    @app.post("/api/users")
    def api_create_user():
        payload = request.get_json(silent=True) or {}
        name = payload.get("name") or "新用户"
        server = payload.get("server")
        user = service.create_user(name=name, server=server)
        return jsonify({"ok": True, "user": user})

    @app.delete("/api/users/<user_id>")
    def api_delete_user(user_id):
        ok = service.delete_user(user_id)
        return jsonify({"ok": ok})

    @app.put("/api/users/<user_id>/profile")
    def api_update_profile(user_id):
        payload = request.get_json(silent=True) or {}
        ok, msg = service.update_user_profile(
            user_id=user_id,
            name=payload.get("name"),
            enabled=payload.get("enabled"),
            auto_schedule=payload.get("auto_schedule"),
            server=payload.get("server"),
        )
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.put("/api/users/<user_id>/config")
    def api_update_config(user_id):
        payload = request.get_json(silent=True) or {}
        ok, msg = service.update_user_config(user_id=user_id, config_patch=payload)
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.put("/api/users/<user_id>/config/mode")
    def api_update_config_mode(user_id):
        payload = request.get_json(silent=True) or {}
        use_custom_config = bool(payload.get("use_custom_config", False))
        clear_overrides = bool(payload.get("clear_overrides", False))
        ok, msg = service.update_user_config_mode(
            user_id=user_id,
            use_custom_config=use_custom_config,
            clear_overrides=clear_overrides,
        )
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.put("/api/users/<user_id>/schedule")
    def api_update_schedule(user_id):
        payload = request.get_json(silent=True) or {}
        schedule = payload.get("schedule", [])
        ok, msg = service.update_user_schedule(user_id=user_id, schedule_items=schedule)
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.post("/api/users/<user_id>/session")
    def api_set_session(user_id):
        payload = request.get_json(silent=True) or {}
        sessionid = payload.get("sessionid", "")
        ok, msg = service.set_user_sessionid(user_id, sessionid)
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.get("/api/users/<user_id>/check-login")
    def api_check_login(user_id):
        ok, msg = service.validate_user_login(user_id)
        return jsonify({"ok": ok, "message": msg})

    @app.post("/api/users/<user_id>/start")
    def api_start_monitor(user_id):
        ok, msg = service.start_user_monitor(user_id, reason="manual-web")
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.post("/api/users/<user_id>/stop")
    def api_stop_monitor(user_id):
        ok, msg = service.stop_user_monitor(user_id, reason="manual-web")
        return jsonify({"ok": ok, "message": msg, "user": service.get_user(user_id)})

    @app.post("/api/users/<user_id>/login/start")
    def api_login_start(user_id):
        ok, msg = service.start_login(user_id)
        state = service.get_login_state(user_id)
        return jsonify({"ok": ok, "message": msg, "state": state})

    @app.get("/api/users/<user_id>/login/state")
    def api_login_state(user_id):
        state = service.get_login_state(user_id)
        return jsonify({"ok": True, "state": state})

    @app.post("/api/users/<user_id>/login/cancel")
    def api_login_cancel(user_id):
        ok, state = service.cancel_login(user_id)
        return jsonify({"ok": ok, "state": state})

    @app.get("/api/users/<user_id>/ppt/current")
    def api_current_ppt(user_id):
        user = service.get_user(user_id)
        if not user:
            return jsonify({"ok": False, "message": "用户不存在"}), 404
        ppt = user.get("current_ppt", {})
        image_path = ppt.get("image_path", "")
        if not image_path or not os.path.exists(image_path):
            return jsonify({"ok": True, "exists": False, "info": ppt.get("info_text", "")})
        return jsonify(
            {
                "ok": True,
                "exists": True,
                "info": ppt.get("info_text", ""),
                "image_url": f"/api/users/{user_id}/ppt/image",
            }
        )

    @app.get("/api/users/<user_id>/ppt/image")
    def api_current_ppt_image(user_id):
        user = service.get_user(user_id)
        if not user:
            return jsonify({"ok": False, "message": "用户不存在"}), 404
        ppt = user.get("current_ppt", {})
        image_path = ppt.get("image_path", "")
        if not image_path or not os.path.exists(image_path):
            return jsonify({"ok": False, "message": "暂无图片"}), 404
        return send_file(image_path)

    @app.get("/api/users/<user_id>/problems")
    def api_problems(user_id):
        user = service.get_user(user_id)
        if not user:
            return jsonify({"ok": False, "message": "用户不存在"}), 404
        problems = user.get("problems", [])
        return jsonify({"ok": True, "problems": problems})

    return app


def run_terminal_login(user_id, timeout_seconds):
    ok, msg = service.start_login(user_id)
    if not ok:
        print(f"启动扫码失败: {msg}")
        return 1

    print("请使用微信扫码（终端二维码会在收到 ticket 后显示）")
    printed_ts = 0
    started = time.time()

    while True:
        if timeout_seconds > 0 and time.time() - started > timeout_seconds:
            service.cancel_login(user_id)
            print("扫码超时，已取消。")
            return 2

        state = service.get_login_state(user_id)
        status = state.get("status")
        updated_at = state.get("updated_at") or 0

        if status == "success":
            print("扫码登录成功，session 已写入用户配置。")
            return 0
        if status == "error":
            print(f"扫码失败: {state.get('error', '')}")
            return 3

        if updated_at and updated_at != printed_ts:
            printed_ts = updated_at
            qr_ascii = state.get("qr_ascii", "")
            if qr_ascii:
                print("\n" + qr_ascii + "\n")
                print("如果二维码过期会自动刷新。")

        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="RainClassroomAssistant Linux/Web 后台服务")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="启动 WebUI 与后台调度")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=18080)

    add_user_parser = subparsers.add_parser("add-user", help="创建用户")
    add_user_parser.add_argument("--name", required=True)
    add_user_parser.add_argument("--server", default="changjiang")

    list_user_parser = subparsers.add_parser("list-users", help="列出用户")
    _ = list_user_parser

    logs_parser = subparsers.add_parser("logs", help="查看用户运行日志")
    logs_parser.add_argument("--user", required=True)
    logs_parser.add_argument("--limit", type=int, default=120)
    logs_parser.add_argument("--keyword", default="")
    logs_parser.add_argument("--types", default="", help="按消息类型筛选，逗号分隔，例如 7,4")

    login_parser = subparsers.add_parser("terminal-login", help="终端二维码扫码登录")
    login_parser.add_argument("--user", required=True)
    login_parser.add_argument("--timeout", type=int, default=240)

    args = parser.parse_args()
    command = args.command or "serve"

    if command == "add-user":
        user = service.create_user(name=args.name, server=args.server)
        print(jsonify_safe(user))
        return

    if command == "list-users":
        users = service.list_users()
        print(jsonify_safe(users))
        return

    if command == "terminal-login":
        exit_code = run_terminal_login(user_id=args.user, timeout_seconds=args.timeout)
        raise SystemExit(exit_code)

    if command == "logs":
        msg_types = []
        for item in str(args.types or "").split(","):
            text = item.strip()
            if not text:
                continue
            try:
                msg_types.append(int(text))
            except Exception:
                continue
        rows = service.get_user_logs(
            user_id=args.user,
            limit=args.limit,
            message_types=msg_types,
            keyword=args.keyword,
        )
        if rows is None:
            print("用户不存在")
            raise SystemExit(1)
        print(jsonify_safe(rows))
        return

    app = create_app()
    service.start()
    try:
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        service.stop()


def jsonify_safe(data):
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
