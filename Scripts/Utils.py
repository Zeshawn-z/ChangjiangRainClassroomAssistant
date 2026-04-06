import threading
import pyttsx3
import json
import urllib3
import requests
import random
import os
import sys
from pathlib import Path

lock = threading.Lock()

YUKETANG_SERVERS = {
    "changjiang": {"name": "长江雨课堂", "host": "changjiang.yuketang.cn"},
    "www": {"name": "雨课堂(主站)", "host": "www.yuketang.cn"},
    "huanghe": {"name": "黄河雨课堂", "host": "huanghe.yuketang.cn"},
    "pro": {"name": "荷塘雨课堂", "host": "pro.yuketang.cn"},
}
DEFAULT_SERVER_KEY = "changjiang"


def normalize_server_key(server_key):
    key = str(server_key or DEFAULT_SERVER_KEY).strip().lower()
    if key not in YUKETANG_SERVERS:
        return DEFAULT_SERVER_KEY
    return key


def get_server_key(config=None):
    if isinstance(config, dict):
        return normalize_server_key(config.get("server"))
    return normalize_server_key(config)


def get_server_host(config=None):
    key = get_server_key(config)
    return YUKETANG_SERVERS[key]["host"]


def build_server_url(path, config=None, ws=False):
    host = get_server_host(config)
    scheme = "wss" if ws else "https"
    normalized_path = str(path or "")
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    return f"{scheme}://{host}{normalized_path}"

def say_something(text):
    # 带线程锁的语音函数
    lock.acquire()
    pyttsx3.speak(text)
    lock.release()
    
def dict_result(text):
    # json string 转 dict object
    return dict(json.loads(text))

def test_network():
    # 网络状态测试
    try:
        http = urllib3.PoolManager()
        http.request('GET', 'https://baidu.com')
        return True
    except:
        return False

def calculate_waittime(limit, type, custom_time):
    # 计算答题等待时间
    '''
    type
    1: 随机
    2: 自定义
    '''
    def default_calculate(limit):
        # 默认的随机答题等待时间算法
        if limit == -1:
            wait_time = random.randint(5,20)
        else:
            if limit > 15:
                wait_time = random.randint(5,limit-10)
            else:
                wait_time = 0
        return wait_time

    if type == 1:
        wait_time = default_calculate(limit)
    elif type == 2:
        # 如果自定义等待时间超过当前题目的剩余时间，则采用默认算法
        if custom_time > limit:
            wait_time = default_calculate(limit)
        else:
            wait_time = custom_time
    return wait_time

def get_initial_data():
    # 默认配置信息
    initial_data = \
    {
        "sessionid":"",
        "server":"changjiang",
        "auto_danmu":True,
        "danmu_config":{
            "danmu_limit":5
        },
        "audio_on":True,
        "audio_config":{
            "audio_type":{
                "send_danmu":False,
                "others_danmu":False,
                "receive_problem":True,
                "answer_result":True,
                "im_called":True,
                "others_called":True,
                "course_info":True,
                "network_info":True
            }
        },
        "auto_answer":True,
        "answer_config":{
            "answer_delay":{
                "type":1,
                "custom":{
                    "time":0
                }
            }
        },
        "llm_config": {
            "api_key": "",
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3-VL-235B-A22B-Thinking",
            "thinking_model": "Qwen/Qwen3-VL-235B-A22B-Thinking",
            "vl_model": "Qwen/Qwen3-VL-235B-A22B-Thinking",
            "answer_timeout": 120,
            "connect_timeout": 10,
            "test_timeout": 15,
            "save_log": True
        },
        "auto_save_ppt": False,
        "enable_devtools": False,
        "debug_mode":False
    }
    return initial_data

def get_config_path():
    # 获取配置文件路径
    return os.path.join(get_config_dir(), "config.json")

def get_config_dir():
    # 获取配置文件所在文件夹（跨平台）
    return get_runtime_data_dir()


def get_runtime_data_dir():
    app_name = "RainClassroomAssistant"
    if os.name == "nt":
        base_dir = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base_dir = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return os.path.join(base_dir, app_name)


def ensure_runtime_data_dir():
    path = get_runtime_data_dir()
    os.makedirs(path, exist_ok=True)
    return path


def get_users_state_path():
    return os.path.join(ensure_runtime_data_dir(), "users_state.json")


def get_users_logs_dir():
    path = os.path.join(ensure_runtime_data_dir(), "user_logs")
    os.makedirs(path, exist_ok=True)
    return path

def get_user_info(sessionid, config=None):
    # 获取用户信息
    headers = {
        "Cookie":"sessionid=%s" % sessionid,
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
    }
    r = requests.get(url=build_server_url("/api/v3/user/basic-info", config),headers=headers,proxies={"http": None,"https":None})
    rtn = dict_result(r.text)
    return (rtn["code"],rtn["data"])

def get_on_lesson(sessionid, config=None):
    # 获取用户当前正在上课列表
    headers = {
        "Cookie":"sessionid=%s" % sessionid,
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
    }
    r = requests.get(build_server_url("/api/v3/classroom/on-lesson", config),headers=headers,proxies={"http": None,"https":None})
    rtn = dict_result(r.text)
    return rtn["data"]["onLessonClassrooms"]

def get_on_lesson_old(sessionid, config=None):
    # 获取用户当前正在上课的列表（旧版）
    headers = {
        "Cookie":"sessionid=%s" % sessionid,
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
    }
    r = requests.get(build_server_url("/v/course_meta/on_lesson_courses", config),headers=headers,proxies={"http": None,"https":None})
    rtn = dict_result(r.text)
    return rtn["on_lessons"]

def resource_path(relative_path):
    # 解决打包exe的图片路径问题
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)