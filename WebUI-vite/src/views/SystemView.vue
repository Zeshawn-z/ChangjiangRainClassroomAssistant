<script setup>
import { computed } from "vue";
import { useAppStore } from "../store";

const store = useAppStore();

const overview = computed(() => store.state.overview || {});
const rows = computed(() => overview.value.users || []);
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
  </section>
</template>
