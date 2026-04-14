<script setup>
import { computed, onMounted, onUnmounted, reactive } from "vue";
import { useAppStore } from "../store";

const store = useAppStore();

const overview = computed(() => store.state.overview || {});
const rows = computed(() => overview.value.users || []);

const ui = reactive({
  logs: [],
  logsLoading: false,
  logsLimit: 120,
  logsKeyword: "",
  onlySessionAndMonitor: true,
});

let logsTimer = null;

function buildLogKey(row, index) {
  return [
    row?.time || "",
    row?.event || "",
    row?.action || "",
    row?.status || "",
    row?.source || "",
    row?.user_id || "",
    String(index),
  ].join("|");
}

function getGlobalLogTagType(row) {
  const eventName = String(row?.event || "");
  const action = String(row?.action || "").toLowerCase();
  const status = String(row?.status || "").toLowerCase();

  if (eventName === "session_state") {
    if (status.includes("error") || status.includes("failed") || status.includes("expired")) return "danger";
    if (status.includes("pending") || status.includes("trigger") || status.includes("no-session")) return "warning";
    if (status.includes("ok") || status.includes("success") || status.includes("updated")) return "success";
    return "info";
  }

  if (eventName === "system_event") {
    if (action.includes("failed") || action.includes("timeout")) return "danger";
    if (action.includes("request") || action.includes("pending") || action.includes("blocked")) return "warning";
    if (action.includes("started") || action.includes("stopped") || action.includes("success")) return "success";
    return "info";
  }

  return "info";
}

function getGlobalLogTitle(row) {
  if (!row) return "未知事件";
  if (row.event === "session_state") return `会话 ${row.status || "unknown"}`;
  if (row.event === "system_event") return `系统 ${row.action || "unknown"}`;
  return row.event || "事件";
}

function getGlobalLogDetail(row) {
  if (!row) return "";
  const parts = [];
  parts.push(`用户: ${row.user_name || row.user_id || "-"}`);
  parts.push(`来源: ${row.source || "-"}`);
  if (row.detail) parts.push(String(row.detail));
  return parts.join(" | ");
}

async function refreshGlobalLogs() {
  ui.logsLoading = true;
  try {
    const data = await store.api.getSystemLogs({
      limit: ui.logsLimit,
      keyword: ui.logsKeyword.trim(),
      events: ui.onlySessionAndMonitor ? "system_event,session_state" : "",
    });
    ui.logs = (data.logs || []).slice().reverse().map((row, index) => ({ ...row, _key: buildLogKey(row, index) }));
  } catch {
    ui.logs = [];
  } finally {
    ui.logsLoading = false;
  }
}

onMounted(() => {
  refreshGlobalLogs();
  logsTimer = setInterval(() => {
    refreshGlobalLogs();
  }, 5000);
});

onUnmounted(() => {
  if (logsTimer) {
    clearInterval(logsTimer);
    logsTimer = null;
  }
});
</script>

<template>
  <section>
    <el-row :gutter="12" class="row-gap">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="用户总数" :value="overview.total_users ?? store.state.users.length" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="启用用户" :value="overview.enabled_users ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="运行中监听" :value="overview.active_users ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="调度线程" :value="overview.scheduler_alive ? '运行中' : '已停止'" />
        </el-card>
      </el-col>
    </el-row>

    <el-card class="page-card" shadow="never">
      <div class="page-title-row">
        <h3>全局运行状态</h3>
        <el-button @click="store.refreshOverview">刷新状态</el-button>
      </div>
      <el-space wrap>
        <el-tag type="info">自动调度用户: {{ overview.auto_schedule_users ?? 0 }}</el-tag>
        <el-tag type="info">自定义配置用户: {{ overview.custom_config_users ?? 0 }}</el-tag>
        <el-tag type="info">已登录用户: {{ overview.session_ready_users ?? 0 }}</el-tag>
      </el-space>
      <el-table :data="rows" stripe class="row-gap" style="margin-top: 10px" empty-text="暂无用户">
        <el-table-column prop="name" label="用户" min-width="120" />
        <el-table-column prop="server" label="服务器" min-width="120" />
        <el-table-column label="监听" min-width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "监听中" : "空闲" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="周课表" min-width="100">
          <template #default="{ row }">{{ row.auto_schedule ? "开启" : "关闭" }}</template>
        </el-table-column>
        <el-table-column label="自定义配置" min-width="120">
          <template #default="{ row }">{{ row.use_custom_config ? "是" : "否" }}</template>
        </el-table-column>
        <el-table-column label="登录态" min-width="110">
          <template #default="{ row }">{{ row.has_sessionid ? "已保存" : "未保存" }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
      </el-table>
    </el-card>

    <el-card class="page-card" shadow="never">
      <template #header>
        <div class="page-title-row" style="margin-bottom: 0">
          <span>全局事件日志</span>
          <el-space>
            <el-select v-model="ui.logsLimit" style="width: 120px" @change="refreshGlobalLogs">
              <el-option :value="80" label="80条" />
              <el-option :value="120" label="120条" />
              <el-option :value="200" label="200条" />
              <el-option :value="400" label="400条" />
            </el-select>
            <el-input
              v-model="ui.logsKeyword"
              clearable
              style="width: 240px"
              placeholder="关键词筛选"
              @keyup.enter="refreshGlobalLogs"
            />
            <el-switch v-model="ui.onlySessionAndMonitor" active-text="仅会话/监听" @change="refreshGlobalLogs" />
            <el-button :loading="ui.logsLoading" style="min-width: 88px" @click="refreshGlobalLogs">刷新日志</el-button>
          </el-space>
        </div>
      </template>

      <div class="mini-list log-list">
        <div v-if="!ui.logs.length" class="empty-note">暂无全局事件</div>
        <div v-for="row in ui.logs" :key="row._key" class="item-row">
          <div class="page-title-row" style="margin: 0 0 4px 0">
            <small>[{{ row.time || "-" }}]</small>
            <el-tag size="small" :type="getGlobalLogTagType(row)">{{ getGlobalLogTitle(row) }}</el-tag>
          </div>
          <div>{{ getGlobalLogDetail(row) }}</div>
        </div>
      </div>
    </el-card>
  </section>
</template>
