import json
import os


class LessonBaseMixin:
    def _log_debug(self, message):
        if self.debug_mode:
            self.add_message(f"[DEBUG] {message}", 0)

    def _normalize_problem_id(self, problem_id):
        if problem_id is None:
            return None
        return str(problem_id)

    def _resolve_problem_id(self, source, fallback=None):
        if isinstance(source, dict):
            for key in ("problemId", "sid", "problemid", "id", "prob"):
                if key in source and source[key] is not None:
                    return self._normalize_problem_id(source[key])
        if fallback is not None:
            return self._normalize_problem_id(fallback)
        return None

    def _format_limit_text(self, limit):
        if limit is None:
            return "请尽快查看"
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            return "请尽快查看"
        if limit_int == -1:
            return "不限时"
        if limit_int < 0:
            return "即将截止"
        return f"剩余约{limit_int}秒"

    def _safe_lesson_name(self):
        safe_name = "".join([c for c in str(self.lessonname) if c.isalnum() or c in (" ", "-", "_")]).strip()
        if not safe_name:
            safe_name = f"Lesson_{self.lessonid}"
        return safe_name

    def _load_problem_store(self):
        try:
            if os.path.exists(self.problem_store_path):
                with open(self.problem_store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            self._log_debug(f"读取题库文件失败: {e}")
        return {}

    def _save_problem_store(self):
        try:
            with open(self.problem_store_path, "w", encoding="utf-8") as f:
                json.dump(self.problem_store, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self._log_debug(f"保存题库文件失败: {e}")

    def _upsert_problem_store(self, problem_id, problem):
        if not isinstance(problem, dict):
            return

        old_item = self.problem_store.get(problem_id, {})
        old_answers = old_item.get("answers", []) if isinstance(old_item, dict) else []
        new_answers = problem.get("answers", [])
        if not isinstance(new_answers, list):
            new_answers = []
        if not new_answers and old_answers:
            new_answers = old_answers

        item = {
            "problemId": problem_id,
            "problemType": problem.get("problemType", 1),
            "body": problem.get("body", ""),
            "options": problem.get("options", []),
            "answers": new_answers,
            "limit": problem.get("limit", 0),
            "sendTime": problem.get("sendTime", 0),
            "result": problem.get("result"),
        }
        self.problem_store[problem_id] = item

    def _set_problem_answers(self, problem_id, answers):
        if problem_id in self.problem_cache and isinstance(self.problem_cache[problem_id], dict):
            self.problem_cache[problem_id]["answers"] = answers

        item = self.problem_store.get(problem_id)
        if not isinstance(item, dict):
            item = {
                "problemId": problem_id,
                "problemType": 1,
                "body": "",
                "options": [],
            }
            self.problem_store[problem_id] = item
        item["answers"] = answers
        self._save_problem_store()

    def _mark_problem_answered(self, problem_id, result=None):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return

        self.answered_problems.add(normalized_id)
        if normalized_id in self.problem_cache and isinstance(self.problem_cache[normalized_id], dict):
            self.problem_cache[normalized_id]["result"] = result if result is not None else self.problem_cache[normalized_id].get("result")
        if normalized_id in self.problem_store and isinstance(self.problem_store[normalized_id], dict):
            if result is not None:
                self.problem_store[normalized_id]["result"] = result
        self._save_problem_store()

    def _is_problem_answered(self, problem_id):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return False

        if normalized_id in self.answered_problems:
            return True

        def is_answered_item(item):
            if not isinstance(item, dict):
                return False
            result = item.get("result")
            if result not in (None, "", [], {}):
                return True
            for key in ("myAnswer", "myanswer", "answered", "isAnswered"):
                value = item.get(key)
                if value:
                    return True
            return False

        if is_answered_item(self.problem_cache.get(normalized_id)):
            self.answered_problems.add(normalized_id)
            return True
        if is_answered_item(self.problem_store.get(normalized_id)):
            self.answered_problems.add(normalized_id)
            return True

        return False

    def _notify_problem_result(self, problem_id, result):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return
        if result in (None, "", [], {}):
            return

        signature = json.dumps(result, ensure_ascii=False, sort_keys=True) if isinstance(result, (dict, list)) else str(result)
        if self.result_notified.get(normalized_id) == signature:
            return
        self.result_notified[normalized_id] = signature

        self._mark_problem_answered(normalized_id, result=result)
