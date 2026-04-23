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
from Scripts.Utils import (
    get_initial_data,
    get_system_logs_path,
    get_user_info,
    get_users_logs_dir,
    get_users_state_path,
    normalize_server_key,
)

try:
    from Scripts.LLM import LLMHandler
except ImportError:
    LLMHandler = None


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
        self.active_lessons = {}
        self.on_session_expired = None

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

    def register_active_lesson(self, lesson_obj):
        if lesson_obj is None:
            return
        lesson_id = str(getattr(lesson_obj, "lessonid", "") or "")
        classroom_id = str(getattr(lesson_obj, "classroomid", "") or "")
        if not lesson_id:
            return
        key = f"{lesson_id}:{classroom_id}"
        with self._lock:
            self.active_lessons[key] = lesson_obj

    def unregister_active_lesson(self, lesson_obj):
        if lesson_obj is None:
            return
        lesson_id = str(getattr(lesson_obj, "lessonid", "") or "")
        classroom_id = str(getattr(lesson_obj, "classroomid", "") or "")
        if not lesson_id:
            return
        key = f"{lesson_id}:{classroom_id}"
        with self._lock:
            self.active_lessons.pop(key, None)

    def find_active_lesson(self, lesson_id=None, problem_id=None):
        lesson_id_text = str(lesson_id or "").strip()
        problem_id_text = str(problem_id or "").strip()

        with self._lock:
            lessons = list(self.active_lessons.values())

        if lesson_id_text:
            for lesson in lessons:
                if str(getattr(lesson, "lessonid", "")) == lesson_id_text:
                    if not problem_id_text:
                        return lesson
                    cache = getattr(lesson, "problem_cache", {})
                    store = getattr(lesson, "problem_store", {})
                    if problem_id_text in cache or problem_id_text in store:
                        return lesson

        if problem_id_text:
            for lesson in lessons:
                cache = getattr(lesson, "problem_cache", {})
                store = getattr(lesson, "problem_store", {})
                if problem_id_text in cache or problem_id_text in store:
                    return lesson

        return lessons[0] if lessons else None

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

    def on_problem_snapshot(self, lesson_id, lesson_name, problem_id, problem_data, page_no=None):
        key = str(problem_id)
        page_value = None
        try:
            if page_no is not None:
                page_value = int(page_no)
        except Exception:
            page_value = None
        with self._lock:
            self.problem_snapshots[key] = {
                "lesson_id": str(lesson_id),
                "lesson_name": str(lesson_name),
                "problem_id": key,
                "page_no": page_value,
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
        self.system_logs_path = get_system_logs_path()
        self._system_log_lock = threading.Lock()
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
    def _sanitize_config_for_frontend(config):
        data = copy.deepcopy(config if isinstance(config, dict) else {})
        llm = data.get("llm_config")
        if not isinstance(llm, dict):
            llm = {}
            data["llm_config"] = llm
        key = str(llm.get("api_key", "")).strip()
        llm["api_key_configured"] = bool(key)
        llm["api_key"] = ""
        return data

    @staticmethod
    def _strip_user_bound_config(config):
        data = copy.deepcopy(config if isinstance(config, dict) else {})
        data.pop("sessionid", None)
        data.pop("server", None)
        return data

    @staticmethod
    def _normalize_problem_answers(answers):
        if isinstance(answers, list):
            values = answers
        else:
            text = str(answers or "")
            for sep in ["，", "|", "/", "、", "\n", "\t"]:
                text = text.replace(sep, ",")
            values = text.split(",")

        normalized = []
        for item in values:
            text = str(item).strip()
            if not text:
                continue
            if text not in normalized:
                normalized.append(text)
        return normalized

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
        context.on_session_expired = lambda uid=user_id: self._handle_context_session_expired(uid)
        return context

    def _append_system_log_entry(self, data):
        payload = data if isinstance(data, dict) else {}
        line = json.dumps(payload, ensure_ascii=False)
        with self._system_log_lock:
            try:
                with open(self.system_logs_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def _emit_session_event(self, user_id, status, source, detail="", level=0):
        with self._lock:
            user = self.users.get(user_id)
            user_name = user.get("name", "") if isinstance(user, dict) else ""
            has_sessionid = bool(str(user.get("sessionid", "")).strip()) if isinstance(user, dict) else False

        payload = {
            "event": "session_state",
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": str(status or "unknown"),
            "source": str(source or "unknown"),
            "detail": str(detail or ""),
            "has_sessionid": has_sessionid,
            "user_id": str(user_id or ""),
            "user_name": str(user_name or ""),
            "level": int(level),
        }

        self._append_system_log_entry(payload)

    def _emit_system_event(self, user_id, action, source, detail="", level=7):
        with self._lock:
            user = self.users.get(user_id)
            user_name = user.get("name", "") if isinstance(user, dict) else ""

        payload = {
            "event": "system_event",
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "action": str(action or "unknown"),
            "source": str(source or "unknown"),
            "detail": str(detail or ""),
            "user_id": str(user_id or ""),
            "user_name": str(user_name or ""),
            "level": int(level),
        }
        self._append_system_log_entry(payload)

    def _handle_context_session_expired(self, user_id):
        self._emit_system_event(user_id, "session-expired-detected", "monitor", "监听线程检测到会话失效")
        self._emit_session_event(user_id, "refresh-triggered", "monitor-session-expired", "检测到会话失效，准备自动扫码刷新", level=7)
        ok, msg = self.start_login(user_id, source="monitor-session-expired")
        with self._lock:
            context = self.contexts.get(user_id)
            if context:
                if ok:
                    context.add_message_signal.emit("检测到会话失效，已自动发起扫码刷新", 7)
                else:
                    context.add_message_signal.emit(f"会话失效后自动刷新失败: {msg}", 4)

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
                "config": self._sanitize_config_for_frontend(self._build_effective_config_locked(user)),
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

    def correct_problem_answer(self, user_id, problem_id, answers, lesson_id=None, submit_now=True):
        normalized_problem_id = str(problem_id or "").strip()
        if not normalized_problem_id:
            return False, "题目ID不能为空", {}

        normalized_answers = self._normalize_problem_answers(answers)
        if not normalized_answers:
            return False, "请至少输入一个答案", {}

        with self._lock:
            if user_id not in self.users:
                return False, "用户不存在", {}
            context = self.contexts.get(user_id)

        if not context:
            return False, "监听尚未启动，无法在线更正题目", {}

        lesson = None
        if hasattr(context, "find_active_lesson"):
            lesson = context.find_active_lesson(lesson_id=lesson_id, problem_id=normalized_problem_id)
        if not lesson:
            return False, "未找到正在监听的课程或题目", {}

        try:
            if hasattr(lesson, "_normalize_problem_id"):
                normalized_problem_id = lesson._normalize_problem_id(normalized_problem_id) or normalized_problem_id

            lesson._set_problem_answers(normalized_problem_id, normalized_answers)

            submit_attempted = bool(submit_now)
            submit_ok = None
            if submit_attempted:
                submit_ok = bool(lesson.answer_problem(normalized_problem_id, normalized_answers))

            submitted = bool(lesson._is_problem_answered(normalized_problem_id))
            problem_data = lesson.problem_cache.get(normalized_problem_id)
            if not isinstance(problem_data, dict):
                problem_data = lesson.problem_store.get(normalized_problem_id, {})

            page_no = lesson.problem_page_map.get(normalized_problem_id)
            context.on_problem_snapshot(
                lesson.lessonid,
                lesson.lessonname,
                normalized_problem_id,
                problem_data,
                page_no=page_no,
            )

            if submit_attempted:
                if submit_ok:
                    context.add_message_signal.emit(f"题目 {normalized_problem_id} 在线更正后已提交: {normalized_answers}", 1)
                else:
                    context.add_message_signal.emit(f"题目 {normalized_problem_id} 在线更正已保存，但提交失败", 4)
            else:
                context.add_message_signal.emit(f"题目 {normalized_problem_id} 在线更正答案已保存: {normalized_answers}", 0)

            detail = {
                "lesson_id": str(getattr(lesson, "lessonid", "") or ""),
                "lesson_name": str(getattr(lesson, "lessonname", "") or ""),
                "problem_id": normalized_problem_id,
                "page_no": page_no,
                "answers": normalized_answers,
                "submit_attempted": submit_attempted,
                "submit_ok": bool(submit_ok) if submit_attempted else None,
                "submitted": submitted,
            }
            return True, "ok", detail
        except Exception as exc:
            return False, f"在线更正失败: {exc}", {}

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

    def get_global_logs(self, limit=200, event_names=None, keyword=""):
        limit = max(1, min(int(limit or 200), 2000))
        keyword = str(keyword or "").strip().lower()

        if isinstance(event_names, (list, tuple, set)):
            names = {str(item).strip() for item in event_names if str(item).strip()}
            target_events = names if names else {"system_event", "session_state"}
        else:
            target_events = {"system_event", "session_state"}

        rows = []
        try:
            with open(self.system_logs_path, "r", encoding="utf-8") as f:
                lines = deque(f, maxlen=max(limit * 8, 400))
        except Exception:
            return []

        for line in lines:
            line = str(line).strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue

            event_name = str(item.get("event", ""))
            if event_name not in target_events:
                continue

            if keyword:
                text = " ".join(
                    [
                        event_name,
                        str(item.get("action", "")),
                        str(item.get("status", "")),
                        str(item.get("source", "")),
                        str(item.get("detail", "")),
                        str(item.get("user_name", "")),
                    ]
                ).lower()
                if keyword not in text:
                    continue

            rows.append(item)

        rows.sort(key=lambda item: str(item.get("time", "")))
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
            return self._sanitize_config_for_frontend(self.default_config)

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

    @staticmethod
    def _normalize_llm_config_for_test(llm_cfg):
        cfg = llm_cfg if isinstance(llm_cfg, dict) else {}
        api_key = str(cfg.get("api_key", "") or "").strip()
        if not api_key:
            return None, "未配置 API Key"

        base_url = str(cfg.get("base_url", "") or "").strip() or "https://api.siliconflow.cn/v1"
        legacy_model = str(cfg.get("model", "") or "").strip()
        thinking_model = str(cfg.get("thinking_model", "") or "").strip() or legacy_model or "gpt-4o-mini"
        vl_model = str(cfg.get("vl_model", "") or "").strip() or thinking_model

        try:
            answer_timeout = int(cfg.get("answer_timeout", 120) or 120)
        except Exception:
            answer_timeout = 120
        try:
            connect_timeout = int(cfg.get("connect_timeout", 10) or 10)
        except Exception:
            connect_timeout = 10
        try:
            test_timeout = int(cfg.get("test_timeout", 15) or 15)
        except Exception:
            test_timeout = 15

        normalized = {
            "api_key": api_key,
            "base_url": base_url,
            "model": legacy_model or thinking_model,
            "thinking_model": thinking_model,
            "vl_model": vl_model,
            "answer_timeout": max(10, answer_timeout),
            "connect_timeout": max(3, connect_timeout),
            "test_timeout": max(5, test_timeout),
        }
        return normalized, "ok"

    def test_llm_prompt(self, prompt="", config_patch=None, user_id=None):
        if not LLMHandler:
            return False, "LLM 模块加载失败，请检查依赖", {
                "prompt": str(prompt or ""),
                "thinking": None,
                "vl": None,
            }

        with self._lock:
            if user_id:
                user = self.users.get(user_id)
                if not user:
                    return False, "用户不存在", {
                        "prompt": str(prompt or ""),
                        "thinking": None,
                        "vl": None,
                    }
                base_config = self._build_effective_config_locked(user)
            else:
                base_config = copy.deepcopy(self.default_config)

        merged_config = self._deep_merge(base_config, config_patch if isinstance(config_patch, dict) else {})
        llm_cfg, msg = self._normalize_llm_config_for_test(merged_config.get("llm_config", {}))
        if not llm_cfg:
            return False, msg, {
                "prompt": str(prompt or ""),
                "thinking": None,
                "vl": None,
            }

        handler = LLMHandler(
            api_key=llm_cfg["api_key"],
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            thinking_model=llm_cfg["thinking_model"],
            vl_model=llm_cfg["vl_model"],
            answer_timeout=llm_cfg["answer_timeout"],
            connect_timeout=llm_cfg["connect_timeout"],
            test_timeout=llm_cfg["test_timeout"],
            save_log=False,
        )

        test_prompt = str(prompt or "").strip() or "请用一句话回复：连接测试成功。"

        think_ok, think_msg, think_output, think_elapsed = handler.test_prompt(
            prompt=test_prompt,
            model=llm_cfg["thinking_model"],
        )

        vl_model = llm_cfg["vl_model"]
        if vl_model == llm_cfg["thinking_model"]:
            vl_ok = think_ok
            vl_msg = "与 Thinking 模型相同，复用同一测试结果"
            vl_output = think_output
            vl_elapsed = think_elapsed
        else:
            vl_ok, vl_msg, vl_output, vl_elapsed = handler.test_prompt(
                prompt=test_prompt,
                model=vl_model,
            )

        ok = bool(think_ok and vl_ok)
        message = "模型测试通过" if ok else "模型测试失败"
        result = {
            "prompt": test_prompt,
            "thinking": {
                "ok": bool(think_ok),
                "message": str(think_msg or ""),
                "model": llm_cfg["thinking_model"],
                "elapsed_ms": int(think_elapsed),
                "output": str(think_output or ""),
            },
            "vl": {
                "ok": bool(vl_ok),
                "message": str(vl_msg or ""),
                "model": vl_model,
                "elapsed_ms": int(vl_elapsed),
                "output": str(vl_output or ""),
            },
        }
        return ok, message, result

    def update_user_schedule(self, user_id, schedule_items):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            user["schedule"] = self._normalize_schedule(schedule_items)
            self._touch_user_locked(user)
            self._save_state_locked()
        return True, "ok"

    def set_user_sessionid(self, user_id, sessionid, source="manual"):
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

        has_sessionid = bool(str(sessionid or "").strip())
        if has_sessionid:
            self._emit_session_event(user_id, "session-updated", source, "session 已写入用户配置", level=0)
        else:
            self._emit_session_event(user_id, "session-cleared", source, "session 已清空", level=7)
        return True, "ok"

    def validate_user_login(self, user_id, source="unknown"):
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            config = self._build_effective_config_locked(user)
        sessionid = config.get("sessionid", "")
        self._emit_session_event(user_id, "validate-start", source, "开始校验登录态", level=0)
        if not sessionid:
            self._emit_session_event(user_id, "validate-no-session", source, "当前未配置 sessionid", level=7)
            return False, "未登录"
        try:
            code, info = get_user_info(sessionid, config)
            if code == 0:
                self._emit_session_event(user_id, "validate-ok", source, f"登录有效: {info.get('name', '')}", level=0)
                return True, info.get("name", "")
            self._emit_session_event(user_id, "validate-expired", source, f"登录失效 code={code}", level=4)
            return False, "session 已失效"
        except Exception as exc:
            self._emit_session_event(user_id, "validate-error", source, f"校验异常: {exc}", level=4)
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
        self._emit_system_event(user_id, "monitor-start-request", f"start-monitor:{reason}", "收到启动监听请求")
        ok, msg = self.validate_user_login(user_id, source=f"start-monitor:{reason}")
        if not ok:
            if "失效" in str(msg) or "未登录" in str(msg):
                self._emit_session_event(user_id, "refresh-requested", f"start-monitor:{reason}", msg, level=7)
                login_ok, login_msg = self.start_login(user_id, source=f"start-monitor:{reason}")
                if login_ok:
                    self._emit_system_event(user_id, "monitor-start-blocked", f"start-monitor:{reason}", "会话无效，已触发扫码刷新")
                    return False, f"{msg}，已自动发起扫码刷新"
                self._emit_system_event(user_id, "monitor-start-failed", f"start-monitor:{reason}", f"会话无效且刷新失败: {login_msg}")
                return False, f"{msg}，自动发起扫码失败: {login_msg}"
            self._emit_system_event(user_id, "monitor-start-failed", f"start-monitor:{reason}", msg)
            return False, msg

        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"
            context = self._get_or_create_context_locked(user_id)
            if context.is_active:
                self._emit_system_event(user_id, "monitor-already-active", f"start-monitor:{reason}", "监听已在运行")
                return True, "监听已在运行"
            context.is_active = True
            context.add_message_signal.emit(f"开始监听，触发来源: {reason}", 7)
            self._emit_system_event(user_id, "monitor-started", f"start-monitor:{reason}", "监听线程已启动")

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
        self._emit_system_event(user_id, "monitor-stop-request", f"stop-monitor:{reason}", "收到停止监听请求")
        with self._lock:
            context = self.contexts.get(user_id)
            thread = self.monitor_threads.get(user_id)
            if not context:
                self._emit_system_event(user_id, "monitor-stop-noop", f"stop-monitor:{reason}", "监听未启动")
                return True, "监听未启动"
            if not context.is_active:
                self._emit_system_event(user_id, "monitor-stop-noop", f"stop-monitor:{reason}", "监听未启动")
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
            self._emit_system_event(user_id, "monitor-stop-timeout", f"stop-monitor:{reason}", "停止超时，线程仍在退出中")
            return False, "停止超时，线程仍在退出中"
        self._emit_system_event(user_id, "monitor-stopped", f"stop-monitor:{reason}", "监听已停止")
        return True, "ok"

    def start_login(self, user_id, source="manual"):
        self._emit_system_event(user_id, "login-start-request", source, "收到扫码登录请求")
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return False, "用户不存在"

            old_session = self.login_sessions.get(user_id)
            if old_session:
                old_state = old_session.get_state()
                if old_state.get("status") == "pending":
                    self._emit_system_event(user_id, "login-already-pending", source, "已有扫码登录进行中")
                    self._emit_session_event(user_id, "refresh-pending", source, "已有扫码刷新进行中", level=7)
                    return True, "扫码已在进行中"
                old_session.close()

            config = self._build_effective_config_locked(user)

        def on_success(sessionid):
            self.set_user_sessionid(user_id, sessionid, source=f"login-success:{source}")
            self._emit_system_event(user_id, "login-success", source, "扫码登录成功")
            self._emit_session_event(user_id, "refresh-success", source, "扫码刷新成功", level=0)
            with self._lock:
                context = self.contexts.get(user_id)
                if context:
                    context.add_message_signal.emit("扫码登录成功，session 已更新", 0)

        def on_error(error_message):
            self._emit_system_event(user_id, "login-failed", source, str(error_message))
            self._emit_session_event(user_id, "refresh-failed", source, f"扫码刷新失败: {error_message}", level=4)
            with self._lock:
                context = self.contexts.get(user_id)
                if context:
                    context.add_message_signal.emit(f"扫码登录失败: {error_message}", 4)

        session = QRLoginSession(config=config, on_success=on_success, on_error=on_error)
        session.start()

        with self._lock:
            self.login_sessions[user_id] = session

        self._emit_system_event(user_id, "login-started", source, "已发起扫码流程")
        self._emit_session_event(user_id, "refresh-started", source, "已发起扫码刷新流程", level=7)

        return True, "ok"

    def cancel_login(self, user_id):
        with self._lock:
            session = self.login_sessions.pop(user_id, None)
        if session:
            session.close()
            state = session.get_state()
            if state.get("status") == "pending":
                state["status"] = "cancelled"
            self._emit_system_event(user_id, "login-cancelled", "api-cancel-login", "已取消扫码登录")
            return True, state
        self._emit_system_event(user_id, "login-cancel-noop", "api-cancel-login", "当前没有扫码登录任务")
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
