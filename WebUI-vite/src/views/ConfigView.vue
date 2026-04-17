<script setup>
import { computed, reactive, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import ConfigEditor from "../components/ConfigEditor.vue";
import { useAppStore } from "../store";

const store = useAppStore();

const ui = reactive({
  defaultConfigDraft: {},
  selectedUserId: "",
  userConfigDraft: {},
  userCustomEnabled: false,
  llmTestPrompt: "请用一句话回复：连接测试成功。",
  defaultLlmTestLoading: false,
  userLlmTestLoading: false,
  defaultLlmTestResult: null,
  userLlmTestResult: null,
});

const users = computed(() => store.state.users || []);
const selectedUser = computed(() => users.value.find((u) => u.id === ui.selectedUserId) || null);

watch(
  () => store.state.defaultConfig,
  (value) => {
    ui.defaultConfigDraft = store.cloneData(value || {});
  },
  { deep: true, immediate: true }
);

watch(
  () => users.value,
  (list) => {
    if (!list.length) {
      ui.selectedUserId = "";
      return;
    }
    if (!ui.selectedUserId || !list.some((u) => u.id === ui.selectedUserId)) {
      ui.selectedUserId = list[0].id;
    }
  },
  { deep: true, immediate: true }
);

watch(
  () => selectedUser.value,
  (user) => {
    if (!user) return;
    ui.userCustomEnabled = !!user.use_custom_config;
    ui.userConfigDraft = store.cloneData(user.config || store.state.defaultConfig || {});
  },
  { deep: true, immediate: true }
);

async function saveDefaultConfig() {
  await store.updateDefaultConfig(ui.defaultConfigDraft);
  ElMessage.success("默认配置已保存");
}

async function saveUserConfig() {
  if (!selectedUser.value) return;
  await store.updateUserConfigMode(selectedUser.value.id, { use_custom_config: true });
  await store.updateUserConfig(selectedUser.value.id, ui.userConfigDraft);
  ui.userCustomEnabled = true;
  ElMessage.success("用户配置已保存");
}

async function saveUserConfigMode() {
  if (!selectedUser.value) return;
  await store.updateUserConfigMode(selectedUser.value.id, { use_custom_config: ui.userCustomEnabled });
}

async function clearOverrides() {
  if (!selectedUser.value) return;
  try {
    await ElMessageBox.confirm("确认清空该用户的覆盖配置吗？", "确认操作", {
      type: "warning",
      confirmButtonText: "确认",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  await store.updateUserConfigMode(selectedUser.value.id, {
    use_custom_config: false,
    clear_overrides: true,
  });
  ui.userCustomEnabled = false;
  ElMessage.success("已清空覆盖配置");
}

function normalizeTestResult(payload) {
  return payload?.result || payload || null;
}

async function testDefaultLlm() {
  ui.defaultLlmTestLoading = true;
  try {
    const data = await store.api.testDefaultLlm({
      prompt: ui.llmTestPrompt,
      config: ui.defaultConfigDraft,
    });
    ui.defaultLlmTestResult = normalizeTestResult(data);
    if (data?.ok) {
      ElMessage.success(data?.message || "测试成功");
    } else {
      ElMessage.error(data?.message || "测试失败");
    }
  } catch (err) {
    ui.defaultLlmTestResult = null;
    ElMessage.error(err?.message || String(err));
  } finally {
    ui.defaultLlmTestLoading = false;
  }
}

async function testUserLlm() {
  if (!selectedUser.value) return;
  ui.userLlmTestLoading = true;
  try {
    const data = await store.api.testUserLlm(selectedUser.value.id, {
      prompt: ui.llmTestPrompt,
      config: ui.userConfigDraft,
    });
    ui.userLlmTestResult = normalizeTestResult(data);
    if (data?.ok) {
      ElMessage.success(data?.message || "测试成功");
    } else {
      ElMessage.error(data?.message || "测试失败");
    }
  } catch (err) {
    ui.userLlmTestResult = null;
    ElMessage.error(err?.message || String(err));
  } finally {
    ui.userLlmTestLoading = false;
  }
}

function outputText(result, key) {
  return result?.[key]?.output || "";
}
</script>

<template>
  <section>
    <el-row :gutter="12">
      <el-col :xs="24" :lg="12">
        <el-card class="page-card" shadow="never">
          <template #header>
            <div class="page-title-row">
              <span>默认配置（系统）</span>
              <el-space>
                <el-button :loading="ui.defaultLlmTestLoading" @click="testDefaultLlm">测试模型连通</el-button>
                <el-button type="primary" @click="saveDefaultConfig">保存默认配置</el-button>
              </el-space>
            </div>
          </template>
          <el-alert
            title="新用户默认使用此配置；未启用用户自定义配置的用户会继承这里。"
            type="info"
            :closable="false"
            show-icon
            class="row-gap"
          />
          <el-form label-position="top" class="row-gap">
            <el-form-item label="模型测试 Prompt">
              <el-input
                v-model="ui.llmTestPrompt"
                type="textarea"
                :rows="3"
                placeholder="输入用于模型连通测试的 Prompt"
              />
            </el-form-item>
          </el-form>
          <el-card v-if="ui.defaultLlmTestResult" shadow="never" class="row-gap">
            <template #header>
              <div class="page-title-row" style="margin-bottom: 0">
                <span>默认配置测试结果</span>
                <small>Prompt: {{ ui.defaultLlmTestResult.prompt || "-" }}</small>
              </div>
            </template>
            <el-space wrap>
              <el-tag :type="ui.defaultLlmTestResult.thinking?.ok ? 'success' : 'danger'">
                Thinking: {{ ui.defaultLlmTestResult.thinking?.ok ? "成功" : "失败" }}
              </el-tag>
              <el-tag :type="ui.defaultLlmTestResult.vl?.ok ? 'success' : 'danger'">
                VL: {{ ui.defaultLlmTestResult.vl?.ok ? "成功" : "失败" }}
              </el-tag>
            </el-space>
            <el-descriptions :column="1" border style="margin-top: 10px">
              <el-descriptions-item label="Thinking 模型">
                {{ ui.defaultLlmTestResult.thinking?.model || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 结果">
                {{ ui.defaultLlmTestResult.thinking?.message || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 耗时(ms)">
                {{ ui.defaultLlmTestResult.thinking?.elapsed_ms ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 返回文本">
                <pre class="test-output">{{ outputText(ui.defaultLlmTestResult, "thinking") }}</pre>
              </el-descriptions-item>
              <el-descriptions-item label="VL 模型">
                {{ ui.defaultLlmTestResult.vl?.model || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 结果">
                {{ ui.defaultLlmTestResult.vl?.message || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 耗时(ms)">
                {{ ui.defaultLlmTestResult.vl?.elapsed_ms ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 返回文本">
                <pre class="test-output">{{ outputText(ui.defaultLlmTestResult, "vl") }}</pre>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
          <ConfigEditor v-model="ui.defaultConfigDraft" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card class="page-card" shadow="never">
          <template #header>
            <div class="page-title-row">
              <span>用户配置覆盖</span>
              <el-space>
                <el-button :loading="ui.userLlmTestLoading" :disabled="!selectedUser" @click="testUserLlm">测试模型连通</el-button>
                <el-button type="primary" :disabled="!selectedUser" @click="saveUserConfig">保存用户配置</el-button>
              </el-space>
            </div>
          </template>

          <el-form label-position="top" class="row-gap">
            <el-form-item label="选择用户">
              <el-select v-model="ui.selectedUserId" style="width: 100%" placeholder="请选择用户">
                <el-option v-for="user in users" :key="user.id" :value="user.id" :label="`${user.name} (${user.id.slice(0, 8)})`" />
              </el-select>
            </el-form-item>
            <el-form-item label="自定义配置开关">
              <el-switch v-model="ui.userCustomEnabled" :disabled="!selectedUser" />
            </el-form-item>
            <el-space>
              <el-button :disabled="!selectedUser" @click="saveUserConfigMode">保存配置模式</el-button>
              <el-button type="danger" plain :disabled="!selectedUser" @click="clearOverrides">清空用户覆盖配置</el-button>
            </el-space>
          </el-form>

          <el-alert v-if="!selectedUser" title="暂无用户可配置。" type="warning" :closable="false" class="row-gap" />
          <el-alert
            v-else-if="ui.userCustomEnabled"
            title="该用户当前使用自定义配置，保存后只影响当前用户。"
            type="success"
            :closable="false"
            class="row-gap"
          />
          <el-alert
            v-else
            title="该用户当前继承系统默认配置，启用后可独立调整。"
            type="info"
            :closable="false"
            class="row-gap"
          />

          <el-card v-if="ui.userLlmTestResult" shadow="never" class="row-gap">
            <template #header>
              <div class="page-title-row" style="margin-bottom: 0">
                <span>用户配置测试结果</span>
                <small>Prompt: {{ ui.userLlmTestResult.prompt || "-" }}</small>
              </div>
            </template>
            <el-space wrap>
              <el-tag :type="ui.userLlmTestResult.thinking?.ok ? 'success' : 'danger'">
                Thinking: {{ ui.userLlmTestResult.thinking?.ok ? "成功" : "失败" }}
              </el-tag>
              <el-tag :type="ui.userLlmTestResult.vl?.ok ? 'success' : 'danger'">
                VL: {{ ui.userLlmTestResult.vl?.ok ? "成功" : "失败" }}
              </el-tag>
            </el-space>
            <el-descriptions :column="1" border style="margin-top: 10px">
              <el-descriptions-item label="Thinking 模型">
                {{ ui.userLlmTestResult.thinking?.model || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 结果">
                {{ ui.userLlmTestResult.thinking?.message || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 耗时(ms)">
                {{ ui.userLlmTestResult.thinking?.elapsed_ms ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="Thinking 返回文本">
                <pre class="test-output">{{ outputText(ui.userLlmTestResult, "thinking") }}</pre>
              </el-descriptions-item>
              <el-descriptions-item label="VL 模型">
                {{ ui.userLlmTestResult.vl?.model || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 结果">
                {{ ui.userLlmTestResult.vl?.message || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 耗时(ms)">
                {{ ui.userLlmTestResult.vl?.elapsed_ms ?? "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="VL 返回文本">
                <pre class="test-output">{{ outputText(ui.userLlmTestResult, "vl") }}</pre>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <ConfigEditor v-model="ui.userConfigDraft" :disabled="!ui.userCustomEnabled || !selectedUser" />
        </el-card>
      </el-col>
    </el-row>
  </section>
</template>

<style scoped>
.test-output {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow: auto;
}
</style>
