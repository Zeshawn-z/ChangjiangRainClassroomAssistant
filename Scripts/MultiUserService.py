import copy
import datetime
import json
import os
import threading
import time
import uuid
from collections import deque

from Scripts.Monitor import monitor
from Scripts.QRLogin import QRLoginSession
from Scripts.Utils import get_initial_data, get_user_info, get_users_logs_dir, get_users_state_path, normalize_server_key


def _bool_value(value, default=False):
    if value is None:
        return bool(default)
    return bool(value)


class _SignalEmitter:
    def __init__(self, callback):
        self._callback = callback

    def emit(self, *args, **kwargs):
        self._callback(*args, **kwargs)


class HeadlessUserContext:
    def __init__(self, user_id, user_name, config, log_file_path=""):
        self.user_id = user_id
        self.user_name = user_name
        self.config = copy.deepcopy(config)
        self.log_file_path = str(log_file_path or "")

        self.is_active = False
        self._lock = threading.RLock()
        self._file_lock = threading.Lock()
        self._next_course_index = 0

        self.messages = deque(maxlen=500)
        self.courses = {}
        self.current_ppt = {"image_path": "", "info_text": ""}
        self.problem_snapshots = {}

        self.add_message_signal = _SignalEmitter(self._on_add_message)
        self.add_course_signal = _SignalEmitter(self._on_add_course)
        self.del_course_signal = _SignalEmitter(self._on_del_course)
        self.update_ppt_image_signal = _SignalEmitter(self._on_update_ppt)

    def update_config(self, config):
        with self._lock:
            self.config = copy.deepcopy(config)

    def get_course_row_count(self):
        with self._lock:
            index = self._next_course_index
            self._next_course_index += 1
            return index

    def _on_add_message(self, message, msg_type=0):
        entry = {
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "type": int(msg_type),
            "message": str(message),
        }
        with self._lock:
            self.messages.append(entry)
        self._append_log_file({"event": "message", **entry})

    def _on_add_course(self, row, row_index):
        item = {
            "course_name": str(row[0]) if len(row) > 0 else "",
            "title": str(row[1]) if len(row) > 1 else "",
            "teacher": str(row[2]) if len(row) > 2 else "",
            "start_time": str(row[3]) if len(row) > 3 else "",
            "row_index": int(row_index),
        }
        with self._lock:
            self.courses[int(row_index)] = item
        self._append_log_file({"event": "course_added", "time": datetime.datetime.now().isoformat(timespec="seconds"), "course": item})

    def _on_del_course(self, row_index):
        with self._lock:
            self.courses.pop(int(row_index), None)
        self._append_log_file(
            {
                "event": "course_removed",
                "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "row_index": int(row_index),
            }
        )

    def _on_update_ppt(self, image_path, info_text):
        info = {
            "image_path": str(image_path or ""),
            "info_text": str(info_text or ""),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self.current_ppt = info
        self._append_log_file({"event": "ppt_updated", "time": info["updated_at"], "info_text": info["info_text"]})

    def on_problem_snapshot(self, lesson_id, lesson_name, problem_id, problem_data):
        key = str(problem_id)
        with self._lock:
            self.problem_snapshots[key] = {
                "lesson_id": str(lesson_id),
                "lesson_name": str(lesson_name),
                "problem_id": key,
                "problem": copy.deepcopy(problem_data) if isinstance(problem_data, dict) else {},
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
        self._append_log_file(
            {
                "event": "problem_snapshot",
                "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "lesson_id": str(lesson_id),
                "lesson_name": str(lesson_name),
                "problem_id": key,
            }
        )

    def _append_log_file(self, data):
        if not self.log_file_path:
            return
        payload = {
            "user_id": self.user_id,
            "user_name": self.user_name,
            **(data if isinstance(data, dict) else {}),
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._file_lock:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def snapshot(self):
        with self._lock:
            return {
                "is_active": bool(self.is_active),
                "messages": list(self.messages),
                "courses": list(self.courses.values()),
                "current_ppt": copy.deepcopy(self.current_ppt),
                "problems": list(self.problem_snapshots.values()),
            }


class MultiUserService:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self.state_path = get_users_state_path()
        self.logs_dir = get_users_logs_dir()
        self.users = {}
        self.default_config = self._sanitize_default_config(get_initial_data())

        self.contexts = {}
        self.monitor_threads = {}
        self.login_sessions = {}
        self.auto_started_users = set()

        self.scheduler_thread = None

        self._load_state()

    @staticmethod
    def _deep_merge(base, override):
        if not isinstance(base, dict):
            return copy.deepcopy(override)
        result = copy.deepcopy(base)
        if not isinstance(override, dict):
            return result
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = MultiUserService._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _deep_diff(base, current):
        if isinstance(base, dict) and isinstance(current, dict):
            diff = {}
            for key, value in current.items():
                if key in base:
                    sub_diff = MultiUserService._deep_diff(base[key], value)
                    if sub_diff is not None:
                        diff[key] = sub_diff
                else:
                    diff[key] = copy.deepcopy(value)
            return diff if diff else None
        if base != current:
            return copy.deepcopy(current)
        return None

    @staticmethod
    def _sanitize_default_config(config):
        base = get_initial_data()
        merged = MultiUserService._deep_merge(base, config if isinstance(config, dict) else {})
        merged["sessionid"] = ""
        merged["server"] = normalize_server_key(merged.get("server"))
        return merged

    @staticmethod
    def _strip_user_bound_config(config):
        data = copy.deepcopy(config if isinstance(config, dict) else {})
        data.pop("sessionid", None)
        data.pop("server", None)
        return data

    @staticmethod
    def _normalize_schedule(schedule_items):
        normalized = []
        if not isinstance(schedule_items, list):
            return normalized

        for item in schedule_items:
            if not isinstance(item, dict):
                continue
            try:
                weekday = int(item.get("weekday"))
            except Exception:
                continue
            if weekday < 0 or weekday > 6:
                continue
            start = str(item.get("start", "")).strip()
            end = str(item.get("end", "")).strip()
            if len(start) != 5 or len(end) != 5 or ":" not in start or ":" not in end:
                continue
            normalized.append(
                {
                    "weekday": weekday,
                    "start": start,
                    "end": end,
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return normalized

    @staticmethod
    def _in_weekly_schedule(schedule_items, now_dt):
        if not schedule_items:
            return False

        now_weekday = now_dt.weekday()
        now_hm = now_dt.strftime("%H:%M")
        previous_weekday = (now_weekday - 1) % 7

        for item in schedule_items:
            if not item.get("enabled", True):
                continue
            weekday = int(item.get("weekday", -1))
            start = item.get("start", "")
            end = item.get("end", "")
            if not start or not end:
                continue

            if start <= end:
                if weekday == now_weekday and start <= now_hm < end:
                    return True
            else:
                # 跨天时间段，例如 23:00-01:00
                if weekday == now_weekday and now_hm >= start:
                    return True
                if weekday == previous_weekday and now_hm < end:
                    return True
        return False

    def _load_state(self):
        payload = {"version": 2, "default_config": get_initial_data(), "users": []}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            pass

        if not isinstance(payload, dict):
            payload = {}

        self.default_config = self._sanitize_default_config(payload.get("default_config", {}))
        users = payload.get("users", []) if isinstance(payload, dict) else []
        with self._lock:
            self.users = {}
            for raw in users:
                user = self._normalize_user_record(raw)
                self.users[user["id"]] = user
            self._save_state_locked()

    def _save_state_locked(self):
        payload = {
            "version": 2,
            "default_config": copy.deepcopy(self.default_config),
            "users": list(self.users.values()),
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _normalize_user_record(self, raw):
        now_text = datetime.datetime.now().isoformat(timespec="seconds")
        raw = raw if isinstance(raw, dict) else {}
        schedule = self._normalize_schedule(raw.get("schedule", []))

        user_id = str(raw.get("id") or uuid.uuid4().hex)
        name = str(raw.get("name") or f"用户-{user_id[:6]}")

        legacy_config = raw.get("config", {}) if isinstance(raw.get("config", {}), dict) else {}
        server = normalize_server_key(raw.get("server") or legacy_config.get("server") or self.default_config.get("server"))
        sessionid = str(raw.get("sessionid") or legacy_config.get("sessionid") or "").strip()

        raw_overrides = raw.get("config_overrides", {})
        if isinstance(raw_overrides, dict):
            config_overrides = self._strip_user_bound_config(raw_overrides)
        else:
            config_overrides = {}

        # 兼容旧状态文件：旧模型把完整配置存储在 config 字段里。
        if not config_overrides and legacy_config:
            legacy_effective = self._deep_merge(self.default_config, self._strip_user_bound_config(legacy_config))
            diff = self._deep_diff(
                self._strip_user_bound_config(self.default_config),
                self._strip_user_bound_config(legacy_effective),
            )
            if isinstance(diff, dict):
                config_overrides = diff

        explicit_mode = raw.get("use_custom_config")
        if explicit_mode is None:
            use_custom_config = bool(config_overrides)
        else:
            use_custom_config = _bool_value(explicit_mode)

        return {
            "id": user_id,
            "name": name,
            "enabled": bool(raw.get("enabled", True)),
            "auto_schedule": bool(raw.get("auto_schedule", True)),
            "schedule": schedule,
            "server": server,
            "sessionid": sessionid,
            "use_custom_config": use_custom_config,
            "config_overrides": config_overrides,
            "created_at": raw.get("created_at") or now_text,
            "updated_at": raw.get("updated_at") or now_text,
        }

    def _build_effective_config_locked(self, user):
        config = copy.deepcopy(self.default_config)
        if user.get("use_custom_config", False):
            config = self._deep_merge(config, user.get("config_overrides", {}))
        config["server"] = normalize_server_key(user.get("server") or config.get("server"))
        config["sessionid"] = str(user.get("sessionid", "")).strip()
        return config

    def _touch_user_locked(self, user):
        user["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    def start(self):
        with self._lock:
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                return
            self._stop_event.clear()
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self.scheduler_thread.start()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            user_ids = list(self.users.keys())
        for user_id in user_ids:
            self.stop_user_monitor(user_id, reason="service-stop")
            self.cancel_login(user_id)

    def _get_or_create_context_locked(self, user_id):
        user = self.users.get(user_id)
        if not user:
            return None
        effective_config = self._build_effective_config_locked(user)
        context = self.contexts.get(user_id)
        if not context:
            context = HeadlessUserContext(
                user_id=user_id,
                user_name=user["name"],
                config=effective_config,
                log_file_path=self._get_user_log_path(user_id),
            )
            self.contexts[user_id] = context
        else:
            context.update_config(effective_config)
        return context

    def _get_user_log_path(self, user_id):
        safe_user_id = str(user_id or "").strip() or "unknown"
        return os.path.join(self.logs_dir, f"{safe_user_id}.jsonl")

    def _scheduler_loop(self):
        while not self._stop_event.is_set():
            now = datetime.datetime.now()
            with self._lock:
                user_ids = list(self.users.keys())

            for user_id in user_ids:
                with self._lock:
                    user = self.users.get(user_id)
                    if not user:
                        continue
                    enabled = bool(user.get("enabled", True))
                    auto_schedule = bool(user.get("auto_schedule", True))
                    schedule = user.get("schedule", [])

                if not enabled or not auto_schedule:
                    if user_id in self.auto_started_users:
                        self.stop_user_monitor(user_id, reason="schedule-disabled")
                        self.auto_started_users.discard(user_id)
                    continue

                in_window = self._in_weekly_schedule(schedule, now)
                if in_window:
                    if not self.is_user_active(user_id):
                        ok, _msg = self.start_user_monitor(user_id, reason="schedule")
                        if ok:
                            self.auto_started_users.add(user_id)
                else:
                    if user_id in self.auto_started_users and self.is_user_active(user_id):
                        self.stop_user_monitor(user_id, reason="schedule-end")
                        self.auto_started_users.discard(user_id)

            self._stop_event.wait(10)

    def create_user(self, name, server="changjiang"):
        user_id = uuid.uuid4().hex
        now_text = datetime.datetime.now().isoformat(timespec="seconds")
        server_key = normalize_server_key(server or self.default_config.get("server"))
        user = {
            "id": user_id,
            "name": str(name or f"用户-{user_id[:6]}"),
            "enabled": True,
            "auto_schedule": True,
            "schedule": [],
            "server": server_key,
            "sessionid": "",
            "use_custom_config": False,
            "config_overrides": {},
            "created_at": now_text,
            "updated_at": now_text,
        }
        with self._lock:
            self.users[user_id] = user
            self._save_state_locked()
        return self.get_user(user_id)

    def delete_user(self, user_id):
        self.stop_user_monitor(user_id, reason="delete-user")
        self.cancel_login(user_id)
        with self._lock:
            existed = user_id in self.users
            self.users.pop(user_id, None)
            self.contexts.pop(user_id, None)
            self.monitor_threads.pop(user_id, None)
            self.auto_started_users.discard(user_id)
            self._save_state_locked()
        return existed

    def list_users(self):
        with self._lock:
            user_ids = list(self.users.keys())
        return [self.get_user(uid, include_runtime=False) for uid in user_ids]

    def get_user(self, user_id, include_runtime=True):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return None
            context = self.contexts.get(user_id)
            active = bool(context.is_active) if context else False
            summary = {
                "id": user["id"],
                "name": user["name"],
                "enabled": user["enabled"],
                "auto_schedule": user["auto_schedule"],
                "schedule": copy.deepcopy(user.get("schedule", [])),
                "config": self._build_effective_config_locked(user),
                "config_overrides": copy.deepcopy(user.get("config_overrides", {})),
                "use_custom_config": bool(user.get("use_custom_config", False)),
                "server": user.get("server", "changjiang"),
                "has_sessionid": bool(user.get("sessionid", "")),
                "updated_at": user.get("updated_at", ""),
                "is_active": active,
            }

        if include_runtime:
            detail = self.get_user_runtime(user_id)
            summary.update(detail)
        return summary

    def get_user_runtime(self, user_id):
        with self._lock:
            context = self.contexts.get(user_id)
            thread = self.monitor_threads.get(user_id)
            if not context:
                return {
                    "is_active": False,
                    "thread_alive": False,
                    "courses": [],
                    "messages": [],
                    "current_ppt": {"image_path": "", "info_text": ""},
                    "problems": [],
                }
            if thread and not thread.is_alive() and context.is_active:
                context.is_active = False
            snap = context.snapshot()
            return {
                "is_active": bool(context.is_active),
                "thread_alive": bool(thread.is_alive()) if thread else False,
                "courses": snap.get("courses", []),
                "messages": snap.get("messages", []),
                "current_ppt": snap.get("current_ppt", {}),
                "problems": snap.get("problems", []),
            }

    def get_user_logs(self, user_id, limit=200, message_types=None, keyword=""):
        with self._lock:
            if user_id not in self.users:
                return None

        limit = max(1, min(int(limit or 200), 2000))
        keyword = str(keyword or "").strip().lower()
        types = None
        if isinstance(message_types, (list, tuple, set)):
            normalized = set()
            for item in message_types:
                try:
                    normalized.add(int(item))
                except Exception:
                    continue
            if normalized:
                types = normalized

        path = self._get_user_log_path(user_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = deque(f, maxlen=limit * 4)
        except Exception:
            return []

        rows = []
        for line in lines:
            line = str(line).strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue

            if item.get("event") == "message" and types is not None:
                try:
                    if int(item.get("type", -1)) not in types:
                        continue
                except Exception:
                    continue

            if keyword:
                text = " ".join(
                    [
                        str(item.get("event", "")),
                        str(item.get("message", "")),
                        str(item.get("lesson_name", "")),
                        str(item.get("info_text", "")),
                    ]
                ).lower()
                if keyword not in text:
                    continue

            rows.append(item)

        if len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def update_user_profile(self, user_id, name=None, enabled=None, auto_schedule=None, server=None):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            if name is not None:
                user["name"] = str(name).strip() or user["name"]
            if enabled is not None:
                user["enabled"] = bool(enabled)
            if auto_schedule is not None:
                user["auto_schedule"] = bool(auto_schedule)
            if server is not None:
                user["server"] = normalize_server_key(server)
            self._touch_user_locked(user)
            self._save_state_locked()
            context = self.contexts.get(user_id)
            if context:
                context.update_config(self._build_effective_config_locked(user))
        return True, "ok"

    def update_user_config(self, user_id, config_patch):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"

            current_effective = self._build_effective_config_locked(user)
            merged_effective = self._deep_merge(current_effective, config_patch if isinstance(config_patch, dict) else {})
            merged_effective["server"] = normalize_server_key(user.get("server") or merged_effective.get("server"))
            merged_effective["sessionid"] = str(user.get("sessionid", "")).strip()

            base_for_diff = self._strip_user_bound_config(self.default_config)
            target_for_diff = self._strip_user_bound_config(merged_effective)
            diff = self._deep_diff(base_for_diff, target_for_diff)
            user["config_overrides"] = diff if isinstance(diff, dict) else {}
            user["use_custom_config"] = True

            self._touch_user_locked(user)
            self._save_state_locked()

            context = self.contexts.get(user_id)
            if context:
                context.update_config(self._build_effective_config_locked(user))
        return True, "ok"

    def update_user_config_mode(self, user_id, use_custom_config, clear_overrides=False):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            user["use_custom_config"] = bool(use_custom_config)
            if clear_overrides:
                user["config_overrides"] = {}
            self._touch_user_locked(user)
            self._save_state_locked()
            context = self.contexts.get(user_id)
            if context:
                context.update_config(self._build_effective_config_locked(user))
        return True, "ok"

    def get_default_config(self):
        with self._lock:
            return copy.deepcopy(self.default_config)

    def update_default_config(self, config_patch):
        with self._lock:
            merged = self._deep_merge(self.default_config, config_patch if isinstance(config_patch, dict) else {})
            merged = self._sanitize_default_config(merged)
            self.default_config = merged
            for user in self.users.values():
                user["server"] = normalize_server_key(user.get("server") or self.default_config.get("server"))
                self._touch_user_locked(user)
            for user_id, context in self.contexts.items():
                user = self.users.get(user_id)
                if user and context:
                    context.update_config(self._build_effective_config_locked(user))
            self._save_state_locked()
        return True, "ok"

    def update_user_schedule(self, user_id, schedule_items):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            user["schedule"] = self._normalize_schedule(schedule_items)
            self._touch_user_locked(user)
            self._save_state_locked()
        return True, "ok"

    def set_user_sessionid(self, user_id, sessionid):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            user["sessionid"] = str(sessionid or "").strip()
            self._touch_user_locked(user)
            self._save_state_locked()
            context = self.contexts.get(user_id)
            if context:
                context.update_config(self._build_effective_config_locked(user))
        return True, "ok"

    def validate_user_login(self, user_id):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            config = self._build_effective_config_locked(user)
        sessionid = config.get("sessionid", "")
        if not sessionid:
            return False, "未登录"
        try:
            code, info = get_user_info(sessionid, config)
            if code == 0:
                return True, info.get("name", "")
            return False, "session 已失效"
        except Exception as exc:
            return False, f"登录态校验失败: {exc}"

    def is_user_active(self, user_id):
        with self._lock:
            context = self.contexts.get(user_id)
            thread = self.monitor_threads.get(user_id)
            if not context:
                return False
            if thread and not thread.is_alive() and context.is_active:
                context.is_active = False
            return bool(context.is_active)

    def start_user_monitor(self, user_id, reason="manual"):
        ok, msg = self.validate_user_login(user_id)
        if not ok:
            return False, msg

        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            context = self._get_or_create_context_locked(user_id)
            if context.is_active:
                return True, "监听已在运行"
            context.is_active = True
            context.add_message_signal.emit(f"开始监听，触发来源: {reason}", 7)

            def run_monitor():
                try:
                    monitor(context)
                finally:
                    context.is_active = False
                    context.add_message_signal.emit("监听线程已退出", 7)

            thread = threading.Thread(target=run_monitor, daemon=True)
            self.monitor_threads[user_id] = thread
            thread.start()
        return True, "ok"

    def stop_user_monitor(self, user_id, reason="manual"):
        with self._lock:
            context = self.contexts.get(user_id)
            thread = self.monitor_threads.get(user_id)
            if not context:
                return True, "监听未启动"
            if not context.is_active:
                return True, "监听未启动"
            context.add_message_signal.emit(f"收到停止请求，触发来源: {reason}", 7)
            context.is_active = False

        if thread and thread.is_alive():
            thread.join(timeout=20)

        with self._lock:
            if context:
                context.is_active = False
            alive = bool(thread and thread.is_alive())
            if not alive:
                self.monitor_threads.pop(user_id, None)
        if alive:
            return False, "停止超时，线程仍在退出中"
        return True, "ok"

    def start_login(self, user_id):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"

            old_session = self.login_sessions.get(user_id)
            if old_session:
                old_session.close()

            config = self._build_effective_config_locked(user)

        def on_success(sessionid):
            self.set_user_sessionid(user_id, sessionid)
            with self._lock:
                context = self.contexts.get(user_id)
                if context:
                    context.add_message_signal.emit("扫码登录成功，session 已更新", 0)

        def on_error(error_message):
            with self._lock:
                context = self.contexts.get(user_id)
                if context:
                    context.add_message_signal.emit(f"扫码登录失败: {error_message}", 4)

        session = QRLoginSession(config=config, on_success=on_success, on_error=on_error)
        session.start()

        with self._lock:
            self.login_sessions[user_id] = session

        return True, "ok"

    def cancel_login(self, user_id):
        with self._lock:
            session = self.login_sessions.pop(user_id, None)
        if session:
            session.close()
            state = session.get_state()
            if state.get("status") == "pending":
                state["status"] = "cancelled"
            return True, state
        return True, {"status": "not_started"}

    def get_login_state(self, user_id):
        with self._lock:
            session = self.login_sessions.get(user_id)
        if not session:
            return {"status": "not_started", "qr_base64": "", "qr_ascii": ""}

        state = session.get_state()
        state["qr_base64"] = session.get_qr_base64()
        state["qr_ascii"] = session.get_qr_ascii()
        return state

    def get_overview(self):
        with self._lock:
            users = list(self.users.values())
            total = len(users)
            enabled = sum(1 for user in users if user.get("enabled", True))
            auto_schedule = sum(1 for user in users if user.get("auto_schedule", True))
            custom_cfg = sum(1 for user in users if user.get("use_custom_config", False))
            with_session = sum(1 for user in users if user.get("sessionid", ""))

            active = 0
            for user_id in self.users.keys():
                context = self.contexts.get(user_id)
                thread = self.monitor_threads.get(user_id)
                if not context:
                    continue
                if thread and not thread.is_alive() and context.is_active:
                    context.is_active = False
                if context.is_active:
                    active += 1

            scheduler_alive = bool(self.scheduler_thread and self.scheduler_thread.is_alive())

            users_summary = [
                {
                    "id": user["id"],
                    "name": user["name"],
                    "enabled": bool(user.get("enabled", True)),
                    "auto_schedule": bool(user.get("auto_schedule", True)),
                    "use_custom_config": bool(user.get("use_custom_config", False)),
                    "has_sessionid": bool(user.get("sessionid", "")),
                    "server": user.get("server", "changjiang"),
                    "is_active": bool(self.contexts.get(user["id"]).is_active) if self.contexts.get(user["id"]) else False,
                    "updated_at": user.get("updated_at", ""),
                }
                for user in users
            ]

        return {
            "total_users": total,
            "enabled_users": enabled,
            "active_users": active,
            "auto_schedule_users": auto_schedule,
            "custom_config_users": custom_cfg,
            "session_ready_users": with_session,
            "scheduler_alive": scheduler_alive,
            "users": users_summary,
        }
