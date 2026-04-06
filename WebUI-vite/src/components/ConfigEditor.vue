<script setup>
import { reactive, watch } from "vue";

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({}),
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

const form = reactive({
  auto_danmu: false,
  danmu_limit: 5,
  audio_on: true,
  auto_answer: true,
  answer_delay_type: 1,
  answer_delay_custom: 0,
  auto_save_ppt: true,
  enable_devtools: false,
  debug_mode: false,

  audio_send_danmu: true,
  audio_others_danmu: true,
  audio_receive_problem: true,
  audio_answer_result: true,
  audio_im_called: true,
  audio_others_called: false,
  audio_course_info: true,
  audio_network_info: true,

  llm_api_key: "",
  llm_base_url: "",
  llm_model: "",
  llm_thinking_model: "",
  llm_vl_model: "",
  llm_answer_timeout: 120,
  llm_connect_timeout: 10,
  llm_test_timeout: 15,
  llm_save_log: true,
});

function patchForm(cfg = {}) {
  form.auto_danmu = !!cfg.auto_danmu;
  form.danmu_limit = Number(cfg.danmu_config?.danmu_limit ?? 5);
  form.audio_on = !!cfg.audio_on;
  form.auto_answer = !!cfg.auto_answer;
  form.answer_delay_type = Number(cfg.answer_config?.answer_delay?.type ?? 1);
  form.answer_delay_custom = Number(cfg.answer_config?.answer_delay?.custom?.time ?? 0);
  form.auto_save_ppt = !!cfg.auto_save_ppt;
  form.enable_devtools = !!cfg.enable_devtools;
  form.debug_mode = !!cfg.debug_mode;

  const audioType = cfg.audio_config?.audio_type || {};
  form.audio_send_danmu = !!audioType.send_danmu;
  form.audio_others_danmu = !!audioType.others_danmu;
  form.audio_receive_problem = !!audioType.receive_problem;
  form.audio_answer_result = !!audioType.answer_result;
  form.audio_im_called = !!audioType.im_called;
  form.audio_others_called = !!audioType.others_called;
  form.audio_course_info = !!audioType.course_info;
  form.audio_network_info = !!audioType.network_info;

  const llm = cfg.llm_config || {};
  form.llm_api_key = llm.api_key ?? "";
  form.llm_base_url = llm.base_url ?? "";
  form.llm_model = llm.model ?? "";
  form.llm_thinking_model = llm.thinking_model ?? "";
  form.llm_vl_model = llm.vl_model ?? "";
  form.llm_answer_timeout = Number(llm.answer_timeout ?? 120);
  form.llm_connect_timeout = Number(llm.connect_timeout ?? 10);
  form.llm_test_timeout = Number(llm.test_timeout ?? 15);
  form.llm_save_log = !!llm.save_log;
}

function toConfig() {
  return {
    auto_danmu: !!form.auto_danmu,
    danmu_config: {
      danmu_limit: Number(form.danmu_limit || 5),
    },
    audio_on: !!form.audio_on,
    audio_config: {
      audio_type: {
        send_danmu: !!form.audio_send_danmu,
        others_danmu: !!form.audio_others_danmu,
        receive_problem: !!form.audio_receive_problem,
        answer_result: !!form.audio_answer_result,
        im_called: !!form.audio_im_called,
        others_called: !!form.audio_others_called,
        course_info: !!form.audio_course_info,
        network_info: !!form.audio_network_info,
      },
    },
    auto_answer: !!form.auto_answer,
    answer_config: {
      answer_delay: {
        type: Number(form.answer_delay_type || 1),
        custom: {
          time: Number(form.answer_delay_custom || 0),
        },
      },
    },
    llm_config: {
      api_key: form.llm_api_key,
      base_url: form.llm_base_url,
      model: form.llm_model,
      thinking_model: form.llm_thinking_model,
      vl_model: form.llm_vl_model,
      answer_timeout: Number(form.llm_answer_timeout || 120),
      connect_timeout: Number(form.llm_connect_timeout || 10),
      test_timeout: Number(form.llm_test_timeout || 15),
      save_log: !!form.llm_save_log,
    },
    auto_save_ppt: !!form.auto_save_ppt,
    enable_devtools: !!form.enable_devtools,
    debug_mode: !!form.debug_mode,
  };
}

watch(
  () => props.modelValue,
  (value) => {
    patchForm(value || {});
  },
  { deep: true, immediate: true }
);

watch(
  form,
  () => {
    emit("update:modelValue", toConfig());
  },
  { deep: true }
);
</script>

<template>
  <div>
    <el-row :gutter="12" class="row-gap">
      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <template #header>
            <span>核心开关</span>
          </template>
          <el-form label-position="left" label-width="140px" :disabled="disabled">
            <el-form-item label="自动发弹幕"><el-switch v-model="form.auto_danmu" /></el-form-item>
            <el-form-item label="播报提示音"><el-switch v-model="form.audio_on" /></el-form-item>
            <el-form-item label="自动答题"><el-switch v-model="form.auto_answer" /></el-form-item>
            <el-form-item label="自动保存PPT"><el-switch v-model="form.auto_save_ppt" /></el-form-item>
            <el-form-item label="启用调试工具"><el-switch v-model="form.enable_devtools" /></el-form-item>
            <el-form-item label="调试模式"><el-switch v-model="form.debug_mode" /></el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <template #header>
            <span>弹幕 / 答题策略</span>
          </template>
          <el-form label-position="left" label-width="140px" :disabled="disabled">
            <el-form-item label="弹幕频率上限">
              <el-input-number v-model="form.danmu_limit" :min="1" :max="99" />
            </el-form-item>
            <el-form-item label="答题延迟类型">
              <el-select v-model="form.answer_delay_type" style="width: 100%">
                <el-option :value="0" label="立即提交" />
                <el-option :value="1" label="随机策略" />
                <el-option :value="2" label="固定延迟" />
              </el-select>
            </el-form-item>
            <el-form-item label="自定义延迟(秒)">
              <el-input-number v-model="form.answer_delay_custom" :min="0" :max="600" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="row-gap">
      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <template #header>
            <span>语音播报分类</span>
          </template>
          <el-form :disabled="disabled" label-position="top">
            <el-row :gutter="8">
              <el-col :span="12"><el-checkbox v-model="form.audio_send_danmu">自己发弹幕</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_others_danmu">其他人弹幕</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_receive_problem">收到题目</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_answer_result">答题结果</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_im_called">自己被点名</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_others_called">其他人被点名</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_course_info">课程信息</el-checkbox></el-col>
              <el-col :span="12"><el-checkbox v-model="form.audio_network_info">网络状态</el-checkbox></el-col>
            </el-row>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <template #header>
            <span>LLM 配置</span>
          </template>
          <el-form label-position="left" label-width="110px" :disabled="disabled">
            <el-form-item label="API Key"><el-input v-model="form.llm_api_key" /></el-form-item>
            <el-form-item label="Base URL"><el-input v-model="form.llm_base_url" /></el-form-item>
            <el-form-item label="主模型"><el-input v-model="form.llm_model" /></el-form-item>
            <el-form-item label="思考模型"><el-input v-model="form.llm_thinking_model" /></el-form-item>
            <el-form-item label="视觉模型"><el-input v-model="form.llm_vl_model" /></el-form-item>
            <el-form-item label="答案超时"><el-input-number v-model="form.llm_answer_timeout" :min="1" /></el-form-item>
            <el-form-item label="连接超时"><el-input-number v-model="form.llm_connect_timeout" :min="1" /></el-form-item>
            <el-form-item label="测试超时"><el-input-number v-model="form.llm_test_timeout" :min="1" /></el-form-item>
            <el-form-item label="保存推理日志"><el-switch v-model="form.llm_save_log" /></el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
