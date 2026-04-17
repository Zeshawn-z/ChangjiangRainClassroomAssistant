import json
import time

import requests
import websocket

from Scripts.Utils import build_server_url, dict_result


class LessonWSMixin:
    def on_open(self, wsapp):
        ws_userid = getattr(self, "identity_id", None) or self.user_uid
        self.handshark = {
            "op": "hello",
            "userid": ws_userid,
            "role": "student",
            "auth": self.auth,
            "lessonid": self.lessonid,
        }
        if self.dev_recorder:
            self.dev_recorder.record("ws_open", self.handshark, "WS Handshake sent")
        wsapp.send(json.dumps(self.handshark))

    def checkin_class(self):
        r = requests.post(
            url=build_server_url("/api/v3/lesson/checkin", self.config),
            headers=self.headers,
            data=json.dumps({"source": 5, "lessonId": self.lessonid}),
            proxies={"http": None, "https": None},
        )
        if self.dev_recorder:
            self.dev_recorder.record("checkin_class", dict_result(r.text), "Class checkin response")
        set_auth = r.headers.get("Set-Auth", None)
        times = 1
        while not set_auth and times <= 3:
            set_auth = r.headers.get("Set-Auth", None)
            times += 1
            time.sleep(1)
        self.headers["Authorization"] = "Bearer %s" % set_auth
        checkin_data = dict_result(r.text).get("data", {})
        identity_id = checkin_data.get("identityId")
        if identity_id is not None:
            self.identity_id = str(identity_id)
        return checkin_data["lessonToken"]

    def on_message(self, wsapp, message):
        data = dict_result(message)
        op = data.get("op")
        if self.dev_recorder:
            self.dev_recorder.record(f"ws_message_{op}", data, f"Received WS OP: {op}")
        if op == "hello":
            timeline = data.get("timeline", [])
            presentations = {
                slide.get("pres")
                for slide in timeline
                if isinstance(slide, dict) and slide.get("type") == "slide" and slide.get("pres")
            }
            current_presentation = data.get("presentation")
            if current_presentation:
                presentations.add(current_presentation)
            for presentationid in presentations:
                self.get_problems(presentationid)
            self._handle_presentation_change(data)
            self.unlocked_problem = data.get("unlockedproblem", [])
            for problemid in self.unlocked_problem:
                self._current_problem(wsapp, problemid)
        elif op == "unlockproblem":
            problem = data.get("problem", {})
            problem_id = self._resolve_problem_id(problem)
            limit = problem.get("limit")
            self._notify_problem_result(problem_id, problem.get("result"))
            self._notify_problem_release(problem_id, limit)
        elif op == "lessonfinished":
            meg = "%s下课了" % self.lessonname
            self.add_message(meg, 7)
            if self.dev_recorder:
                self.dev_recorder.close()
            wsapp.close()
        elif op == "presentationupdated":
            self.get_problems(data.get("presentation"))
            self._handle_presentation_change(data)
        elif op == "presentationcreated":
            self.get_problems(data.get("presentation"))
            self._handle_presentation_change(data)
        elif op == "slidenav":
            slide_data = data.get("slide")
            if isinstance(slide_data, dict):
                self._handle_presentation_change(slide_data)

            unlocked = data.get("unlockedproblem", [])
            if isinstance(unlocked, list):
                for pid_raw in unlocked:
                    pid = self._normalize_problem_id(pid_raw)
                    if not pid:
                        continue
                    if pid in self.notified_problems:
                        continue
                    if pid in self.problem_info_requested:
                        continue
                    self.problem_info_requested.add(pid)
                    self._current_problem(wsapp, pid)
        elif op == "newdanmu" and self.config["auto_danmu"]:
            current_content = data["danmu"].lower()
            uid = data["userid"]
            sent_danmu_user = self.user_cls(uid)
            if sent_danmu_user in self.classmates_ls:
                for i in self.classmates_ls:
                    if i == sent_danmu_user:
                        meg = "%s课程的%s%s发送了弹幕：%s" % (self.lessonname, i.sno, i.name, data["danmu"])
                        self.add_message(meg, 2)
                        break
            else:
                self.classmates_ls.append(sent_danmu_user)
                sent_danmu_user.get_userinfo(self.classroomid, self.headers, self.config)
                meg = "%s课程的%s%s发送了弹幕：%s" % (
                    self.lessonname,
                    sent_danmu_user.sno,
                    sent_danmu_user.name,
                    data["danmu"],
                )
                self.add_message(meg, 2)
            now = time.time()
            try:
                same_content_ls = self.danmu_dict[current_content]
            except KeyError:
                self.danmu_dict[current_content] = []
                same_content_ls = self.danmu_dict[current_content]
            for i in same_content_ls:
                if now - i > 60:
                    same_content_ls.remove(i)
            if current_content not in self.sent_danmu_dict.keys() or now - self.sent_danmu_dict[current_content] > 60:
                if len(same_content_ls) + 1 >= self.config["danmu_config"]["danmu_limit"]:
                    self.send_danmu(current_content)
                    same_content_ls = []
                    self.sent_danmu_dict[current_content] = now
                else:
                    same_content_ls.append(now)
        elif op == "callpaused":
            meg = "%s点名了，点到了：%s" % (self.lessonname, data["name"])
            if self.user_uname == data["name"]:
                self.add_message(meg, 5)
            else:
                self.add_message(meg, 6)
        elif op == "probleminfo":
            raw_limit = data.get("limit")
            time_left = None
            try:
                limit_int = int(raw_limit)
            except (TypeError, ValueError):
                limit_int = None
            if limit_int == -1:
                time_left = -1
            elif limit_int is not None:
                try:
                    delta = int(data.get("now", 0)) - int(data.get("dt", 0))
                    time_left = int(limit_int - delta / 1000)
                except Exception:
                    time_left = limit_int
            problem_id = self._resolve_problem_id(data)
            if problem_id in self.problem_info_requested:
                self.problem_info_requested.discard(problem_id)
            self._notify_problem_result(problem_id, data.get("result"))
            if self._is_problem_answered(problem_id):
                self._mark_problem_answered(problem_id, result=data.get("result"))
            self._notify_problem_release(problem_id, time_left)

    def _current_problem(self, wsapp, promblemid):
        query_problem = {"op": "probleminfo", "lessonid": self.lessonid, "problemid": promblemid, "msgid": 1}
        wsapp.send(json.dumps(query_problem))

    def start_lesson(self, callback):
        self.auth = self.checkin_class()
        rtn = self.get_lesson_info()
        teacher = rtn["teacher"]["name"]
        title = rtn["title"]
        timestamp = rtn["startTime"] // 1000
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        if hasattr(self.main_ui, "get_course_row_count"):
            index = self.main_ui.get_course_row_count()
        elif hasattr(self.main_ui, "tableWidget"):
            index = self.main_ui.tableWidget.rowCount()
        else:
            index = 0
        self.add_course([self.lessonname, title, teacher, time_str], index)
        ws_url = build_server_url("/wsapp/", self.config, ws=True)
        self.wsapp = websocket.WebSocketApp(url=ws_url, header=self.headers, on_open=self.on_open, on_message=self.on_message)
        self.wsapp.run_forever()
        meg = "%s监听结束" % self.lessonname
        self.add_message(meg, 7)
        self.del_course(index)
        return callback(self)

    def send_danmu(self, content):
        url = build_server_url("/api/v3/lesson/danmu/send", self.config)
        data = {
            "extra": "",
            "fromStart": "50",
            "lessonId": self.lessonid,
            "message": content,
            "requiredCensor": False,
            "showStatus": True,
            "target": "",
            "userName": "",
            "wordCloud": True,
        }
        r = requests.post(url=url, headers=self.headers, data=json.dumps(data), proxies={"http": None, "https": None})
        if dict_result(r.text)["code"] == 0:
            meg = "%s弹幕发送成功！内容：%s" % (self.lessonname, content)
        else:
            meg = "%s弹幕发送失败！内容：%s" % (self.lessonname, content)
        self.add_message(meg, 1)

    def get_lesson_info(self):
        url = build_server_url("/api/v3/lesson/basic-info", self.config)
        r = requests.get(url=url, headers=self.headers, proxies={"http": None, "https": None})
        return dict_result(r.text)["data"]
