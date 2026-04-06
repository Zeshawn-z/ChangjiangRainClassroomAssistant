# RainClassroomAssitant

一个基于 Python + PyQt5 的雨课堂桌面辅助工具，用于课程监听、消息提醒、PPT 预览与自动化处理。

## 功能特性

- 自动签到
- 自动答题（支持课堂中发布的常见题型）
- 自动弹幕跟发（阈值触发）
- 点名、题目发布等场景的语音提示
- 多课程并行监听
- PPT 页面预览与本地保存
- 一次性定时任务（可配置下一次开始/结束监听时间）
- 可切换服务器节点（主窗口可选）
  - 长江雨课堂（默认）
  - 雨课堂主站
  - 黄河雨课堂
  - 荷塘雨课堂

## 免责声明

1. 本项目仅用于学习研究、个人技术交流与自动化开发实践。
2. 使用者应遵守所在学校、课程平台与相关法律法规的规定。
3. 严禁将本项目用于作弊、破坏教学秩序、批量刷课、攻击平台或任何违法违规用途。
4. 因不当使用本项目产生的任何后果，由使用者自行承担，项目作者与贡献者不承担任何责任。
5. 平台接口与策略可能随时变更，项目不保证持续可用性、稳定性或兼容性。

## 环境要求

- Windows 10/11
- Python 3.10 及以上

## 后台版（跨平台，新增）

当前分支新增了无 Qt 的后台运行模式，支持：

- 多用户并行监听
- 周课表自动启停（按周循环）
- WebUI 管理用户、配置、登录态、监听状态
- Web 扫码登录与终端二维码扫码登录
- 题目与 PPT 预览（WebUI）

### 启动方式

1. 安装依赖

  pip install -r requirements.txt

2. 启动后台 + WebUI

  python RainClassroomAssistantLinux.py serve --host 0.0.0.0 --port 18080

3. 浏览器访问

  http://127.0.0.1:18080

### WebUI 前端开发（Vite + Vue3）

前端源码位于 WebUI-vite，使用 Vite 管理：

1. 安装前端依赖

  cd WebUI-vite
  npm install

2. 本地开发（热更新）

  npm run dev

默认开发地址为 http://127.0.0.1:5173，已代理 /api 到 http://127.0.0.1:18080。

3. 构建发布版本

  npm run build

构建产物会输出到 WebUI/dist，后端启动时仅托管该目录（已移除旧单文件 UI 回退）。

### 常用命令

- 创建用户

  python RainClassroomAssistantLinux.py add-user --name "张三" --server changjiang

- 查看用户

  python RainClassroomAssistantLinux.py list-users

- 终端扫码登录（会输出二维码）

  python RainClassroomAssistantLinux.py terminal-login --user <user_id> --timeout 240

- 查看某个用户最近日志（监听状态/启停事件/运行消息）

  python RainClassroomAssistantLinux.py logs --user <user_id> --limit 120

- 仅查看监听状态类日志（消息类型 7）

  python RainClassroomAssistantLinux.py logs --user <user_id> --types 7 --limit 200

### 周课表说明

WebUI 中每个用户可配置多条时间段规则：

- weekday: 0-6 分别表示周一到周日
- start/end: HH:MM 格式
- enabled: 是否启用该条规则

系统会按规则循环判断并自动开始/停止监听。支持跨天时段（例如 23:00-01:00）。

## 本地运行

1. 安装依赖

	pip install -r requirements.txt

2. 启动程序

	python RainClassroomAssistant.py

3. 在主窗口顶部选择服务器（默认长江）
4. 点击登录，扫码完成授权
5. 点击启用开始监听

说明：切换服务器后会自动清空当前 session 并弹出登录窗口，需要重新扫码。

## 打包 EXE

本地打包命令（单文件 + 图标）：

pyinstaller -F -w -i .\UI\Image\favicon.ico .\RainClassroomAssistant.py

产物默认在 dist 目录下。

## GitHub Actions 自动构建与发布

仓库已提供工作流文件：

- .github/workflows/build-exe.yml

能力包括：

- 自动构建 Windows 单文件 EXE（含图标）
- 自动生成或使用指定语义化标签（例如 v1.0.0）
- 自动创建 Release 并上传 EXE 附件

## LLM 配置指南

在主界面点击 配置，在 LLM 配置 区域填写以下参数：

- API Key：模型平台密钥
- Base URL：OpenAI 兼容接口根地址
- Thinking Model：默认解题模型（先用它判断是否缺图）
- VL Model：视觉解题模型（收到缺图标记时再调用）
- 答题请求超时：单题请求最大等待时长（秒）
- 连接测试读取超时：点击测试按钮时的网络读取超时（秒）
- 保存 LLM 调用日志：建议开启，便于复盘

建议配置：

- Base URL 推荐填写到 v1，例如 https://api.siliconflow.cn/v1
- 答题请求超时建议 120 秒起
- 先用轻量模型验证稳定性，再切换更强模型

说明：

- 程序会自动处理 Base URL 尾部 v1（未填写时自动补齐）
- 点击 测试 LLM 连接 会分别验证 Thinking/VL 两个模型
- 默认先调用 Thinking 模型；若其返回特殊标记 __NEED_PPT_IMAGE__，再把当前页 PPT 图片发给 VL 模型
- 程序会约束模型输出为 JSON 对象格式，减少自由文本导致的解析失败

示例 llm_config：

{
  "api_key": "sk-xxxx",
  "base_url": "https://api.siliconflow.cn/v1",
  "model": "Qwen/Qwen3-32B",
  "thinking_model": "Qwen/Qwen3-32B",
  "vl_model": "Qwen/Qwen3-VL-235B-A22B-Instruct",
  "answer_timeout": 120,
  "connect_timeout": 10,
  "test_timeout": 15,
  "save_log": true
}

## 自动答题流程

1. 监听到题目事件（如 unlockproblem、probleminfo）
2. 进入自动答题调度，检查：
   - 是否开启 auto_answer
   - 该题是否已答过
   - 本地缓存是否已有答案
3. 若无缓存答案且已配置 LLM，则请求模型解题
4. 若题面信息不足，会触发 PPT 图片兜底再请求一次
5. 归一化答案格式（单选/多选/填空）
6. 按延迟策略到时提交答案
7. 成功后标记为已作答，避免重复提交

当前实现的保护机制：

- 题目已答过会跳过重复提交
- 未配置 LLM 且无缓存答案会输出提示
- 对模型输出进行选项字母归一化，降低格式错误概率

## PPT 题目数据格式

题目源自 PPT 接口中的 slides 数据。程序会抽取每页题目信息并写入本地题库文件。

来源结构（简化）：

- data.slides[]
- slide.cover：该页图片 URL
- slide.problem：该页题目对象

本地题库文件路径：

- problems/problems_<lesson_id>.json

本地题目对象结构（核心字段）：

{
  "problemId": "123456",
  "problemType": 1,
  "body": "题干文本",
  "options": [
    {"key": "A", "value": "选项A"},
    {"key": "B", "value": "选项B"}
  ],
  "answers": ["A"],
  "limit": 30,
  "sendTime": 1730000000000,
  "result": null
}

补充说明：

- 若开启 自动保存 PPT，图片会保存到 PPTs/课程名_课程ID/presentationID/slide_x.jpg
- 程序会维护题目与页码、presentation 的映射关系，用于提示与图片兜底

## DevTools 使用说明

启用方式：

1. 打开 配置
2. 勾选 启用 DevTools 记录器
3. 保存后重新开始监听课程

日志位置：

- logs 目录，文件格式为 jsonl（每行一条 JSON 事件）

常见事件：

- session_start / session_end
- ws_open
- ws_message_xxx
- get_ppt
- checkin_class
- answer_problem / answer_response

排错建议：

1. 先确认日志里有 session_start，确保记录器已启用
2. 检查是否收到 ws_message_unlockproblem / ws_message_probleminfo
3. 查看 answer_problem 的 payload 与 answer_response 返回码
4. 若题目无法识别，查看 get_ppt 事件里 slides 与 problem 字段

## 项目结构（节选）

- RainClassroomAssistant.py：程序入口
- UI/MainWindow.py：主窗口与交互逻辑
- UI/Login.py：扫码登录流程
- Scripts/Monitor.py：课程监听调度
- Scripts/lesson：课程 websocket、PPT、答题逻辑
- Scripts/Utils.py：公共工具与配置
