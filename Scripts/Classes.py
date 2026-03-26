import threading
import os
import requests

from Scripts.Utils import build_server_url, dict_result, get_user_info
from Scripts.lesson import LessonBaseMixin, LessonPPTMixin, LessonSolveMixin, LessonWSMixin

try:
    from Scripts.LLM import LLMHandler
except ImportError:
    LLMHandler = None

try:
    from Scripts.DevTools import PacketRecorder
except ImportError:
    PacketRecorder = None

class Lesson(LessonWSMixin, LessonSolveMixin, LessonPPTMixin, LessonBaseMixin):
    def __init__(self, lessonid, lessonname, classroomid, main_ui):
        self.classroomid = classroomid
        self.lessonid = lessonid
        self.lessonname = lessonname
        self.sessionid = main_ui.config["sessionid"]
        self.headers = {
            "Cookie": "sessionid=%s" % self.sessionid,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
        }
        self.receive_danmu = {}
        self.sent_danmu_dict = {}
        self.danmu_dict = {}
        self.unlocked_problem = []
        self.problem_cache = {}
        self.problem_page_map = {}
        self.problem_presentation_map = {}
        self.ppt_problem_pages = {}
        self.presentation_slide_covers = {}
        self.current_presentation_page = {}
        self.notified_problems = set()
        self.auto_answer_scheduled = set()
        self.precompute_answer_scheduled = set()
        self.answered_problems = set()
        self.result_notified = {}
        self.problem_end_notified = set()
        self.problem_end_deadline = {}
        self.problem_info_requested = set()
        self.auto_answer_warned = False
        self.debug_mode = bool(main_ui.config.get("debug_mode", False))
        self._seen_content_types = set()
        self._seen_answers_types = set()
        self.classmates_ls = []
        self.add_message = main_ui.add_message_signal.emit
        self.add_course = main_ui.add_course_signal.emit
        self.del_course = main_ui.del_course_signal.emit
        self.config = main_ui.config
        _, rtn = get_user_info(self.sessionid, self.config)
        self.user_uid = rtn["id"]
        self.user_uname = rtn["name"]
        self.main_ui = main_ui
        self.user_cls = User
        self.problems_dir = os.path.join(os.getcwd(), "problems")
        os.makedirs(self.problems_dir, exist_ok=True)
        self.problem_store_path = os.path.join(self.problems_dir, f"problems_{self.lessonid}.json")
        self.problem_store = self._load_problem_store()
        for pid, pdata in self.problem_store.items():
            if isinstance(pdata, dict):
                self.problem_cache[pid] = pdata

        self.llm_handler = None
        llm_cfg = self.config.get("llm_config")
        if llm_cfg and llm_cfg.get("api_key") and LLMHandler:
            self.llm_handler = LLMHandler(**llm_cfg)
            self.add_message("LLM 自动答题已启用", 1)
            # If local cache has unsolved problems, precompute answers in background.
            for pid in list(self.problem_cache.keys()):
                if not self._has_cached_answers(pid):
                    threading.Thread(target=self._precompute_answer_task, args=(pid,), daemon=True).start()

        self.dev_recorder = None
        if self.config.get("enable_devtools") and PacketRecorder:
            self.dev_recorder = PacketRecorder(self.lessonname, self.lessonid)
            self.add_message("DevTools 数据记录已启用", 1)

    def __eq__(self, other):
        return self.lessonid == other.lessonid


class User:
    def __init__(self, uid):
        self.uid = uid
    
    def get_userinfo(self, classroomid, headers, config=None):
        r = requests.get(
            build_server_url("/v/course_meta/fetch_user_info_new?query_user_id=%s&classroom_id=%s" % (self.uid, classroomid), config),
            headers=headers,
            proxies={"http": None, "https": None},
        )
        data = dict_result(r.text)["data"]
        self.sno = data["school_number"]
        self.name = data["name"]