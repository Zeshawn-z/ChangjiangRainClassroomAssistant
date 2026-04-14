<script setup>
import { computed, onMounted, onUnmounted, reactive, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useAppStore } from "../store";

const store = useAppStore();
const weekdayText = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

function buildEmptyRuntime() {
  return {
    is_active: false,
    thread_alive: false,
    courses: [],
    messages: [],
    current_ppt: { image_path: "", info_text: "" },
    problems: [],
  };
}

function getLogEventText(row) {
  const eventName = row?.event || "message";
  if (eventName === "message") {
    return `消息(${row?.type ?? 0})`;
  }
  if (eventName === "course_added") return "课程加入";
  if (eventName === "course_removed") return "课程移除";
  if (eventName === "ppt_updated") return "PPT更新";
  if (eventName === "problem_snapshot") return "题目快照";
  return eventName;
}

function getLogContentText(row) {
  if (!row) return "";
  if (row.message) return row.message;
  if (row.lesson_name && row.problem_id) {
    return `${row.lesson_name} #${row.problem_id}`;
  }
  if (row.info_text) return row.info_text;
  if (row.course?.course_name || row.course?.title) {
    return `${row.course?.course_name || ""} ${row.course?.title || ""}`.trim();
  }
  return "";
}

function getLogTagType(row) {
  if (!row) return "info";
  if (row.event === "message") {
    if (row.type === 4) return "danger";
    if (row.type === 7) return "warning";
    return "info";
  }
  if (row.event === "problem_snapshot") return "success";
  return "info";
}

const ui = reactive({
  newUserName: "",
  newUserServer: "",
  selectedUserId: "",
  sessionidInput: "",
  scheduleDraft: [],
  addWeekday: 0,
  addStart: "08:00",
  addEnd: "10:00",
  addEnabled: true,
  profile: {
    name: "",
    server: "",
    enabled: true,
    auto_schedule: true,
  },
  loginState: {
    status: "not_started",
    error: "",
    qr_base64: "",
  },
  runtime: buildEmptyRuntime(),
  pptImageVersion: Date.now(),
  logs: [],
  logsLimit: 120,
  logsKeyword: "",
  logsStateOnly: false,
  logsLoading: false,
  runtimeLoading: false,
  scheduleDirty: false,
  bindingFromUser: false,
});

function normalizeHm(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";

  let hourText = "";
  let minuteText = "";

  if (text.includes(":")) {
    const parts = text.split(":");
    if (parts.length !== 2) return "";
    [hourText, minuteText] = parts;
  } else if (/^\d{3,4}$/.test(text)) {
    hourText = text.slice(0, text.length - 2);
    minuteText = text.slice(-2);
  } else {
    return "";
  }

  const hour = Number(hourText);
  const minute = Number(minuteText);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return "";
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return "";

  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function normalizeScheduleDraft() {
  const normalized = [];
  for (let i = 0; i < ui.scheduleDraft.length; i += 1) {
    const item = ui.scheduleDraft[i] || {};
    const start = normalizeHm(item.start);
    const end = normalizeHm(item.end);
    if (!start || !end) {
      ElMessage.error(`第 ${i + 1} 条课表时间无效，请使用 HH:mm（例如 08:07）`);
      return null;
    }

    normalized.push({
      weekday: Number(item.weekday || 0),
      start,
      end,
      enabled: !!item.enabled,
    });
  }
  return normalized;
}

let loginTimer = null;

const users = computed(() => store.state.users || []);
const selectedUser = computed(() => users.value.find((u) => u.id === ui.selectedUserId) || null);

function buildLogKey(row) {
  if (!row) return "";
  return [
    row.time || row.updated_at || "",
    row.event || "",
    row.type ?? "",
    row.message || "",
    row.lesson_name || "",
    row.problem_id || "",
  ].join("|");
}

function getPptImageUrl() {
  if (!selectedUser.value || !ui.runtime.current_ppt?.image_path) {
    return "";
  }
  return `/api/users/${selectedUser.value.id}/ppt/image?t=${ui.pptImageVersion}`;
}

function syncSelectedUser() {
  if (!users.value.length) {
    ui.selectedUserId = "";
    return;
  }
  if (!ui.selectedUserId || !users.value.some((u) => u.id === ui.selectedUserId)) {
    ui.selectedUserId = users.value[0].id;
  }
}

function bindFromUser(user, options = {}) {
  const forceSchedule = !!options.forceSchedule;
  if (!user) {
    ui.runtime = buildEmptyRuntime();
    ui.pptImageVersion = Date.now();
    ui.logs = [];
    return;
  }
  ui.bindingFromUser = true;
  ui.profile.name = user.name || "";
  ui.profile.server = user.server || store.state.servers?.[0]?.key || "changjiang";
  ui.profile.enabled = !!user.enabled;
  ui.profile.auto_schedule = !!user.auto_schedule;
  ui.sessionidInput = "";
  if (forceSchedule || !ui.scheduleDirty) {
    ui.scheduleDraft = JSON.parse(JSON.stringify(user.schedule || []));
    ui.scheduleDirty = false;
  }
  ui.bindingFromUser = false;
}

watch(
  () => users.value,
  () => {
    syncSelectedUser();
  },
  { deep: true, immediate: true }
);

watch(
  () => ui.selectedUserId,
  () => {
    bindFromUser(selectedUser.value, { forceSchedule: true });
    refreshLoginState();
    refreshRuntime();
    refreshLogs();
  }
);

watch(
  () => selectedUser.value,
  (user) => {
    if (!user || user.id !== ui.selectedUserId) return;
    bindFromUser(user);
  },
  { deep: true }
);

watch(
  () => ui.scheduleDraft,
  () => {
    if (ui.bindingFromUser) return;
    ui.scheduleDirty = true;
  },
  { deep: true }
);

watch(
  () => store.state.servers,
  (servers) => {
    if (!servers.length) return;
    if (!ui.newUserServer) {
      ui.newUserServer = servers[0].key;
    }
    if (!ui.profile.server) {
      ui.profile.server = servers[0].key;
    }
  },
  { deep: true, immediate: true }
);

async function refreshLoginState() {
  if (!ui.selectedUserId) return;
  try {
    const data = await store.api.getLoginState(ui.selectedUserId);
    ui.loginState = data.state || { status: "not_started" };
    if (ui.loginState.status === "success") {
      await store.refreshUsers();
      await store.refreshOverview();
    }
  } catch (err) {
    ui.loginState = { status: "error", error: err?.message || String(err) };
  }
}

async function refreshRuntime() {
  if (!ui.selectedUserId) {
    ui.runtime = buildEmptyRuntime();
    return;
  }
  ui.runtimeLoading = true;
  try {
    const prevPath = ui.runtime.current_ppt?.image_path || "";
    const data = await store.api.getUserRuntime(ui.selectedUserId);
    ui.runtime = data.runtime || buildEmptyRuntime();
    const currentPath = ui.runtime.current_ppt?.image_path || "";
    if (currentPath !== prevPath) {
      ui.pptImageVersion = Date.now();
    }
  } catch {
    ui.runtime = buildEmptyRuntime();
  } finally {
    ui.runtimeLoading = false;
  }
}

async function refreshLogs() {
  if (!ui.selectedUserId) {
    ui.logs = [];
    return;
  }
  ui.logsLoading = true;
  try {
    const data = await store.api.getUserLogs(ui.selectedUserId, {
      limit: ui.logsLimit,
      keyword: ui.logsKeyword.trim(),
      types: ui.logsStateOnly ? "7" : "",
    });
    ui.logs = (data.logs || [])
      .filter((row) => !["session_state", "system_event"].includes(row?.event))
      .slice()
      .reverse()
      .map((row) => ({ ...row, _key: buildLogKey(row) }));
  } catch {
    ui.logs = [];
  } finally {
    ui.logsLoading = false;
  }
}

async function createUser() {
  const name = ui.newUserName.trim();
  if (!name) {
    ElMessage.warning("请输入用户名称");
    return;
  }
  await store.createUser(name, ui.newUserServer);
  ui.newUserName = "";
  syncSelectedUser();
  bindFromUser(selectedUser.value);
  ElMessage.success("用户已新增");
}

async function deleteCurrentUser() {
  if (!selectedUser.value) return;
  try {
    await ElMessageBox.confirm("确认删除当前用户？", "确认操作", {
      type: "warning",
      confirmButtonText: "确认",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  const oldId = selectedUser.value.id;
  await store.deleteUser(oldId);
  if (ui.selectedUserId === oldId) {
    ui.selectedUserId = "";
    syncSelectedUser();
  }
  ElMessage.success("用户已删除");
}

async function saveProfile() {
  if (!selectedUser.value) return;
  await store.updateProfile(selectedUser.value.id, {
    name: ui.profile.name,
    server: ui.profile.server,
    enabled: ui.profile.enabled,
    auto_schedule: ui.profile.auto_schedule,
  });
  ElMessage.success("基础信息已保存");
}

async function saveSession() {
  if (!selectedUser.value) return;
  await store.setSession(selectedUser.value.id, ui.sessionidInput.trim());
  ui.sessionidInput = "";
  ElMessage.success("session 已保存");
}

async function checkLogin() {
  if (!selectedUser.value) return;
  const data = await store.api.checkLogin(selectedUser.value.id);
  if (data.ok) {
    ElMessage.success(`登录有效: ${data.message}`);
  } else {
    ElMessage.error(`登录无效: ${data.message}`);
  }
}

async function startLogin() {
  if (!selectedUser.value) return;
  await store.api.startLogin(selectedUser.value.id);
  await refreshLoginState();
  ElMessage.success("二维码已生成，请扫码");
}

async function cancelLogin() {
  if (!selectedUser.value) return;
  await store.api.cancelLogin(selectedUser.value.id);
  await refreshLoginState();
}

async function startMonitor() {
  if (!selectedUser.value) return;
  await store.startMonitor(selectedUser.value.id);
  await Promise.all([refreshRuntime(), refreshLogs()]);
  ElMessage.success("已启动监听");
}

async function stopMonitor() {
  if (!selectedUser.value) return;
  await store.stopMonitor(selectedUser.value.id);
  await Promise.all([refreshRuntime(), refreshLogs()]);
  ElMessage.success("已停止监听");
}

function addSchedule() {
  const start = normalizeHm(ui.addStart);
  const end = normalizeHm(ui.addEnd);
  if (!start || !end) {
    ElMessage.warning("请输入有效时间，格式为 HH:mm（例如 08:07）");
    return;
  }

  ui.scheduleDraft.push({
    weekday: Number(ui.addWeekday || 0),
    start,
    end,
    enabled: !!ui.addEnabled,
  });

  ui.addStart = start;
  ui.addEnd = end;
}

function removeSchedule(index) {
  ui.scheduleDraft.splice(index, 1);
}

async function saveSchedule() {
  if (!selectedUser.value) return;
  const normalized = normalizeScheduleDraft();
  if (!normalized) return;

  ui.scheduleDraft = normalized;
  await store.updateSchedule(selectedUser.value.id, normalized);
  bindFromUser(selectedUser.value, { forceSchedule: true });
  ElMessage.success("课表已保存");
}

onMounted(() => {
  loginTimer = setInterval(() => {
    refreshLoginState();
    refreshRuntime();
    refreshLogs();
  }, 3000);
});

onUnmounted(() => {
  if (loginTimer) {
    clearInterval(loginTimer);
    loginTimer = null;
  }
});
</script>

<template>
  <el-row :gutter="12">
    <el-col :xs="24" :md="8" :lg="7">
      <el-card class="page-card" shadow="never">
        <template #header>
          <span>用户列表</span>
        </template>

        <el-form label-position="top">
          <el-form-item label="用户名称">
            <el-input v-model="ui.newUserName" placeholder="新用户名称" />
          </el-form-item>
          <el-form-item label="服务器">
            <el-select v-model="ui.newUserServer" style="width: 100%" placeholder="请选择服务器">
              <el-option v-for="item in store.state.servers" :key="item.key" :value="item.key" :label="`${item.name} (${item.host})`" />
            </el-select>
          </el-form-item>
          <el-button type="primary" style="width: 100%" @click="createUser">新增用户</el-button>
        </el-form>

        <el-divider />

        <el-scrollbar max-height="58vh">
          <div v-if="!users.length" class="empty-note">暂无用户</div>
          <el-card
            v-for="user in users"
            :key="user.id"
            class="user-list-item"
            :class="{ 'is-active': user.id === ui.selectedUserId }"
            shadow="never"
            @click="ui.selectedUserId = user.id"
          >
            <div class="name">{{ user.name }}</div>
            <div class="meta">{{ user.server }} | {{ user.is_active ? "监听中" : "空闲" }}</div>
            <div class="meta">登录: {{ user.has_sessionid ? "已保存" : "未保存" }} | 配置: {{ user.use_custom_config ? "自定义" : "默认" }}</div>
          </el-card>
        </el-scrollbar>
      </el-card>
    </el-col>

    <el-col :xs="24" :md="16" :lg="17">
      <el-empty v-if="!selectedUser" description="请选择左侧用户进行管理" />

      <div v-else>
        <el-card class="page-card" shadow="never">
          <div class="page-title-row">
            <h3>{{ selectedUser.name }} ({{ selectedUser.id.slice(0, 8) }})</h3>
            <el-space wrap>
              <el-tag :type="ui.runtime.is_active ? 'success' : 'info'">{{ ui.runtime.is_active ? "监听中" : "空闲" }}</el-tag>
              <el-tag :type="ui.runtime.thread_alive ? 'success' : 'info'">线程{{ ui.runtime.thread_alive ? "存活" : "未运行" }}</el-tag>
              <el-button type="primary" @click="startMonitor">手动开始监听</el-button>
              <el-button @click="stopMonitor">手动停止监听</el-button>
              <el-button type="danger" plain @click="deleteCurrentUser">删除用户</el-button>
            </el-space>
          </div>
        </el-card>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :lg="12">
            <el-card class="page-card" shadow="never">
              <template #header>
                <span>基础信息</span>
              </template>
              <el-form label-position="left" label-width="130px">
                <el-form-item label="名称"><el-input v-model="ui.profile.name" /></el-form-item>
                <el-form-item label="服务器">
                  <el-select v-model="ui.profile.server" style="width: 100%">
                    <el-option v-for="item in store.state.servers" :key="item.key" :value="item.key" :label="`${item.name} (${item.host})`" />
                  </el-select>
                </el-form-item>
                <el-form-item label="启用用户"><el-switch v-model="ui.profile.enabled" /></el-form-item>
                <el-form-item label="周课表自动启停"><el-switch v-model="ui.profile.auto_schedule" /></el-form-item>
              </el-form>
              <el-alert
                :title="`当前配置模式: ${selectedUser.use_custom_config ? '用户自定义配置' : '继承系统默认配置'}`"
                type="info"
                :closable="false"
                class="row-gap"
              />
              <el-button @click="saveProfile">保存基础信息</el-button>
            </el-card>
          </el-col>

          <el-col :xs="24" :lg="12">
            <el-card class="page-card" shadow="never">
              <template #header>
                <span>登录管理</span>
              </template>
              <el-form label-position="top">
                <el-form-item label="sessionid">
                  <el-input v-model="ui.sessionidInput" placeholder="可手动粘贴 sessionid" />
                </el-form-item>
                <el-space wrap>
                  <el-button @click="saveSession">保存 session</el-button>
                  <el-button @click="checkLogin">校验登录状态</el-button>
                </el-space>
                <el-divider />
                <el-space wrap>
                  <el-button type="primary" @click="startLogin">Web 扫码登录</el-button>
                  <el-button @click="cancelLogin">取消扫码</el-button>
                </el-space>
              </el-form>
              <div style="margin-top: 8px">
                <el-tag type="info">扫码状态: {{ ui.loginState.status || "not_started" }}</el-tag>
                <el-tag v-if="ui.loginState.error" type="danger" style="margin-left: 8px">{{ ui.loginState.error }}</el-tag>
              </div>
              <img v-if="ui.loginState.qr_base64" :src="`data:image/png;base64,${ui.loginState.qr_base64}`" class="qr-image" alt="登录二维码" />
            </el-card>
          </el-col>
        </el-row>

        <el-card class="page-card" shadow="never">
          <template #header>
            <span>周课表（循环）</span>
          </template>
          <div class="schedule-row">
            <el-select v-model="ui.addWeekday" style="width: 100%">
              <el-option v-for="(text, idx) in weekdayText" :key="text" :value="idx" :label="text" />
            </el-select>
            <el-input v-model="ui.addStart" style="width: 100%" placeholder="开始时间（如 08:07）" />
            <el-input v-model="ui.addEnd" style="width: 100%" placeholder="结束时间（如 09:52）" />
            <el-switch v-model="ui.addEnabled" active-text="启用" inactive-text="停用" />
            <el-button @click="addSchedule">添加</el-button>
          </div>

          <el-alert
            title="时间支持任意分钟输入，格式建议 HH:mm，也支持 4 位数字（例如 0807）"
            type="info"
            :closable="false"
            class="row-gap"
          />

          <el-table :data="ui.scheduleDraft" stripe empty-text="暂无课表项">
            <el-table-column label="星期" min-width="100">
              <template #default="{ row }">
                <el-select v-model="row.weekday" size="small" style="width: 100%">
                  <el-option v-for="(text, idx) in weekdayText" :key="text" :value="idx" :label="text" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="开始" min-width="120">
              <template #default="{ row }">
                <el-input v-model="row.start" size="small" placeholder="HH:mm" />
              </template>
            </el-table-column>
            <el-table-column label="结束" min-width="120">
              <template #default="{ row }">
                <el-input v-model="row.end" size="small" placeholder="HH:mm" />
              </template>
            </el-table-column>
            <el-table-column label="状态" min-width="100">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ $index }">
                <el-button type="danger" link @click="removeSchedule($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-button style="margin-top: 10px" @click="saveSchedule">保存课表</el-button>
        </el-card>

        <el-row :gutter="12" class="row-gap">
          <el-col :xs="24" :lg="12">
            <el-card class="page-card" shadow="never">
              <template #header>
                <span>PPT 与题目预览</span>
              </template>
              <el-alert
                :title="ui.runtime.current_ppt?.info_text || '暂无 PPT'"
                type="info"
                :closable="false"
                class="row-gap"
              />
              <img
                v-if="ui.runtime.current_ppt?.image_path"
                :src="getPptImageUrl()"
                class="ppt-image"
                alt="当前PPT"
              />
              <div class="mini-list" style="margin-top: 10px">
                <div v-if="!(ui.runtime.problems || []).length" class="empty-note">暂无题目</div>
                <div v-for="item in (ui.runtime.problems || []).slice(-20).reverse()" :key="`${item.problem_id}-${item.lesson_name}`" class="item-row">
                  <strong>{{ item.lesson_name }}</strong><br />
                  题号: {{ item.problem_id }}<br />
                  {{ item.problem?.body || "" }}<br />
                  {{ Array.isArray(item.problem?.options) ? item.problem.options.map((o) => `${o.key}:${o.value}`).join(" | ") : "" }}
                </div>
              </div>
            </el-card>
          </el-col>

          <el-col :xs="24" :lg="12">
            <el-card class="page-card" shadow="never">
              <template #header>
                <span>当前课程</span>
              </template>
              <div class="mini-list course-list">
                <div v-if="!(ui.runtime.courses || []).length" class="empty-note">暂无课程</div>
                <div v-for="course in ui.runtime.courses || []" :key="`${selectedUser.id}-${course.row_index}`" class="item-row">
                  {{ course.course_name }} | {{ course.title }} | {{ course.teacher }}
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <el-card class="page-card" shadow="never">
          <template #header>
            <div class="page-title-row" style="margin-bottom: 0">
              <span>运行日志</span>
              <el-space>
                <el-select v-model="ui.logsLimit" style="width: 120px" @change="refreshLogs">
                  <el-option :value="80" label="80条" />
                  <el-option :value="120" label="120条" />
                  <el-option :value="200" label="200条" />
                  <el-option :value="400" label="400条" />
                </el-select>
                <el-input
                  v-model="ui.logsKeyword"
                  clearable
                  style="width: 220px"
                  placeholder="关键词筛选"
                  @keyup.enter="refreshLogs"
                />
                <el-switch v-model="ui.logsStateOnly" active-text="仅监听事件" @change="refreshLogs" />
                <el-button :loading="ui.logsLoading" style="min-width: 88px" @click="refreshLogs">刷新日志</el-button>
              </el-space>
            </div>
          </template>
          <div class="mini-list log-list">
            <div v-if="!ui.logs.length" class="empty-note">暂无日志</div>
            <div v-for="msg in ui.logs" :key="msg._key" class="item-row">
              <div class="page-title-row" style="margin: 0 0 4px 0">
                <small>[{{ msg.time || msg.updated_at || "-" }}]</small>
                <el-tag size="small" :type="getLogTagType(msg)">{{ getLogEventText(msg) }}</el-tag>
              </div>
              <div>{{ getLogContentText(msg) }}</div>
            </div>
          </div>
        </el-card>
      </div>
    </el-col>
  </el-row>
</template>
