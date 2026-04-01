import base64
import json
import threading
import time
from io import BytesIO

import requests
import websocket
from PIL import Image

from Scripts.Utils import build_server_url, dict_result


class QRLoginSession:
    def __init__(self, config, on_success=None, on_error=None):
        self.config = config
        self.on_success = on_success
        self.on_error = on_error

        self._lock = threading.Lock()
        self._refresh_running = False
        self._closed = False

        self.status = "pending"
        self.error = ""
        self.sessionid = ""
        self.qr_image_bytes = b""
        self.updated_at = 0.0

        self.wsapp = None
        self.ws_thread = None
        self.refresh_thread = None

    def start(self):
        with self._lock:
            if self.ws_thread and self.ws_thread.is_alive():
                return

        def on_open(wsapp):
            self._send_request_login(wsapp)

        def on_message(wsapp, message):
            try:
                data = dict_result(message)
            except Exception:
                return

            op = data.get("op")
            if op == "requestlogin":
                ticket = data.get("ticket")
                if ticket:
                    self._update_qr(ticket)
            elif op == "loginsuccess":
                user_id = data.get("UserID")
                auth = data.get("Auth")
                if not user_id or not auth:
                    self._set_error("扫码成功但缺少 UserID/Auth")
                    return
                self._complete_login(user_id, auth)

        def on_error(_wsapp, error):
            self._set_error(f"登录 websocket 异常: {error}")

        def on_close(_wsapp, _code, _reason):
            # 非主动关闭且还未成功时保持 pending 状态，等待上层处理
            return

        login_wss_url = build_server_url("/wsapp/", self.config, ws=True)
        self.wsapp = websocket.WebSocketApp(
            url=login_wss_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        self.ws_thread = threading.Thread(target=self.wsapp.run_forever, daemon=True)
        self.ws_thread.start()

        self._refresh_running = True
        self.refresh_thread = threading.Thread(target=self._refresh_qr_loop, daemon=True)
        self.refresh_thread.start()

    def close(self):
        with self._lock:
            self._closed = True
            self._refresh_running = False
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass

    def _send_request_login(self, wsapp):
        payload = {
            "op": "requestlogin",
            "role": "web",
            "version": 1.4,
            "type": "qrcode",
            "from": "web",
        }
        try:
            wsapp.send(json.dumps(payload))
        except Exception:
            return

    def _refresh_qr_loop(self):
        elapsed = 0
        while True:
            with self._lock:
                if not self._refresh_running or self._closed:
                    break
                done = self.status in ("success", "error", "cancelled")
            if done:
                break

            if elapsed >= 60:
                elapsed = 0
                if self.wsapp:
                    self._send_request_login(self.wsapp)
            time.sleep(1)
            elapsed += 1

    def _update_qr(self, ticket_url):
        try:
            img = requests.get(
                url=ticket_url,
                proxies={"http": None, "https": None},
                timeout=10,
            ).content
        except Exception as exc:
            self._set_error(f"二维码下载失败: {exc}")
            return

        with self._lock:
            if self._closed:
                return
            self.qr_image_bytes = img
            self.updated_at = time.time()

    def _complete_login(self, user_id, auth):
        web_login_url = build_server_url("/pc/web_login", self.config)
        login_data = json.dumps({"UserID": user_id, "Auth": auth})
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:104.0) Gecko/20100101 Firefox/104.0",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url=web_login_url,
                data=login_data,
                headers=headers,
                proxies={"http": None, "https": None},
                timeout=10,
            )
            sessionid = dict(response.cookies).get("sessionid", "")
            if not sessionid:
                self._set_error("扫码成功但未获取到 sessionid")
                return
        except Exception as exc:
            self._set_error(f"扫码换取 session 失败: {exc}")
            return

        with self._lock:
            self.status = "success"
            self.sessionid = sessionid
            self.updated_at = time.time()
            self._refresh_running = False

        if self.on_success:
            try:
                self.on_success(sessionid)
            except Exception:
                pass

        self.close()

    def _set_error(self, message):
        with self._lock:
            if self.status == "success":
                return
            self.status = "error"
            self.error = str(message)
            self.updated_at = time.time()
            self._refresh_running = False

        if self.on_error:
            try:
                self.on_error(self.error)
            except Exception:
                pass

    def get_qr_base64(self):
        with self._lock:
            if not self.qr_image_bytes:
                return ""
            return base64.b64encode(self.qr_image_bytes).decode("ascii")

    def get_qr_ascii(self, width=44):
        with self._lock:
            raw = self.qr_image_bytes
        if not raw:
            return ""

        try:
            image = Image.open(BytesIO(raw)).convert("L")
            image = image.resize((width, width), Image.NEAREST)
        except Exception:
            return ""

        threshold = 128
        lines = []
        # 纯 ASCII：黑块使用##，白块使用空格，兼容常见终端
        for y in range(width):
            row = []
            for x in range(width):
                pixel = image.getpixel((x, y))
                row.append("##" if pixel < threshold else "  ")
            lines.append("".join(row))
        return "\n".join(lines)

    def get_state(self):
        with self._lock:
            return {
                "status": self.status,
                "error": self.error,
                "sessionid": self.sessionid,
                "updated_at": self.updated_at,
            }
