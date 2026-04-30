import os
import threading

import requests

from Scripts.Utils import build_server_url, dict_result


class LessonPPTMixin:
    def _get_ppt(self, presentationid):
        # 获取课程各页ppt
        r = requests.get(
            url=build_server_url("/api/v3/lesson/presentation/fetch?presentation_id=%s" % (presentationid), self.config),
            headers=self.headers,
            proxies={"http": None, "https": None},
        )
        data = dict_result(r.text)["data"]
        if self.dev_recorder:
            self.dev_recorder.record("get_ppt", data, f"Fetched PPT {presentationid}")
        return data

    def _get_slide_image_path(self, presentation_id, page_no):
        safe_name = self._safe_lesson_name()
        return os.path.join(
            os.getcwd(),
            "PPTs",
            f"{safe_name}_{self.lessonid}",
            str(presentation_id),
            f"slide_{page_no}.jpg",
        )

    def _ensure_slide_image(self, presentation_id, page_no):
        image_path = self._get_slide_image_path(presentation_id, page_no)
        if os.path.exists(image_path):
            return image_path

        cover_url = self.presentation_slide_covers.get(str(presentation_id), {}).get(page_no)
        if not cover_url:
            return ""

        try:
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            r = requests.get(cover_url, timeout=10)
            if r.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(r.content)
                return image_path
        except Exception as e:
            self._log_debug(f"下载当前页PPT图片失败: {e}")
        return ""

    def _emit_current_ppt_image(self, presentation_id, page_no):
        if presentation_id is None or page_no is None:
            return
        image_path = self._ensure_slide_image(presentation_id, page_no)
        info_text = f"{self.lessonname} | PPT {presentation_id} | 第{page_no}页"
        try:
            self.main_ui.update_ppt_image_signal.emit(image_path, info_text)
        except Exception:
            pass

    def _extract_page_number(self, data):
        if not isinstance(data, dict):
            return None

        def normalize_index(key, value):
            if isinstance(value, (int, float)):
                value = int(value)
                if key.lower().endswith("index") or key.lower().endswith("idx") or key == "index":
                    return value + 1
                return value
            return None

        for key in ("page", "pageNo", "pageIndex", "page_index", "currentPage", "index", "si"):
            if key in data:
                normalized = normalize_index(key, data.get(key))
                if normalized is not None:
                    return normalized

        for key in ("slide", "currentSlide", "msg", "payload"):
            nested = data.get(key)
            if isinstance(nested, dict):
                result = self._extract_page_number(nested)
                if result is not None:
                    return result

        return None

    def _handle_presentation_change(self, data):
        if not isinstance(data, dict):
            return
        presentation_id = data.get("presentation") or data.get("pres")
        page_no = self._extract_page_number(data)
        if page_no is None:
            self._log_debug(f"presentation {presentation_id} 未提取到页码: {list(data.keys())}")
            return
        if presentation_id is not None:
            last_page = self.current_presentation_page.get(presentation_id)
            if last_page == page_no:
                return
            self.current_presentation_page[presentation_id] = page_no
        self._emit_current_ppt_image(presentation_id, page_no)

    def get_problems(self, presentationid):
        # 获取课程ppt中的题目，只汇总题目所在页码
        try:
            data = self._get_ppt(presentationid)
            slides = data.get("slides")
            if not isinstance(slides, list):
                self.add_message(f"{self.lessonname} 读取 PPT {presentationid} 数据失败：缺少有效的 slides", 4)
                self._log_debug(f"PPT {presentationid} slides 类型: {type(slides).__name__}")
                return []

            total_slides = len(slides)
            self.add_message(f"{self.lessonname} PPT {presentationid} 共 {total_slides} 页", 0)

            problem_pages = self.ppt_problem_pages.setdefault(presentationid, set())
            pages_before = set(problem_pages)
            added_pages = set()
            new_problem_ids = []

            for index, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    self._log_debug(f"PPT {presentationid} 第{index + 1}页 slide 类型: {type(slide).__name__}")
                    continue

                page_no = index + 1
                cover_url = slide.get("cover")
                if isinstance(cover_url, str) and cover_url.startswith("http"):
                    self.presentation_slide_covers.setdefault(str(presentationid), {})[page_no] = cover_url

                problem = slide.get("problem")
                if not isinstance(problem, dict):
                    if problem is not None:
                        self._log_debug(f"PPT {presentationid} 第{index + 1}页 problem 类型: {type(problem).__name__}")
                    continue

                problem_id = self._normalize_problem_id(problem.get("problemId"))
                if problem_id is None:
                    self._log_debug(f"PPT {presentationid} 第{index + 1}页 problem 缺少 problemId")
                    continue

                if page_no not in problem_pages:
                    added_pages.add(page_no)
                problem_pages.add(page_no)
                self.problem_page_map[problem_id] = page_no
                self.problem_presentation_map[problem_id] = str(presentationid)
                if isinstance(cover_url, str) and cover_url.startswith("http"):
                    problem["cover"] = cover_url

                if problem_id not in self.problem_cache:
                    new_problem_ids.append(problem_id)

                old_problem = self.problem_store.get(problem_id)
                if isinstance(old_problem, dict):
                    old_answers = old_problem.get("answers", [])
                    if isinstance(old_answers, list) and old_answers and not problem.get("answers"):
                        problem["answers"] = old_answers

                content_type = type(problem.get("content")).__name__
                if content_type not in self._seen_content_types:
                    self._seen_content_types.add(content_type)
                    self._log_debug(f"题目 {problem_id} content 类型: {content_type}")

                self.problem_cache[problem_id] = problem
                self._upsert_problem_store(problem_id, problem)
                if hasattr(self.main_ui, "on_problem_snapshot"):
                    try:
                        self.main_ui.on_problem_snapshot(self.lessonid, self.lessonname, problem_id, problem, page_no=page_no)
                    except Exception:
                        pass
                self._notify_problem_result(problem_id, problem.get("result"))
                if self._is_problem_answered(problem_id):
                    self._log_debug(f"题目 {problem_id} 已作答，记录状态")

            if problem_pages:
                pages_text = ", ".join(str(page) for page in sorted(problem_pages))
                if not pages_before:
                    self.add_message(f"{self.lessonname} PPT {presentationid} 题目页数：{pages_text}", 0)
                elif added_pages:
                    added_text = ", ".join(str(page) for page in sorted(added_pages))
                    self.add_message(f"{self.lessonname} PPT {presentationid} 题目页数更新：{pages_text}（新增 {added_text}）", 0)
                else:
                    self._log_debug(f"PPT {presentationid} 题目页数无变化")
            else:
                self.add_message(f"{self.lessonname} PPT {presentationid} 暂未发现题目", 0)

            try:
                self._save_problem_store()
                self.add_message(f"已更新题目数据文件: {self.problem_store_path}", 0)
            except Exception:
                pass

            if self.config.get("auto_save_ppt"):
                threading.Thread(
                    target=self._save_ppt_task,
                    args=(self.lessonname, self.lessonid, presentationid, slides),
                    daemon=True,
                ).start()

            for pid in new_problem_ids:
                threading.Thread(target=self._precompute_answer_task, args=(pid,), daemon=True).start()

            return sorted(problem_pages)

        except Exception as e:
            self.add_message(f"{self.lessonname} 获取 PPT {presentationid} 题目时发生错误: {e}", 4)
            self._log_debug(f"get_problems 异常: {e}")
            return []

    def _save_ppt_task(self, lesson_name, lesson_id, presentationid, slides):
        try:
            safe_name = "".join([c for c in str(lesson_name) if c.isalnum() or c in (" ", "-", "_")]).strip()
            if not safe_name:
                safe_name = f"Lesson_{lesson_id}"

            ppt_base_dir = os.path.join(os.getcwd(), "PPTs")
            lesson_dir = os.path.join(ppt_base_dir, f"{safe_name}_{lesson_id}")
            pres_dir = os.path.join(lesson_dir, str(presentationid))

            if not os.path.exists(pres_dir):
                os.makedirs(pres_dir, exist_ok=True)

            self._log_debug(f"开始保存 PPT {presentationid} ({len(slides)} 页) 到 {pres_dir}")

            count = 0
            for index, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    continue

                cover_url = slide.get("cover")
                if not cover_url:
                    continue

                file_name = f"slide_{index + 1}.jpg"
                file_path = os.path.join(pres_dir, file_name)

                if os.path.exists(file_path):
                    continue

                try:
                    r = requests.get(cover_url, timeout=10)
                    if r.status_code == 200:
                        with open(file_path, "wb") as f:
                            f.write(r.content)
                        count += 1
                except Exception as e:
                    self._log_debug(f"Failed to download slide {index + 1}: {e}")

            if count > 0:
                self.add_message(f"{lesson_name} PPT {presentationid} 新增保存 {count} 张图片", 0)

        except Exception as e:
            self.add_message(f"PPT 保存任务异常: {e}", 4)
