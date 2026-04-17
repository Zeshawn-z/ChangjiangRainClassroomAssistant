import json
import os
import re
import threading
import time

import requests

FALLBACK_TO_PPT_MARKER = "__NEED_PPT_IMAGE__"


class LLMHandler:
    def __init__(
        self,
        api_key,
        base_url,
        model="",
        thinking_model="",
        vl_model="",
        answer_timeout=120,
        connect_timeout=10,
        test_timeout=15,
        save_log=True,
        **kwargs,
    ):
        self.api_key = api_key
        if not base_url.endswith("/v1"):
            self.base_url = base_url.rstrip("/") + "/v1"
        else:
            self.base_url = base_url

        legacy_model = (model or "").strip()
        self.thinking_model = (thinking_model or legacy_model or "gpt-4o-mini").strip()
        self.vl_model = (vl_model or self.thinking_model).strip()

        self.answer_timeout = max(10, int(answer_timeout))
        self.connect_timeout = max(3, int(connect_timeout))
        self.test_timeout = max(5, int(test_timeout))
        self.save_log = bool(save_log)
        self.extra_config = kwargs or {}

        self._log_lock = threading.Lock()
        self._log_file = ""
        if self.save_log:
            self._init_log_file()

    def _init_log_file(self):
        try:
            log_dir = os.path.join(os.getcwd(), "logs")
            os.makedirs(log_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            self._log_file = os.path.join(log_dir, f"llm_{ts}.jsonl")
        except Exception:
            self._log_file = ""

    def _write_log(self, event_type, payload):
        if not self.save_log or not self._log_file:
            return
        entry = {
            "timestamp": time.time(),
            "readable_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event_type,
            "payload": payload,
        }
        with self._log_lock:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def _request_completion(self, messages, model_name, is_thinking=False):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

        if is_thinking:
            data["temperature"] = 0.1

        self._write_log(
            "llm_request",
            {
                "model": model_name,
                "is_thinking": is_thinking,
                "messages": messages,
            },
        )

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=data,
            timeout=(self.connect_timeout, self.answer_timeout),
        )

        if response.status_code == 400 and "response_format" in str(response.text).lower():
            # Some OpenAI-compatible providers do not support response_format=json_object.
            self._write_log(
                "llm_retry_without_response_format",
                {
                    "model": model_name,
                    "is_thinking": is_thinking,
                    "response": response.text,
                },
            )
            data.pop("response_format", None)
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=(self.connect_timeout, self.answer_timeout),
            )

        response.raise_for_status()
        res_json = response.json()
        content = res_json["choices"][0]["message"].get("content", "")

        self._write_log(
            "llm_response",
            {
                "model": model_name,
                "is_thinking": is_thinking,
                "response": res_json,
                "content": content,
            },
        )
        return content

    def _strip_thinking_trace(self, text):
        if not isinstance(text, str):
            return ""
        # Remove explicit think/reasoning blocks that some models output.
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        return cleaned.strip()

    def _extract_json_object(self, text):
        if not isinstance(text, str):
            return None

        text = self._strip_thinking_trace(text)
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None

        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
        return None

    def _normalize_answers(self, value):
        if isinstance(value, list):
            rtn = []
            for item in value:
                s = str(item).strip()
                if s:
                    rtn.append(s)
            return rtn
        if isinstance(value, str):
            s = value.strip()
            return [s] if s else []
        return []

    def _resolve_question_type_hint(self, problem_data, options):
        raw_type = None
        if isinstance(problem_data, dict):
            raw_type = problem_data.get("problemType")

        type_code = None
        if isinstance(raw_type, (int, float)):
            type_code = int(raw_type)
        elif isinstance(raw_type, str) and raw_type.strip().isdigit():
            type_code = int(raw_type.strip())

        if type_code == 1:
            return "单选题(problemType=1)", "Must return exactly 1 answer. Use option keys like A/B/C.", type_code
        if type_code == 2:
            return "多选题(problemType=2)", "May return multiple answers. Use option keys like A/B/C.", type_code
        if type_code == 3:
            return "填空题(problemType=3)", "Return text answers for blanks, not option keys.", type_code

        if isinstance(options, list) and not options:
            return "填空题(推断)", "Likely fill-blank. Return text answers.", None

        return "选择题(problemType缺失或异常)", "Return the most likely option keys; may be 1 or multiple answers.", None

    def _build_thinking_messages(self, question_text, options, question_type_label, question_type_rule, image_urls):
        options_text = ""
        if options:
            lines = []
            for opt in options:
                if isinstance(opt, dict):
                    lines.append(f"{opt.get('key', '')}: {opt.get('value', '')}")
            if lines:
                options_text = "\n".join(lines)

        system_prompt = (
            "You are a strict exam-solving assistant. "
            "Output must be JSON object only, no markdown, no extra text."
        )

        user_prompt = (
            "Solve the question with available text/context.\n"
            f"Question Type: {question_type_label}\n"
            f"Type Rule: {question_type_rule}\n"
            f"Question: {question_text}\n"
            f"Options:\n{options_text}\n\n"
            "If image information is required but missing, return exactly:\n"
            "{\"status\":\"need_image\",\"marker\":\"__NEED_PPT_IMAGE__\",\"answers\":[]}\n"
            "Otherwise return:\n"
            "{\"status\":\"ok\",\"answers\":[\"...\"],\"reason\":\"short\"}"
        )

        # Thinking model only consumes text and decides whether image is required.
        content = [{"type": "text", "text": user_prompt}]

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

    def _build_vl_messages(self, question_text, options, question_type_label, question_type_rule, image_urls):
        options_text = ""
        if options:
            lines = []
            for opt in options:
                if isinstance(opt, dict):
                    lines.append(f"{opt.get('key', '')}: {opt.get('value', '')}")
            if lines:
                options_text = "\n".join(lines)

        system_prompt = (
            "You are a strict vision-language exam solver. "
            "Output must be JSON object only, no markdown, no extra text."
        )

        user_prompt = (
            "Use the provided PPT images to solve the same question.\n"
            f"Question Type: {question_type_label}\n"
            f"Type Rule: {question_type_rule}\n"
            f"Question: {question_text}\n"
            f"Options:\n{options_text}\n\n"
            "Return strictly:\n"
            "{\"status\":\"ok\",\"answers\":[\"...\"],\"reason\":\"short\"}"
        )

        content = [{"type": "text", "text": user_prompt}]
        for img in image_urls:
            if isinstance(img, str) and img.startswith("http"):
                content.append({"type": "image_url", "image_url": {"url": img}})

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

    def _build_question_text(self, problem_data):
        content_obj = problem_data.get("content", {}) if isinstance(problem_data, dict) else {}
        text_content = ""
        image_urls = []

        if isinstance(content_obj, dict):
            text_content = str(content_obj.get("text", "")).strip()
            if "images" in content_obj and isinstance(content_obj["images"], list):
                image_urls.extend([img for img in content_obj["images"] if isinstance(img, str)])
            elif isinstance(content_obj.get("img"), str):
                image_urls.append(content_obj["img"])
        elif isinstance(content_obj, str):
            text_content = content_obj.strip()

        if not text_content and isinstance(problem_data, dict):
            text_content = str(problem_data.get("body", "")).strip()

        if isinstance(problem_data, dict) and isinstance(problem_data.get("cover"), str):
            image_urls.append(problem_data["cover"])

        options = problem_data.get("options", []) if isinstance(problem_data, dict) else []
        question_type_label, question_type_rule, _ = self._resolve_question_type_hint(problem_data, options)
        return text_content, options, image_urls, question_type_label, question_type_rule

    def get_answer(self, problem_data, fallback_images=None):
        question_text, options, image_urls, question_type_label, question_type_rule = self._build_question_text(problem_data)

        # 第一阶段：默认走 thinking 模型
        thinking_messages = self._build_thinking_messages(
            question_text,
            options,
            question_type_label,
            question_type_rule,
            image_urls,
        )
        try:
            thinking_content = self._request_completion(
                messages=thinking_messages,
                model_name=self.thinking_model,
                is_thinking=True,
            )
        except Exception as e:
            self._write_log("llm_error", {"stage": "thinking", "error": str(e)})
            return []

        obj = self._extract_json_object(thinking_content)
        if not isinstance(obj, dict):
            self._write_log("llm_parse_error", {"stage": "thinking", "content": thinking_content})
            return []

        status = str(obj.get("status", "")).strip().lower()
        marker = str(obj.get("marker", "")).strip()
        answers = self._normalize_answers(obj.get("answers", []))

        if status == "ok" and answers:
            return answers

        need_image = status == "need_image" or marker == FALLBACK_TO_PPT_MARKER
        if not need_image:
            return answers

        # 第二阶段：仅在明确需要图片时回退到 VL
        ppt_images = []
        if isinstance(fallback_images, list):
            for url in fallback_images:
                if isinstance(url, str) and url.startswith("http") and url not in ppt_images:
                    ppt_images.append(url)

        # Only send the current-page preferred image to reduce visual noise.
        if ppt_images:
            ppt_images = [ppt_images[0]]

        if not ppt_images:
            self._write_log("llm_need_image_but_no_ppt", {"question": question_text})
            return []

        vl_messages = self._build_vl_messages(
            question_text,
            options,
            question_type_label,
            question_type_rule,
            ppt_images,
        )
        try:
            vl_content = self._request_completion(
                messages=vl_messages,
                model_name=self.vl_model,
                is_thinking=False,
            )
        except Exception as e:
            self._write_log("llm_error", {"stage": "vl", "error": str(e)})
            return []

        vl_obj = self._extract_json_object(vl_content)
        if not isinstance(vl_obj, dict):
            self._write_log("llm_parse_error", {"stage": "vl", "content": vl_content})
            return []

        vl_status = str(vl_obj.get("status", "")).strip().lower()
        vl_answers = self._normalize_answers(vl_obj.get("answers", []))
        if vl_status == "ok" and vl_answers:
            return vl_answers
        return vl_answers

    def test_connection(self, model=""):
        """
        Test the connection to the LLM API.
        Returns: (bool, message)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        target_model = (model or self.thinking_model).strip()
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=(self.connect_timeout, self.test_timeout),
            )
            if response.status_code == 200:
                # 尝试校验目标模型是否存在（部分兼容网关可能不返回完整列表）
                msg = f"连接成功（模型: {target_model}）"
                try:
                    payload = response.json()
                    model_ids = [str(item.get("id", "")) for item in payload.get("data", []) if isinstance(item, dict)]
                    if model_ids and target_model not in model_ids:
                        msg += "；注意：/models 列表中未发现该模型，请确认网关映射"
                except Exception:
                    pass
                return True, msg
            if response.status_code in (401, 403):
                return False, "连接失败: API Key 无效或无权限"
            return False, f"连接失败: HTTP {response.status_code} {response.text}"
        except Exception as e:
            return False, f"连接异常: {str(e)}"

    def test_prompt(self, prompt, model=""):
        """
        Perform a real chat completion test with a prompt.
        Returns: (bool, message, output, elapsed_ms)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        target_model = (model or self.thinking_model).strip()
        text_prompt = str(prompt or "").strip() or "请简短回复：连接测试成功。"

        data = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Reply briefly in plain text.",
                },
                {
                    "role": "user",
                    "content": text_prompt,
                },
            ],
            "temperature": 0.2,
        }

        begin = time.time()
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=(self.connect_timeout, self.test_timeout),
            )
            elapsed_ms = int((time.time() - begin) * 1000)
            if response.status_code in (401, 403):
                return False, "连接失败: API Key 无效或无权限", "", elapsed_ms
            response.raise_for_status()

            payload = response.json()
            choices = payload.get("choices", []) if isinstance(payload, dict) else []
            message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
            output = str(message.get("content", "") or "").strip()
            if not output:
                return False, "模型未返回有效文本", "", elapsed_ms
            return True, f"连接成功（模型: {target_model}）", output, elapsed_ms
        except Exception as e:
            elapsed_ms = int((time.time() - begin) * 1000)
            return False, f"连接异常: {str(e)}", "", elapsed_ms
