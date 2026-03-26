import requests
import json
import re

FALLBACK_TO_PPT_MARKER = "__NEED_PPT_IMAGE__"

class LLMHandler:
    def __init__(self, api_key, base_url, model="gpt-3.5-turbo", answer_timeout=120, connect_timeout=10, test_timeout=15):
        self.api_key = api_key
        # Ensure base_url ends with v1 if not present, commonly required for OpenAI compatible APIs
        if not base_url.endswith("/v1"):
            self.base_url = base_url.rstrip("/") + "/v1"
        else:
            self.base_url = base_url
        self.model = model
        self.answer_timeout = max(10, int(answer_timeout))
        self.connect_timeout = max(3, int(connect_timeout))
        self.test_timeout = max(5, int(test_timeout))

    def _request_completion(self, messages):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=data,
            timeout=(self.connect_timeout, self.answer_timeout)
        )
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]

    def _parse_answer_list(self, content):
        # Extract JSON list from content
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            try:
                answer_list = json.loads(match.group(0))
                return [str(x) for x in answer_list]
            except Exception:
                pass

        text = content.strip()
        if text:
            return [text]
        return []

    def get_answer(self, problem_data, fallback_images=None):
        """
        Get answer from LLM for the given problem.
        problem_data: structure from problem_cache
        Returns: list of answers (e.g. ["A"], ["A", "C"], ["answer text"])
        """
        content_obj = problem_data.get("content", {})
        text_content = ""
        image_urls = []

        if isinstance(content_obj, dict):
            text_content = content_obj.get("text", "")
            # Try to find images in content, assuming 'images' list or similar structure
            if "images" in content_obj and isinstance(content_obj["images"], list):
                image_urls.extend([img for img in content_obj["images"] if isinstance(img, str)])
            elif "img" in content_obj and isinstance(content_obj["img"], str):
                 image_urls.append(content_obj["img"])
        elif isinstance(content_obj, str):
             text_content = content_obj

        # Many Rain Classroom problems store plain question text in "body".
        if not text_content:
            text_content = str(problem_data.get("body", ""))
        
        # Check for cover image or other image fields in problem_data
        if problem_data.get("cover"):
             image_urls.append(problem_data["cover"])

        options = problem_data.get("options", [])
        
        prompt_text = f"Question: {text_content}\n"
        
        if options:
            prompt_text += "Options:\n"
            for opt in options:
                key = opt.get("key", "")
                val = opt.get("value", "")
                prompt_text += f"{key}: {val}\n"
        
        prompt_text += (
            "\nProvide the answer. If it is a multiple choice question, return only the option letters "
            "(e.g. A, B). If it is a fill-in-the-blank question, return the blank text. "
            "Return the answer in JSON format as a list of strings, e.g. [\"A\"] or [\"Answer\"]."
            "\nIf the current question text/images are insufficient to solve, output exactly: "
            f"{FALLBACK_TO_PPT_MARKER}"
        )

        messages = [
            {"role": "system", "content": "You are a helpful assistant that answers examination questions."}
        ]

        user_content = []
        if text_content or options:
             user_content.append({"type": "text", "text": prompt_text})
        
        for img_url in image_urls:
            # simple validation
            if img_url.startswith("http"):
                user_content.append({
                    "type": "image_url", 
                    "image_url": {"url": img_url}
                })
        
        if not user_content:
             # Fallback if empty
             user_content.append({"type": "text", "text": "Please solve this problem."})

        messages.append({"role": "user", "content": user_content})

        try:
            content = self._request_completion(messages)

            if FALLBACK_TO_PPT_MARKER in str(content):
                ppt_images = []
                if isinstance(fallback_images, list):
                    for url in fallback_images:
                        if isinstance(url, str) and url.startswith("http") and url not in ppt_images:
                            ppt_images.append(url)

                if not ppt_images:
                    return []

                fallback_user_content = [{
                    "type": "text",
                    "text": (
                        "Use these PPT images to solve the same question. "
                        "Return JSON list of strings only."
                    )
                }]
                for img_url in ppt_images:
                    fallback_user_content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url}
                    })

                fallback_messages = [
                    {"role": "system", "content": "You are a helpful assistant that answers examination questions."},
                    {"role": "user", "content": fallback_user_content}
                ]
                content = self._request_completion(fallback_messages)

            if FALLBACK_TO_PPT_MARKER in str(content):
                return []

            return self._parse_answer_list(content)
            
        except Exception as e:
            print(f"[LLM Error] {e}")
            return []

    def test_connection(self):
        """
        Test the connection to the LLM API.
        Returns: (bool, message)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            # Use /models for quick connectivity check to avoid slow reasoning model blocking.
            response = requests.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=(self.connect_timeout, self.test_timeout)
            )
            if response.status_code == 200:
                return True, "连接成功！"
            elif response.status_code in (401, 403):
                return False, "连接失败: API Key 无效或无权限"
            else:
                return False, f"连接失败: HTTP {response.status_code} {response.text}"
        except Exception as e:
            return False, f"连接异常: {str(e)}"
