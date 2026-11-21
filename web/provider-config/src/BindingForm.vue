<script setup lang="ts">
import {ref, computed, watch, nextTick, onMounted, onUnmounted} from 'vue'
import {useFormDraft} from './formDraft'
import ContractFields from './ContractFields.vue'
import {containDialogFocus} from './dialogFocus'
const props = defineProps<{save: (operation: string, values: any, id?: string, credential?: string, source?: string) => Promise<any>, writable: boolean, source: string, blocked?: boolean, pendingMessage?: string, reconciling?: boolean}>()
defineEmits<{'restore-draft': [], reconcile: []}>()
const dialog = ref<HTMLDialogElement | null>(null), error = ref(''), busy = ref(false), original = ref('')
const form = ref<any>({}), advanced = ref(false)
const formSource = ref('')
const draft = useFormDraft('vc-binding-draft')
const {offer: draftOffer, notice: draftNotice, conflict: draftConflict} = draft
const sourceConflict = computed(() => !!formSource.value && formSource.value !== props.source)
const protocols = ['unconfigured','sub2api-json-v1','newapi-json-v1','newapi-multipart-v1','openai-images-v1','xingapi-video-v1','xingapi-video-v2']
const operations = ['text-to-video','image-to-video','reference-to-video','text-to-image','image-edit','video-edit','video-extend']
const sections = [
  {id:'declared_capabilities', name:'供应商声明与来源'}, {id:'capability_overrides', name:'可执行参数约束'},
  {id:'listed_pricing', name:'展示报价与来源'}, {id:'pricing', name:'预算价格、条件档位和计费规则'},
  {id:'adapter_options', name:'协议选项'}]
async function open(binding: any) {
  if (busy.value || props.blocked) return
  if (draftOffer.value) { error.value = '请先恢复或丢弃模型资料草稿。'; return }
  formSource.value = props.source
  form.value = {id: binding.id, display_name: binding.name, notes: binding.notes, favorite: binding.favorite,
    sort_order: binding.sort_order, tags: binding.tags.join(', '), enabled: binding.enabled,
    remote_model: binding.remote_model, adapter: binding.adapter, operations: [...binding.operations], setup_status: binding.setup_status}
  for (const s of sections) form.value[s.id] = JSON.stringify(binding[s.id] || {}, null, 2)
  original.value = JSON.stringify(form.value); advanced.value = false; error.value = ''; await nextTick(); dialog.value?.showModal()
  dialog.value?.querySelector('input')?.focus()
}
async function close() {
  if (busy.value) return
  if (original.value !== JSON.stringify(form.value) && !confirm('放弃尚未保存的模型资料？')) return
  try { await draft.discard() } catch (e: any) { error.value = e.message; return }
  dialog.value?.close(); form.value = {}
  await nextTick(); document.querySelector<HTMLElement>('[data-binding-editor]')?.focus()
}
async function submit() {
  if (busy.value || props.blocked) return
  busy.value = true; error.value = ''
  try {
    const f = form.value
    const order = Number(f.sort_order)
    if (f.sort_order === '' || !Number.isSafeInteger(order)) throw new Error('排序值需要有效的整数。')
    const values: any = {display_name: f.display_name, notes: f.notes, favorite: f.favorite,
      sort_order: order, tags: f.tags.split(',').map((v: string) => v.trim()).filter(Boolean)}
    if (advanced.value) {
      Object.assign(values, {enabled: f.enabled, remote_model: f.remote_model, adapter: f.adapter,
        operations: f.operations, setup_status: f.setup_status})
      for (const s of sections) {
        try {
          const data = JSON.parse(f[s.id])
          if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error()
          values[s.id] = Object.keys(data).length ? data : null
        } catch { throw new Error(s.name + '需要有效的 JSON 对象。') }
      }
    }
    await props.save('binding.update', values, f.id, undefined, formSource.value)
    if (!await draft.cleanup()) draftNotice.value = '资料已保存；旧草稿保留，可稍后从列表核对。'
    dialog.value?.close(); form.value = {}
    await nextTick(); document.querySelector<HTMLElement>('[data-binding-editor]')?.focus()
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
function draftForm() {
  const f = form.value
  return {kind: 'binding', id: f.id, display_name: f.display_name, notes: f.notes, favorite: !!f.favorite,
    sort_order: String(f.sort_order ?? ''), tags: f.tags, advanced: advanced.value, enabled: !!f.enabled,
    remote_model: f.remote_model, adapter: f.adapter, operations: f.operations, setup_status: f.setup_status,
    sections: Object.fromEntries(sections.map(s => [s.id, f[s.id]]))}
}
watch(() => JSON.stringify([form.value, advanced.value, formSource.value]), () => {
  if (dialog.value?.open && !busy.value && JSON.stringify(form.value) !== original.value) draft.schedule(draftForm(), formSource.value)
})
async function restoreDraft(bindings: any[]) {
  if (busy.value || props.blocked) return
  try {
    const d = await draft.restore(), binding = bindings.find(b => b.id === d.form.id)
    if (!binding) { draftOffer.value = d; throw new Error('原模型接入已不可用，草稿保留；请先核对配置或丢弃草稿。') }
    // Use current safe DTOs only to fill sections that could not be persisted.
    const {kind: _, advanced: showAdvanced, sections: restored, ...values} = d.form
    form.value = {...values}
    for (const s of sections) form.value[s.id] = restored[s.id] ?? JSON.stringify(binding[s.id] || {}, null, 2)
    formSource.value = d.source_token; original.value = ''; advanced.value = showAdvanced && !d.omitted_sections?.length
    error.value = ''; await nextTick(); dialog.value?.showModal(); dialog.value?.querySelector('input')?.focus()
  } catch (e: any) { error.value = e.message }
}
function rebase() {
  if (confirm('请核对当前模型的资料、协议和报价，确认已经合并其他窗口的修改？')) formSource.value = props.source
}
async function discardOffer() { try { await draft.discard() } catch (e: any) { error.value = e.message } }
defineExpose({open, findDraft: draft.find, restoreDraft, adoptDraft: draft.adopt, forgetDraftOffer: draft.forgetOffer, hasOpenForm: () => !!dialog.value?.open})
function guard(event: BeforeUnloadEvent) {
  if (dialog.value?.open && (busy.value || original.value !== JSON.stringify(form.value))) {event.preventDefault();event.returnValue=''}
}
onMounted(() => window.addEventListener('beforeunload', guard))
onUnmounted(() => {draft.stop(); window.removeEventListener('beforeunload', guard)})
</script>
<template><div v-if="draftOffer" class="notice" role="status">此标签页有未提交的模型资料草稿。<span v-if="draftOffer.unavailable">暂不可恢复，请从本机草稿列表核对或丢弃。</span><button :disabled="!writable || draftOffer.unavailable" @click="$emit('restore-draft')">恢复模型草稿</button><button :disabled="!writable || draftOffer.unavailable" @click="discardOffer">丢弃模型草稿</button><span v-if="error">{{ error }}</span></div><dialog ref="dialog" aria-labelledby="binding-form-title" @keydown="containDialogFocus" @cancel.prevent="close"><form @submit.prevent="submit" :aria-busy="busy">
  <div class="dialog-head"><h2 id="binding-form-title">模型资料与价格</h2><p>显示资料可直接维护；协议、能力和价格来源由 Codex 依据文档整理。</p></div>
  <div class="dialog-body"><div v-if="pendingMessage" class="notice" role="alert">{{ pendingMessage }}<button type="button" :disabled="reconciling" data-reconcile @click="$emit('reconcile')">核对保存结果</button></div><fieldset class="form-fields" :disabled="busy" aria-label="模型资料"><div v-if="error" class="error" role="alert">{{ error }}</div><p v-if="draftNotice" class="hint" role="status">{{ draftNotice }}</p><button v-if="draftConflict" type="button" @click="draft.fork(draftForm(), formSource)">将当前模型输入另存新草稿</button><div v-if="sourceConflict" class="notice">模型草稿来源已变化，请先合并核对。<button type="button" @click="rebase">使用当前模型重新核对</button></div>
    <label class="field"><span>显示名称</span><input v-model="form.display_name" maxlength="200"></label>
    <label class="field"><span>备注</span><textarea v-model="form.notes" rows="4" maxlength="16000"></textarea></label>
    <label class="field"><span>标签（逗号分隔）</span><input v-model="form.tags"></label>
    <label class="checkline"><input v-model="form.favorite" type="checkbox">收藏此接入</label>
    <label class="field"><span>排序值</span><input v-model.number="form.sort_order" type="number" step="1"></label>
    <details :open="advanced" @toggle="advanced = ($event.target as HTMLDetailsElement).open"><summary>按明确文档维护协议、参数与报价（可选）</summary>
      <p class="hint">以下结构化字段可由 Codex 整理后填写。声明与可执行约束分开；报价不代表实际账单。保存时统一校验。</p>
      <label class="field"><span>精确远端型号</span><input v-model="form.remote_model" required></label>
      <label class="field"><span>协议</span><select v-model="form.adapter"><option v-for="p in protocols" :key="p" :value="p">{{ p }}</option></select></label>
      <div class="field"><span>已确认操作</span><label v-for="op in operations" :key="op" class="checkline"><input v-model="form.operations" type="checkbox" :value="op">{{ op }}</label></div>
      <label class="field"><span>接入整理状态</span><input v-model="form.setup_status"></label>
      <ContractFields :key="form.id" :value="form" @update="(section, raw) => form[section] = raw" />
      <label v-for="s in sections" :key="s.id" class="field"><span>{{ s.name }}</span><textarea v-model="form[s.id]" rows="6" spellcheck="false" class="mono"></textarea></label>
      <label class="checkline"><input v-model="form.enabled" type="checkbox">启用为新任务候选（仍须逐次验证请求）</label>
    </details>
  </fieldset></div><div class="dialog-foot"><span>统一保存模型资料</span><div class="actions"><button type="button" :disabled="busy" @click="close">取消</button><button type="submit" class="primary" :disabled="busy || blocked || !writable || sourceConflict">{{ busy ? '正在保存…' : '保存模型资料' }}</button></div></div>
</form></dialog></template>
