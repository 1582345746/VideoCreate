<script setup lang="ts">
import {ref, watch} from 'vue'
import {request} from './api'
const props = defineProps<{binding: string, token: string}>()
const data = ref<any>({}), error = ref(''), loading = ref(false)
const labels: any = {catalog:'目录',contract:'合同',smoke:'生成小样',quality:'内容质量'}
const states: any = {unverified:'未核实',reported_pass:'有通过记录',fail:'有失败记录'}
watch(() => [props.binding, props.token], async (_, __, onCleanup) => {
  const id = props.binding, token = props.token
  let active = true
  onCleanup(() => { active = false })
  data.value = {}; error.value = ''; loading.value = true
  try {
    const result = await request('evidence', {binding: id})
    if (!active) return
    if (result.binding !== id || result.config_token !== token) {
      error.value = '配置已变化，请刷新配置后再查看操作记录。'; return
    }
    data.value = result.operations
  }
  catch (e: any) { if (active) error.value = e.message }
  finally { if (active) loading.value = false }
}, {immediate: true, flush: 'sync'})
</script>
<template><section class="detail-block"><h3>逐操作证据</h3><p v-if="loading" role="status">正在读取操作记录…</p><p v-else-if="error" role="status">{{ error }}</p><p v-else-if="!Object.keys(data).length">暂无可读取的操作记录。</p><div v-for="(stages, op) in data" :key="String(op)" class="evidence-operation"><strong>{{ op }}</strong><div class="tags"><span v-for="(r, stage) in stages" :key="String(stage)" class="badge">{{ labels[stage] }} · {{ states[r.status] }} {{ r.receipt_count ? `(${r.receipt_count})` : '' }}</span></div></div><small>各层独立记录；文生视频通过不代表参考视频通过。</small></section></template>
