<script setup lang="ts">
import {ref} from 'vue'
import {request} from './api'
const props = defineProps<{writable: boolean, recover: (row: any) => Promise<void>}>()
const emit = defineEmits<{discarded: [token: string]}>()
const rows = ref<any[]>([]), cursor = ref<string | null>(null), loaded = ref(false), busy = ref(false), error = ref('')
const kinds: Record<string, string> = {upstream:'上游输入', binding:'模型资料', defaults:'默认选择', repair:'备份选择', unknown:'无法识别的草稿'}
const states: Record<string, string> = {available:'可恢复', expired:'已过期', unsupported:'版本不支持', unavailable:'无法读取'}
const date = (seconds: number) => new Date(seconds * 1000).toLocaleString('zh-CN')
async function list(more = false) {
  busy.value = true; error.value = ''
  try {
    const result = await request('drafts/list', {cursor: more ? cursor.value : undefined})
    rows.value = more ? [...rows.value, ...result.drafts] : result.drafts
    cursor.value = result.next_cursor; loaded.value = true
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
async function act(row: any, discard = false) {
  busy.value = true; error.value = ''
  try {
    if (discard) {
      if (!confirm('丢弃这份未提交草稿？已保存的配置不会改变。')) return
      await request('drafts/discard', {draft_token: row.draft_token, expected_version: row.draft_version})
      rows.value = rows.value.filter(r => r.draft_token !== row.draft_token)
      emit('discarded', row.draft_token)
    } else await props.recover(row)
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template><details class="panel settings draft-recovery"><summary>本机未提交草稿</summary>
  <p class="hint">浏览器关闭后，可主动找回七天内的非秘密输入。列表只显示类型和时间；恢复输入后仍需核对并手动保存。API 密钥需重新填写。</p>
  <button :disabled="busy" @click="list()">{{ busy ? '正在读取…' : '读取本机草稿列表' }}</button>
  <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="loaded && !rows.length" role="status">暂无本机草稿。</p>
  <ul v-if="rows.length" aria-label="本机草稿列表"><li v-for="row in rows" :key="row.draft_token">
    <strong>{{ kinds[row.kind] }}</strong> · {{ states[row.status] }}<p>更新 {{ date(row.updated_at) }}<span v-if="row.expires_at"> · 到期 {{ date(row.expires_at) }}</span></p>
    <div class="actions"><button :disabled="busy || !writable || row.status !== 'available'" @click="act(row)">恢复输入</button><button :disabled="busy || !writable" @click="act(row, true)">丢弃此草稿</button></div>
  </li></ul><button v-if="cursor" :disabled="busy" @click="list(true)">更多草稿</button>
</details></template>
