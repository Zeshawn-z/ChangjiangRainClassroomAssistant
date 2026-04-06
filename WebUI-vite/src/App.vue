<script setup>
import { computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { useAppStore } from "./store";

const route = useRoute();
const store = useAppStore();

const currentTitle = computed(() => {
  if (route.path.includes("/users")) return "用户管理";
  if (route.path.includes("/config")) return "配置管理";
  return "系统管理";
});

const updatedText = computed(() => {
  if (!store.state.lastUpdatedAt) return "尚未刷新";
  return new Date(store.state.lastUpdatedAt).toLocaleString();
});

async function refreshAll() {
  try {
    await store.refreshAll();
  } catch (err) {
    ElMessage.error(`刷新失败: ${err?.message || err}`);
  }
}

onMounted(async () => {
  try {
    await store.init();
    store.startPolling(5000);
  } catch (err) {
    ElMessage.error(`初始化失败: ${err?.message || err}`);
  }
});

onUnmounted(() => {
  store.stopPolling();
});
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header" height="auto">
      <div class="brand-block">
        <h1>RainClassroomAssistant</h1>
        <p>Linux 后台多用户管理中心</p>
      </div>
      <div class="head-right">
        <div class="head-meta">当前页面: {{ currentTitle }} | 最近刷新: {{ updatedText }}</div>
        <el-button type="primary" @click="refreshAll">立即刷新</el-button>
      </div>
    </el-header>

    <el-menu :default-active="route.path" mode="horizontal" router class="main-navbar">
      <el-menu-item index="/system">系统管理</el-menu-item>
      <el-menu-item index="/users">用户管理</el-menu-item>
      <el-menu-item index="/config">配置管理</el-menu-item>
    </el-menu>

    <el-main class="app-main">
      <el-alert
        v-if="store.state.lastError"
        :title="`最近一次请求报错: ${store.state.lastError}`"
        type="error"
        show-icon
        :closable="false"
        class="error-alert"
      />
      <RouterView />
    </el-main>
  </el-container>
</template>
