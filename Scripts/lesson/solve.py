import json
import threading
import time

import requests


class LessonSolveMixin:
    def _collect_problem_fallback_images(self, problem_id, problem_data):
        images = []

        if isinstance(problem_data, dict):
            cover = problem_data.get("cover")
            if isinstance(cover, str) and cover.startswith("http"):
                images.append(cover)

        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return images

        presentation_id = self.problem_presentation_map.get(normalized_id)
        page_no = self.problem_page_map.get(normalized_id)

        if presentation_id is not None and page_no is not None:
            cover_map = self.presentation_slide_covers.get(str(presentation_id), {})
            current_cover = cover_map.get(page_no)
            if isinstance(current_cover, str) and current_cover.startswith("http") and current_cover not in images:
                images.append(current_cover)

            for _, cover_url in sorted(cover_map.items(), key=lambda x: x[0]):
                if isinstance(cover_url, str) and cover_url.startswith("http") and cover_url not in images:
                    images.append(cover_url)
                if len(images) >= 10:
                    break

        return images

    def _has_cached_answers(self, problem_id):
        problem_data = self.problem_cache.get(problem_id)
        if isinstance(problem_data, dict):
            ans = problem_data.get("answers", [])
            if isinstance(ans, list) and ans:
                return True

        store_item = self.problem_store.get(problem_id)
        if isinstance(store_item, dict):
            ans = store_item.get("answers", [])
            if isinstance(ans, list) and ans:
                return True
        return False

    def _normalize_llm_answers(self, problem_data, raw_answers):
        if not isinstance(raw_answers, list):
            return []

        ptype = problem_data.get("problemType", 1) if isinstance(problem_data, dict) else 1
        options = problem_data.get("options", []) if isinstance(problem_data, dict) else []
        option_keys = []
        option_value_to_key = {}
        for opt in options:
            if not isinstance(opt, dict):
                continue
            key = str(opt.get("key", "")).strip().upper()
            value = str(opt.get("value", "")).strip()
            if key:
                option_keys.append(key)
            if value and key:
                option_value_to_key[value] = key

        normalized = []
        for ans in raw_answers:
            text = str(ans).strip()
            if not text:
                continue
            direct = text.upper()
            if direct in option_keys:
                normalized.append(direct)
                continue
            if text in option_value_to_key:
                normalized.append(option_value_to_key[text])
                continue

            chars = []
            for ch in direct:
                if ch in option_keys:
                    chars.append(ch)
            if chars:
                normalized.extend(chars)
            else:
                normalized.append(text)

        unique = []
        for item in normalized:
            if item not in unique:
                unique.append(item)

        if ptype == 1 and unique:
            return [unique[0]]
        return unique

    def _ensure_problem_answers(self, problem_id):
        problem_data = self.problem_cache.get(problem_id)
        if not isinstance(problem_data, dict):
            problem_data = self.problem_store.get(problem_id)

        if not isinstance(problem_data, dict):
            return []

        cached_answers = problem_data.get("answers", [])
        if isinstance(cached_answers, list) and cached_answers:
            return cached_answers

        if not self.llm_handler:
            return []

        fallback_images = self._collect_problem_fallback_images(problem_id, problem_data)
        answers = self.llm_handler.get_answer(problem_data, fallback_images=fallback_images)
        normalized_answers = self._normalize_llm_answers(problem_data, answers)
        if normalized_answers:
            self.add_message(f"题目 {problem_id} LLM 解题完成: {normalized_answers}", 0)
            self._set_problem_answers(problem_id, normalized_answers)
        return normalized_answers

    def _precompute_answer_task(self, problem_id):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return
        if normalized_id in self.precompute_answer_scheduled:
            return
        self.precompute_answer_scheduled.add(normalized_id)
        try:
            had_cached = self._has_cached_answers(normalized_id)
            answers = self._ensure_problem_answers(normalized_id)
            if answers and not had_cached:
                page_no = self.problem_page_map.get(normalized_id)
                if page_no is not None:
                    self.add_message(f"缓存题目 第{page_no}页 {normalized_id} 预解答案: {answers}", 0)
                else:
                    self.add_message(f"缓存题目 {normalized_id} 预解答案: {answers}", 0)
        finally:
            self.precompute_answer_scheduled.discard(normalized_id)

    def answer_problem(self, problem_id, list_result):
        if not list_result:
            return False

        if self._is_problem_answered(problem_id):
            self.add_message(f"题目 {problem_id} 已作答，跳过自动提交", 0)
            return True

        problem = self.problem_cache.get(problem_id)
        if hasattr(problem, "get"):
            ptype = problem.get("problemType", 1)
        else:
            ptype = 1

        result = list_result
        if ptype == 3 and isinstance(result, list) and len(result) == 1:
            result = result[0]

        url = "https://changjiang.yuketang.cn/api/v3/lesson/problem/answer"
        data = {
            "problemId": problem_id,
            "problemType": ptype,
            "dt": int(time.time() * 1000),
            "result": result,
        }

        self._log_debug(f"Payload for problem {problem_id}: {json.dumps(data, ensure_ascii=False)}")
        if self.dev_recorder:
            self.dev_recorder.record("answer_problem", data, f"Submitting answer for {problem_id}")

        try:
            r = requests.post(url=url, headers=self.headers, json=data, proxies={"http": None, "https": None}, timeout=5)
            res = r.json()
            if self.dev_recorder:
                self.dev_recorder.record("answer_response", res, f"Answer response for {problem_id}")
            if res.get("code") == 0:
                self.add_message(f"题目 {problem_id} 自动答题成功: {result}", 1)
                self._mark_problem_answered(problem_id, result=result)
                return True
            msg_text = str(res.get("msg", ""))
            if "ALREADY_ANSWERED" in msg_text:
                self._mark_problem_answered(problem_id)
                self.add_message(f"题目 {problem_id} 已作答，跳过重复提交", 0)
                return True
            self.add_message(f"题目 {problem_id} 自动答题失败: {res.get('msg')}", 4)
            return False
        except Exception as e:
            self.add_message(f"题目 {problem_id} 自动答题异常: {e}", 4)
            return False

    def _schedule_auto_answer(self, problem_id, reason=""):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return

        if self._is_problem_answered(normalized_id):
            self._log_debug(f"题目 {normalized_id} 已作答，跳过自动答题排队")
            return

        if reason == "ppt-cache":
            return

        if not self.config.get("auto_answer"):
            return

        if not self.llm_handler and not self._has_cached_answers(normalized_id):
            if not self.auto_answer_warned:
                self.add_message(f"{self.lessonname} 未配置LLM，不支持自动答题，请配置 llm_config 或 手动作答。", 4)
                self.auto_answer_warned = True
            return

        if normalized_id in self.auto_answer_scheduled:
            return

        self.auto_answer_scheduled.add(normalized_id)
        if reason:
            self._log_debug(f"题目 {normalized_id} 加入自动答题队列，触发源: {reason}")
        threading.Thread(target=self._auto_answer_task, args=(normalized_id,), daemon=True).start()

    def _auto_answer_task(self, problem_id):
        delay = self.config.get("answer_config", {}).get("answer_delay", {}).get("custom", {}).get("time", 5)
        if delay < 2:
            delay = 2
        time.sleep(delay)

        try:
            answers = self._ensure_problem_answers(problem_id)
            if answers:
                self.add_message(f"题目 {problem_id} 推荐答案: {answers}", 3)
                ok = self.answer_problem(problem_id, answers)
                if not ok:
                    self.auto_answer_scheduled.discard(problem_id)
            else:
                self.add_message(f"LLM 未返回题目 {problem_id} 的答案", 4)
                self.auto_answer_scheduled.discard(problem_id)
        except Exception as e:
            self.add_message(f"LLM 答题出错: {e}", 4)
            self.auto_answer_scheduled.discard(problem_id)

    def _notify_problem_ended(self, problem_id):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return
        if normalized_id in self.problem_end_notified:
            return
        if self._is_problem_answered(normalized_id):
            return

        self.problem_end_notified.add(normalized_id)
        page_no = self.problem_page_map.get(normalized_id)
        page_text = f"第{page_no}页" if page_no is not None else "未知页"
        self.add_message(f"{self.lessonname} {page_text}题目已结束", 0)

    def _problem_end_countdown(self, problem_id, deadline):
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                break
            time.sleep(min(remain, 1))

        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return
        if self.problem_end_deadline.get(normalized_id) != deadline:
            return
        self._notify_problem_ended(normalized_id)

    def _schedule_problem_end_notice(self, problem_id, limit):
        normalized_id = self._normalize_problem_id(problem_id)
        if not normalized_id:
            return

        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            return

        if limit_int == -1:
            self.problem_end_deadline.pop(normalized_id, None)
            return

        if limit_int <= 0:
            self.problem_end_deadline[normalized_id] = time.time()
            self._notify_problem_ended(normalized_id)
            return

        deadline = time.time() + limit_int
        self.problem_end_deadline[normalized_id] = deadline
        threading.Thread(target=self._problem_end_countdown, args=(normalized_id, deadline), daemon=True).start()

    def _notify_problem_release(self, problem_id, limit):
        normalized_id = self._normalize_problem_id(problem_id)
        if normalized_id is not None and normalized_id in self.notified_problems:
            return

        page_no = None
        if normalized_id is not None:
            page_no = self.problem_page_map.get(normalized_id)
        if page_no is None:
            self._log_debug(f"题目 {normalized_id} 未找到页码映射")
        page_text = f"第{page_no}页" if page_no is not None else "未知页"
        limit_text = self._format_limit_text(limit)
        self.add_message(f"{self.lessonname} {page_text}发布新题（{limit_text}）", 3)

        if normalized_id is not None:
            self.notified_problems.add(normalized_id)
            self._schedule_problem_end_notice(normalized_id, limit)

        if normalized_id:
            self._schedule_auto_answer(normalized_id, reason="release")
        elif self.config.get("auto_answer"):
            self.add_message(f"{self.lessonname} 无法自动答题：未解析到题目ID", 4)
