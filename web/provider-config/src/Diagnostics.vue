<script setup lang="ts">
import {ref} from 'vue'
import {request} from './api'
const preview = ref<any>(null), error = ref(''), busy = ref(false), notice = ref('')
async function inspect() {
  busy.value = true; error.value = ''; notice.value = ''; preview.value = null
  try { preview.value = await request('diagnostics/preview', {}) }
  catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const result = await request('diagnostics/export', {preview_token: preview.value.preview_token})
    const response = await fetch(result.download_url, {headers: {'X-VC-Client':'1'}, credentials:'same-origin', cache:'no-store'})
    if (!response.ok) throw new Error('诊断已写入本机，但下载未完成；请重新打开页面核对。')
    const url = URL.createObjectURL(await response.blob()), a = document.createElement('a')
    a.href = url; a.download = result.filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    preview.value = null; notice.value = '已导出匿名诊断文件。'
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template><section class="panel settings backup-panel"><h2>匿名诊断</h2><p class="hint">预览本机配置和证据摘要，再导出新文件。报告省略账户、凭据、备注、任务链接和本机路径。</p><div v-if="error" class="error" role="alert">{{ error }}</div><div v-if="notice" class="notice">{{ notice }}</div><div class="actions"><button :disabled="busy" @click="inspect">预览匿名诊断</button><button v-if="preview" class="primary" :disabled="busy" @click="save">导出此预览</button></div><pre v-if="preview" class="diagnostic-preview" tabindex="0" aria-label="匿名诊断预览">{{ JSON.stringify(preview.report, null, 2) }}</pre></section></template>
