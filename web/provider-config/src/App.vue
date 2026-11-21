<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { request, session, stateKey } from './api'
import BindingForm from './BindingForm.vue'
import {containDialogFocus} from './dialogFocus'
import EvidenceView from './EvidenceView.vue'
import Diagnostics from './Diagnostics.vue'
import CatalogTools from './CatalogTools.vue'
import DraftRecovery from './DraftRecovery.vue'
import {useFormDraft} from './formDraft'

const page = ref('providers'), provider = ref(''), selected = ref('')
const loading = ref(true), error = ref(''), query = ref(''), kind = ref(''), family = ref(''), favorites = ref(false)
const packet = ref<any>({ summary: {}, upstreams: [], bindings: [] })
const writable = computed(() => !!packet.value.summary.editable)
const dialog = ref<HTMLDialogElement | null>(null), form = ref<any>({}), saving = ref(false), formError = ref(''), notice = ref('')
const bindingForm = ref<InstanceType<typeof BindingForm> | null>(null)
const taskFit = ref<any>(null), taskOnly = ref(false)
const formBaseline = ref('')
const formSource = ref('')
const upstreamDraft = useFormDraft('vc-upstream-draft')
const {offer: draftOffer, notice: draftNotice, conflict: draftConflict} = upstreamDraft
let upstreamOpener: HTMLElement | null = null
let upstreamAction = 'create'
const pending = ref(''), pendingLegacy = ref(false)
const commitIssue = ref(''), reconciling = ref(false)
let reconcileWaiter: {resolve: (result: any) => void, reject: (error: Error) => void} | null = null
const defaultForm = ref<any>({image: {binding: '', policy: 'ask'}, video: {binding: '', policy: 'ask'}})
const defaultSaving = ref(false)
const defaultBaseline = ref('')
const defaultSource = ref('')
const defaultsDirty = computed(() => JSON.stringify(defaultForm.value) !== defaultBaseline.value)
const backups = ref<any>({backups: [], can_repair: false}), backupChoice = ref(''), restoring = ref(false)
const changing = ref(false)
const saveBusy = computed(() => changing.value || saving.value || defaultSaving.value || restoring.value || reconciling.value)
const canReconcile = computed(() => !!pending.value && !reconciling.value && (!!commitIssue.value || !saveBusy.value))
watch(canReconcile, async available => {
  if (!available) return
  await nextTick()
  if (!canReconcile.value) return
  // Chrome can retain the disabled submit's sequential starting point. Give
  // the now-available recovery action focus, including after a failed status read.
  const target = document.querySelector<HTMLElement>('dialog[open] [data-reconcile]') ||
    document.querySelector<HTMLElement>('main [data-reconcile]')
  target?.focus()
})
const defaultDraft = useFormDraft('vc-defaults-draft'), repairDraft = useFormDraft('vc-repair-draft')
const {offer: defaultOffer, notice: defaultNotice, conflict: defaultDraftConflict} = defaultDraft
const {offer: repairOffer, notice: repairNotice, conflict: repairDraftConflict} = repairDraft
const backupSource = ref(''), backupMode = ref('')
const defaultConflict = computed(() => !!defaultSource.value && defaultSource.value !== packet.value.summary.token)
const backupCurrentSource = computed(() => backups.value.can_repair ? backups.value.source_token : packet.value.summary.token)
const backupConflict = computed(() => !!backupChoice.value && (backupSource.value !== backupCurrentSource.value || backupMode.value !== (backups.value.can_repair ? 'repair' : 'restore')))
const observation = ref<any>({rows: [], contracts: []}), checking = ref(false), importIds = ref<string[]>([]), importKind = ref('video')
let catalogReadVersion = 0
function invalidateCatalogRead() {
  catalogReadVersion++; checking.value = false
  observation.value = {rows: [], contracts: []}; importIds.value = []
}
// Invalidate before select/change handlers start the next read. Returning to the
// same upstream is a new context, even if the earlier request is still running.
watch(() => [page.value, provider.value, packet.value.summary.token, loading.value], invalidateCatalogRead, {flush: 'sync'})
const mediaKinds = [{id: 'image', name: '图片'}, {id: 'video', name: '视频'}]
const defaultOptions = (kind: string) => packet.value.bindings.filter((b: any) => b.kind === kind && b.default_eligible)
const pages = [{ id: 'providers', name: '上游管理', icon: '▤' }, { id: 'catalog', name: '模型目录', icon: '▦' },
  { id: 'defaults', name: '默认选择', icon: '✓' }, { id: 'checks', name: '检查与记录', icon: '☷' }, { id: 'settings', name: '设置', icon: '⚙' }]
const current = computed(() => packet.value.upstreams.find((p: any) => p.id === provider.value))
const names = computed(() => [...new Set(packet.value.bindings.map((b: any) => b.family))])
const rows = computed(() => packet.value.bindings.filter((b: any) =>
  (page.value === 'catalog' || b.upstream_id === provider.value) && (!kind.value || b.kind === kind.value) &&
  (!taskOnly.value || !taskFit.value || taskFit.value[b.id]?.matches) &&
  (!family.value || b.family === family.value) && (!favorites.value || b.favorite) &&
  [b.name, b.remote_model, b.notes, b.upstream_name, ...b.tags].join(' ').toLowerCase().includes(query.value.toLowerCase())))
const detail = computed(() => rows.value.find((b: any) => b.id === selected.value) || rows.value[0])
const states: Record<string, string> = { enabled: '已启用', draft: '待整理草稿', disabled: '未启用', archived: '已归档' }
const configStates: Record<string, string> = { valid: '配置已读取', missing: '未找到配置', 'invalid-json': '配置文件需要修复',
  'invalid-schema': '配置结构需要检查', 'unsupported-version': '配置版本较新，当前只读', unreadable: '无法读取配置' }
function formSnapshot(value: any) {
  return JSON.stringify({mode: value?.mode || '', id: value?.id || '', url: value?.url || '', name: value?.name || '',
    notes: value?.notes || '', key: value?.key || '', same_account: !!value?.same_account})
}
const formDirty = computed(() => formSnapshot(form.value) !== formBaseline.value)
async function refresh() {
  const keepDefaults = defaultsDirty.value && !!defaultBaseline.value && !defaultSaving.value
  loading.value = true; error.value = ''
  try {
    await session()
    if (!pending.value) {
      pending.value = sessionStorage.getItem(stateKey('vc-pending-change')) || ''
      if (!pending.value) {
        pending.value = sessionStorage.getItem('vc-pending-change') || ''
        pendingLegacy.value = !!pending.value
      }
    }
    packet.value = await request('catalog')
    if (!keepDefaults) {
      for (const kind of mediaKinds) {
        const old = packet.value.defaults[kind.id]
        defaultForm.value[kind.id] = {binding: old?.binding || '', policy: old?.policy || 'ask'}
      }
      defaultBaseline.value = JSON.stringify(defaultForm.value)
      defaultSource.value = packet.value.summary.token
    }
    if (!packet.value.upstreams.some((p: any) => p.id === provider.value)) provider.value = packet.value.upstreams[0]?.id || ''
    return true
  } catch (e: any) { error.value = e.message; return false }
  finally { loading.value = false }
}
async function navigate(id: string, uid?: string) {
  if (saveBusy.value) return
  if (page.value === 'defaults' && defaultsDirty.value) {
    if (!confirm('放弃尚未保存的默认选择？')) return
    try { await defaultDraft.discard() } catch (e: any) { error.value = e.message; return }
    defaultForm.value = JSON.parse(defaultBaseline.value)
  }
  page.value = id; query.value = ''; kind.value = ''; family.value = ''; selected.value = ''
  if (uid) provider.value = uid
  if (id === 'settings') loadBackups()
  if (id === 'checks' && provider.value) readCatalog(false)
}
async function change(operation: string, values: any, id?: string, credential?: string, source?: string) {
  if (pending.value) throw new Error('请先核对上一次保存结果，再进行新的保存。')
  if (changing.value) throw new Error('正在保存本机配置，请等待本次结果。')
  // Reserve the transaction before awaiting preview: pending is only available
  // after preview returns, so it cannot guard this first asynchronous interval.
  changing.value = true
  try {
    const preview = await request('changes/preview', {operation, id, values,
      expected_token: source || (dialog.value?.open && formSource.value ? formSource.value : packet.value.summary.token)})
    return await submitPreview(preview, credential)
  } finally { changing.value = false }
}
async function submitPreview(preview: any, credential?: string) {
  pending.value = preview.preview_token
  pendingLegacy.value = false; sessionStorage.setItem(stateKey('vc-pending-change'), pending.value)
  let result: any, reconciled = false
  try { result = await request('changes/commit', {preview_token: pending.value, ...(credential ? {credential} : {})}) }
  catch (e: any) {
    // Keep the original caller suspended, including its form lock and exact
    // draft version. Only an explicit status read may complete this write.
    credential = undefined
    commitIssue.value = (e.message || '未收到保存确认。') + ' 请核对保存结果；确认前输入保持锁定，不会自动重复提交。'
    result = await new Promise((resolve, reject) => { reconcileWaiter = {resolve, reject} })
    reconciled = true
  }
  clearPending()
  notice.value = result.warning || (reconciled ? '已核对：上一次配置保存成功。' : '已保存到本机配置。新上游的模型接入可继续交给 Codex 整理。')
  await refresh()
  return result
}
function clearPending() {
  const key = pendingLegacy.value ? 'vc-pending-change' : stateKey('vc-pending-change')
  if (sessionStorage.getItem(key) === pending.value) sessionStorage.removeItem(key)
  pending.value = ''; pendingLegacy.value = false; commitIssue.value = ''
}
async function loadBackups() {
  try { backups.value = await request('backups') }
  catch (e: any) { error.value = e.message }
}
async function restoreBackup() {
  if (saveBusy.value || pending.value || !backupChoice.value || backupConflict.value) return
  restoring.value = true; changing.value = true
  try {
    const repair = backupMode.value === 'repair'
    const preview = await request('changes/preview', {operation: repair ? 'config.repair' : 'config.restore',
      values: {backup_id: backupChoice.value}, expected_token: backupSource.value})
    const counts = preview.counts
    const warning = repair && !preview.original_structure_verified ? '\n损坏原文无法完整解析，请确认所选备份覆盖需要保留的历史身份。' : ''
    if (!confirm(`恢复后登记 ${counts.upstreams} 个上游、${counts.bindings} 个接入。可读取的后续身份会保留，原文件会先备份。${warning}\n确认恢复？`)) return
    await submitPreview(preview)
    notice.value = '配置已恢复，原始备份与旧凭据版本继续保留。'
    await loadBackups()
    backupChoice.value = ''; backupSource.value = ''; backupMode.value = ''
    if (!await repairDraft.cleanup()) repairNotice.value = '配置已恢复；旧草稿保留，可稍后从列表核对。'
  } catch (e: any) { error.value = e.message }
  finally { restoring.value = false; changing.value = false }
}
function chooseBackup() {
  if (saveBusy.value) return
  if (repairOffer.value) { error.value = '请先恢复或丢弃原有的备份选择草稿。'; backupChoice.value = ''; return }
  backupSource.value = backupCurrentSource.value
  backupMode.value = backups.value.can_repair ? 'repair' : 'restore'
  if (backupChoice.value) repairDraft.schedule({kind: 'repair', mode: backupMode.value, backup_id: backupChoice.value}, backupSource.value)
  else discardRecovery('repair')
}
async function restoreRecovery(kind: 'defaults' | 'repair') {
  if (saveBusy.value) return
  try {
    if (kind === 'defaults') {
      if (defaultsDirty.value && !confirm('用草稿替换当前尚未保存的默认选择？')) return
      const d = await defaultDraft.restore()
      defaultForm.value = {image: d.form.image, video: d.form.video}; defaultSource.value = d.source_token
      page.value = 'defaults'
    } else {
      const d = await repairDraft.restore(); await loadBackups()
      backupChoice.value = d.form.backup_id; backupSource.value = d.source_token; backupMode.value = d.form.mode
      page.value = 'settings'
    }
    await nextTick(); document.querySelector<HTMLElement>('main select')?.focus()
  } catch (e: any) { error.value = e.message }
}
async function discardRecovery(kind: 'defaults' | 'repair') {
  if (saveBusy.value) return
  try {
    await (kind === 'defaults' ? defaultDraft : repairDraft).discard()
    if (kind === 'repair') { backupChoice.value = ''; backupSource.value = ''; backupMode.value = '' }
  } catch (e: any) { error.value = e.message }
}
function rebaseRecovery(kind: 'defaults' | 'repair') {
  if (saveBusy.value) return
  if (!confirm('请对照当前配置核对并合并草稿，确认继续使用这些选择？')) return
  if (kind === 'defaults') defaultSource.value = packet.value.summary.token
  else {
    if (backupMode.value !== (backups.value.can_repair ? 'repair' : 'restore')) {
      error.value = '配置状态已变化，请重新选择备份；原草稿不会自动转为另一种操作。'; return
    }
    backupSource.value = backupCurrentSource.value
    repairDraft.schedule({kind:'repair', mode:backupMode.value, backup_id:backupChoice.value}, backupSource.value)
  }
}
watch(() => JSON.stringify([defaultForm.value, defaultSource.value]), () => {
  if (!loading.value && !defaultSaving.value && defaultsDirty.value && !defaultOffer.value)
    defaultDraft.schedule({kind: 'defaults', ...defaultForm.value}, defaultSource.value)
})
async function readCatalog(network = false) {
  if (page.value !== 'checks' || loading.value || !provider.value || checking.value) return
  const version = ++catalogReadVersion, upstream = provider.value
  checking.value = true; importIds.value = []; observation.value = {rows: [], contracts: []}
  try {
    const result = await request(network ? 'catalog/check' : 'catalog/observation', {upstream})
    if (version === catalogReadVersion) observation.value = result
  }
  catch (e: any) { if (version === catalogReadVersion) error.value = e.message }
  finally { if (version === catalogReadVersion) checking.value = false }
}
async function importCatalog() {
  if (saveBusy.value || pending.value) return
  try {
    await change('catalog.import', {observation_id: observation.value.observation_id, ids: importIds.value, kind: importKind.value}, provider.value)
    notice.value = '已登记为禁用草稿。协议、能力和型号等价关系继续交给 Codex 整理。'
    await readCatalog(false)
  } catch (e: any) { error.value = e.message }
}
async function applyContract(contract: any) {
  if (saveBusy.value || pending.value) return
  if (!confirm(`${contract.title}：${contract.scope}\n确认按此明确文档整理为候选？`)) return
  try { await change('contract.apply', {contract_id: contract.id, revision: contract.revision}, provider.value); notice.value = '已按明确文档登记文生视频候选；实测与质量仍未验证。' }
  catch (e: any) { error.value = e.message }
}
async function reconcile() {
  if (!canReconcile.value) return
  if (pendingLegacy.value && !confirm('旧版保存记录没有配置身份。请确认当前路径就是上次保存使用的原配置：\n' +
    packet.value.summary.config_path + '\n确认后只核对结果，不会重新提交。')) return
  reconciling.value = true
  try {
    const result = await request('changes/status', {preview_token: pending.value})
    if (!['committed', 'not-committed', 'not-submitted'].includes(result.status)) {
      commitIssue.value = result.message || '保存结果仍然未知，请稍后继续核对。'; return
    }
    const waiter = reconcileWaiter; reconcileWaiter = null
    const notCommitted = '已核对：上一次未提交配置。请检查输入后重新保存；密钥可能需要重新填写。'
    clearPending()
    if (waiter) {
      // Resume the original success/failure path: close the right form, reset
      // its baseline/selection, and clean only its last observed draft version.
      if (result.status === 'committed') waiter.resolve(result.result)
      else waiter.reject(new Error(notCommitted))
      return
    }
    // Reload loses the in-memory continuation. Never use a newly loaded draft
    // version to delete an old submission's draft: another tab may have edited it.
    notice.value = (result.status === 'committed' ? '已核对：上一次配置保存成功。' : notCommitted) +
      ' 页面重开前的非秘密草稿继续保留，请核对当前配置后再恢复或丢弃。'
    await refresh()
  } catch (e: any) { commitIssue.value = (e.message || '核对失败。') + ' 请稍后继续核对；不会重复提交。' }
  finally { reconciling.value = false }
}
async function openUpstream(mode = 'create') {
  if (saveBusy.value || pending.value) return
  if (draftOffer.value) { error.value = '请先恢复或丢弃此标签页的未提交草稿。'; return }
  const old = current.value
  upstreamOpener = document.activeElement as HTMLElement; upstreamAction = mode
  form.value = {mode, id: mode === 'create' || mode === 'copy' ? '' : old?.id,
    url: mode === 'create' ? '' : old?.url || '', name: mode === 'create' ? '' : old?.name || '',
    notes: mode === 'create' ? '' : old?.notes || '', key: '', same_account: false}
  formBaseline.value = formSnapshot(form.value)
  formSource.value = packet.value.summary.token
  formError.value = ''; await nextTick(); dialog.value?.showModal()
  dialog.value?.querySelector('input')?.focus()
}
async function focusUpstreamOpener() {
  await nextTick()
  const target = upstreamOpener?.isConnected ? upstreamOpener : document.querySelector<HTMLElement>(`[data-upstream-action="${upstreamAction}"]`)
  target?.focus()
}
async function closeForm() {
  if (saving.value) return
  if (formDirty.value && !confirm('放弃当前表单中尚未保存的修改？')) return
  try { await discardDraft() } catch (e: any) { formError.value = e.message; return }
  form.value = {}; formBaseline.value = ''; dialog.value?.close()
  await focusUpstreamOpener()
}
async function saveUpstream() {
  if (saveBusy.value || pending.value) return
  let saved = false
  saving.value = true; formError.value = ''
  try {
    const mode = form.value.mode
    if (mode !== 'update' && !form.value.key.trim()) throw new Error('请填写 API 密钥。')
    const credential = form.value.key; form.value.key = ''
    const operation = mode === 'update' ? 'upstream.update' : mode === 'rotate' ? 'upstream.rotate' : 'upstream.create'
    const values = mode === 'update' ? {name: form.value.name, notes: form.value.notes} : mode === 'rotate' ?
      {same_account: form.value.same_account} : {url: form.value.url, name: form.value.name, notes: form.value.notes}
    const result = await change(operation, values, form.value.id || undefined, credential || undefined)
    if (!await upstreamDraft.cleanup()) notice.value = '上游已保存；旧草稿保留，可稍后从列表核对。'
    provider.value = result.id; form.value = {}; formBaseline.value = ''; dialog.value?.close()
    saved = true
  } catch (e: any) { formError.value = e.message + ' 密钥输入不会暂存，请按需重新填写。' }
  finally {
    saving.value = false
    // The opener is disabled while saving. Enable it before returning keyboard
    // focus; focusing a disabled element silently leaves focus on the page body.
    if (saved) await focusUpstreamOpener()
  }
}
function nonsecretForm() {
  const f = form.value
  let url = f.url || ''
  try { const u = new URL(url); if (u.protocol !== 'https:' || u.username || u.password || u.search || u.hash) url = '' }
  catch { url = '' }
  return {mode:f.mode,id:f.id || '',url,name:f.name || '',notes:f.notes || ''}
}
watch(() => JSON.stringify(nonsecretForm()), () => {
  upstreamDraft.stop()
  if (!dialog.value?.open || !formDirty.value || !['create','copy','update'].includes(form.value.mode) || saving.value) return
  upstreamDraft.schedule(nonsecretForm(), formSource.value)
})
async function discardDraft() {
  await upstreamDraft.discard()
}
async function findDraft() {
  await upstreamDraft.find()
}
async function restoreDraft() {
  if (saveBusy.value) return
  try {
    const d = await upstreamDraft.restore()
    form.value = {...d.form,key:'',same_account:false}; formSource.value=d.source_token
    formBaseline.value=''; formError.value=''; draftOffer.value=null; await nextTick(); dialog.value?.showModal()
    dialog.value?.querySelector('input')?.focus()
    draftNotice.value = d.conflict ? '草稿来源已变化，请先合并核对；不会自动覆盖当前配置。' : '已恢复非秘密输入，请重新填写密钥。'
  } catch (e:any) {error.value=e.message}
}
async function recoverListedDraft(row: any) {
  if (saveBusy.value) throw new Error('正在保存本机配置，请等待结果后再恢复草稿。')
  if (dialog.value?.open || bindingForm.value?.hasOpenForm() || defaultsDirty.value || backupChoice.value)
    throw new Error('请先保存或关闭当前表单，再恢复另一份草稿。当前输入已保留。')
  if (row.kind === 'binding') {
    await bindingForm.value?.adoptDraft(row)
    await bindingForm.value?.restoreDraft(packet.value.bindings)
  } else if (row.kind === 'upstream') {
    await upstreamDraft.adopt(row); await restoreDraft()
  } else if (row.kind === 'defaults' || row.kind === 'repair') {
    await (row.kind === 'defaults' ? defaultDraft : repairDraft).adopt(row)
    await restoreRecovery(row.kind)
  }
}
function forgetListedDraft(token: string) {
  for (const draft of [upstreamDraft, defaultDraft, repairDraft]) draft.forgetOffer(token)
  bindingForm.value?.forgetDraftOffer(token)
}
function rebaseForm() {
  if (confirm('请核对当前配置及表单中的名称、备注，确认已合并其他窗口的变更？')) formSource.value=packet.value.summary.token
}
async function archive() {
  if (saveBusy.value || pending.value) return
  if (!current.value || !confirm('归档会停用这家上游的新任务接入，原任务恢复信息继续保留。继续归档？')) return
  try { await change('upstream.archive', {}, current.value.id) } catch (e: any) { error.value = e.message }
}
async function saveDefaults() {
  if (saveBusy.value || pending.value) return
  defaultSaving.value = true
  try {
    await change('defaults.update', defaultForm.value, undefined, undefined, defaultSource.value); notice.value = '图片和视频的默认策略已保存。'
    if (!await defaultDraft.cleanup()) defaultNotice.value = '默认选择已保存；旧草稿保留，可稍后从列表核对。'
  }
  catch (e: any) { error.value = e.message }
  finally { defaultSaving.value = false }
}
function guard(event: BeforeUnloadEvent) {
  if ((dialog.value?.open && formDirty.value) || saveBusy.value || defaultsDirty.value || backupChoice.value) { event.preventDefault(); event.returnValue = '' }
}
onMounted(async () => {
  window.addEventListener('beforeunload', guard); if (!await refresh()) return
  // A repair draft must be recoverable immediately after reopening a damaged
  // config, before the user has visited Settings and loaded its backup list.
  await loadBackups()
  await Promise.all([findDraft(), defaultDraft.find(), repairDraft.find(), bindingForm.value?.findDraft()])
})
onUnmounted(() => {invalidateCatalogRead(); upstreamDraft.stop(); defaultDraft.stop(); repairDraft.stop(); window.removeEventListener('beforeunload', guard)})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">VC</span><div>VideoCreate<small>上游配置中心</small></div></div>
      <nav aria-label="主导航"><button v-for="p in pages" :key="p.id" :aria-label="p.name" :aria-current="page === p.id ? 'page' : undefined" :class="{active: page === p.id}" :disabled="saveBusy" @click="navigate(p.id)"><span aria-hidden="true">{{ p.icon }}</span>{{ p.name }}</button></nav>
      <div class="side-label">我的上游</div>
      <div class="provider-nav"><button v-for="p in packet.upstreams" :key="p.id" :class="{active: page === 'providers' && provider === p.id}" :disabled="saveBusy" @click="navigate('providers', p.id)"><span class="avatar">{{ p.name.slice(0, 1) }}</span><span class="provider-name">{{ p.name }}</span><small>{{ p.binding_count }}</small></button></div>
      <div class="side-bottom"><span class="status-dot"></span> 本机配置<span>视频制作在 Codex 中完成</span></div>
    </aside>
    <div class="workspace">
      <header class="topbar"><span>VideoCreate <span class="slash">/</span> {{ pages.find(p => p.id === page)?.name }}</span><div class="header-state"><span>修订 {{ packet.summary.revision ?? '—' }}</span><span class="badge">{{ writable ? "本机配置" : "只读预览" }}</span></div></header>
      <main>
        <DraftRecovery :writable="writable || !!backups.can_repair" :recover="recoverListedDraft" @discarded="forgetListedDraft" />
        <div v-if="error" class="error" role="alert">{{ error }} <button :disabled="saveBusy" @click="refresh">重新读取</button></div>
        <BindingForm ref="bindingForm" :save="change" :pending-message="commitIssue" :reconciling="reconciling" @reconcile="reconcile" :writable="writable" :blocked="saveBusy || !!pending" :source="packet.summary.token" @restore-draft="bindingForm?.restoreDraft(packet.bindings)" />
        <div v-if="defaultOffer" class="notice" role="status">此标签页有未提交的默认选择草稿。<span v-if="defaultOffer.unavailable">暂不可恢复，请从本机草稿列表核对或丢弃。</span><button :disabled="!writable || defaultOffer.unavailable" @click="restoreRecovery('defaults')">恢复默认草稿</button><button :disabled="!writable || defaultOffer.unavailable" @click="discardRecovery('defaults')">丢弃默认草稿</button></div>
        <div v-if="repairOffer" class="notice" role="status">此标签页有未提交的备份选择草稿。<span v-if="repairOffer.unavailable">暂不可恢复，请从本机草稿列表核对或丢弃。</span><button :disabled="repairOffer.unavailable || (!writable && !backups.can_repair)" @click="restoreRecovery('repair')">恢复备份选择</button><button :disabled="repairOffer.unavailable" @click="discardRecovery('repair')">丢弃备份选择</button></div>
        <div v-if="draftOffer" class="notice">此标签页有未提交的非秘密草稿。<span v-if="draftOffer.unavailable">暂不可恢复，请从本机草稿列表核对或丢弃。</span><button :disabled="!writable || draftOffer.unavailable" @click="restoreDraft">恢复草稿</button><button :disabled="!writable || draftOffer.unavailable" @click="discardDraft">丢弃草稿</button></div><div v-if="notice" class="notice" role="status">{{ notice }}</div><div v-if="pending" class="notice" :role="commitIssue ? 'alert' : undefined">有一次保存结果尚未核对。{{ commitIssue }}<button :disabled="!canReconcile" data-reconcile @click="reconcile">核对保存结果</button></div><div v-if="loading" class="empty" role="status">正在读取本机配置…</div>
        <template v-else>
          <div v-if="packet.summary.status !== 'valid'" class="notice" role="status">{{ configStates[packet.summary.status] }}。原文件保留，请在设置中核对读取位置。</div>
          <template v-if="page === 'providers' || page === 'catalog'">
            <div class="page-heading"><div><div class="eyebrow">{{ page === 'catalog' ? '跨上游查看' : '服务与模型配置' }}</div><h1>{{ page === 'catalog' ? '模型目录' : current?.name || '上游管理' }}</h1><p>查看上游接入、模型参数与备注，配置结果供 Codex 使用。</p></div><div class="actions"><button :disabled="saveBusy" @click="refresh">刷新配置</button><button v-if="writable" class="primary" data-upstream-action="create" :disabled="saveBusy || !!pending" @click="openUpstream()">＋ 添加上游</button></div></div>
            <div v-if="page === 'providers' && current" class="summary panel"><div><small>API 地址</small><span class="mono">{{ current.url }}</span></div><div><small>API 密钥</small><span>{{ current.credential_present ? '已登记' : '尚未配置' }}</span></div><div><small>模型接入</small><span>{{ current.binding_count }} 个</span></div><div v-if="writable" class="actions"><button data-upstream-action="update" :disabled="saveBusy || !!pending" @click="openUpstream('update')">编辑资料</button><button data-upstream-action="rotate" :disabled="saveBusy || !!pending" @click="openUpstream('rotate')">更换密钥</button><button data-upstream-action="copy" :disabled="saveBusy || !!pending" @click="openUpstream('copy')">另存新上游</button><button class="danger" :disabled="saveBusy || !!pending" @click="archive">归档</button><button @click="navigate('checks')">目录与文档</button></div></div>
            <div class="section-title"><h2>{{ page === 'catalog' ? '全部模型' : '已添加模型' }}</h2><span>声明、合同和实测分别记录</span></div>
            <div class="toolbar"><input v-model="query" type="search" placeholder="搜索型号、备注或标签…" aria-label="搜索模型"><select v-model="kind" aria-label="媒体类型"><option value="">全部类型</option><option value="video">视频</option><option value="image">图片</option></select><select v-model="family" aria-label="模型家族"><option value="">全部家族</option><option v-for="f in names" :key="String(f)" :value="f">{{ f }}</option></select><button :aria-pressed="favorites" :class="{chosen: favorites}" @click="favorites = !favorites">☆ 收藏</button></div>
            <CatalogTools :rows="packet.bindings.filter((b: any) => page === 'catalog' || b.upstream_id === provider)" :token="packet.summary.token" @filter="taskFit = $event; taskOnly = !!$event"/><label v-if="taskFit" class="checkline"><input v-model="taskOnly" type="checkbox">只显示参数相符的接入</label><div class="models-grid"><section class="panel table-panel"><div class="table-scroll"><table aria-label="模型列表"><thead><tr><th>模型 / 远端型号</th><th>类型 / 上游</th><th>报价</th><th>接入状态</th></tr></thead><tbody><tr v-for="b in rows" :key="b.id" :class="{selected: detail?.id === b.id}" tabindex="0" @click="selected = b.id" @keydown.enter="selected = b.id" @keydown.space.prevent="selected = b.id"><td><strong>{{ b.name }} <span v-if="b.favorite" class="star" role="img" aria-label="已收藏">★</span></strong><span class="model-id">{{ b.remote_model }}</span></td><td>{{ b.kind === 'video' ? '视频' : '图片' }}<span class="subtext">{{ b.upstream_name }}</span></td><td class="price-cell">{{ b.price_text || '价格未知' }}</td><td><span class="badge" :class="{green: b.state === 'enabled', amber: b.draft}">{{ states[b.state] }}</span></td></tr></tbody></table></div><div v-if="!rows.length" class="empty">{{ packet.upstreams.length ? '没有符合条件的接入' : '尚未配置上游' }}</div><div class="table-footer">共 {{ rows.length }} 个接入</div></section>
              <aside v-if="detail" class="panel detail" aria-label="模型详情"><span class="badge">接入详情</span><button v-if="writable" data-binding-editor :disabled="saveBusy || !!pending" @click="bindingForm?.open(detail)">编辑资料与价格</button><h2>{{ detail.name }}</h2><p>{{ detail.upstream_name }} · {{ detail.family }}</p><div class="detail-block"><h3>精确远端型号</h3><div class="mono">{{ detail.remote_model }}</div></div><div class="detail-block"><h3>已配置协议与操作</h3><div class="mono">{{ detail.adapter }}</div><div class="tags"><span v-for="op in detail.operations" :key="op" class="badge">{{ op }}</span><span v-if="!detail.operations.length">待整理接入</span></div><small>启用与目录登记不代表实际生成效果通过。</small></div><section v-if="detail.setup_gaps?.length" class="detail-block" aria-label="接入整理待办"><h3>接入整理待办</h3><p>由 Codex 核对当前上游与精确型号的文档后补齐；保存 URL/Key 无需填写这些信息。</p><ul><li v-for="gap in detail.setup_gaps" :key="gap.code">{{ gap.message }}</li></ul><small>目录名称和供应商声明不证明可执行合同；整理待办不替代任务预检。</small></section><div class="detail-block"><h3>参考与参数声明</h3><p>{{ detail.declared_capabilities?.summary || '尚未填写声明' }}</p><p v-if="detail.declared_capabilities?.references">图片 {{ detail.declared_capabilities.references.images ?? '未知' }} · 视频 {{ detail.declared_capabilities.references.videos ?? '未知' }} · 音频 {{ detail.declared_capabilities.references.audios ?? '未知' }}</p></div><div class="detail-block"><h3>价格</h3><p class="preserve">{{ detail.price_text || '价格未知' }}</p><small>报价与实际账单分别记录。</small></div><div class="detail-block"><h3>备注</h3><p class="note preserve">{{ detail.notes || '暂无备注' }}</p><div class="tags"><span v-for="tag in detail.tags" :key="tag" class="badge">{{ tag }}</span></div></div><EvidenceView :binding="detail.id" :token="packet.summary.token"/></aside>
            </div>
          </template>
          <template v-else-if="page === 'settings'"><div class="page-heading"><div><h1>设置</h1><p>核对配置位置与本机服务版本。</p></div></div><section class="panel settings"><h2>配置文件</h2><div class="path mono">{{ packet.summary.config_path }}</div><dl><dt>读取状态</dt><dd>{{ configStates[packet.summary.status] }}</dd><dt>软件版本</dt><dd>{{ packet.summary.version }}</dd><dt>Schema / 修订</dt><dd>{{ packet.summary.schema_version ?? '—' }} / {{ packet.summary.revision ?? '—' }}</dd><dt>当前页面</dt><dd>{{ writable ? "可编辑" : "只读预览" }}</dd></dl><button :disabled="saveBusy" @click="refresh">重新读取配置</button></section><section class="panel settings backup-panel"><h2>备份与恢复</h2><p v-if="repairNotice" class="hint" role="status">{{ repairNotice }}</p><button v-if="repairDraftConflict" type="button" :disabled="restoring" @click="repairDraft.fork({kind: 'repair', mode: backupMode, backup_id: backupChoice}, backupSource)">将当前备份选择另存新草稿</button><div v-if="backupConflict" class="notice">备份草稿来源或修复状态已变化。<button type="button" :disabled="restoring" @click="rebaseRecovery('repair')">使用当前文件重新核对</button></div><p class="hint">恢复前保留原文件；可读取的后续上游和接入身份会继续保留。</p><label class="field"><span>选择本机配置备份</span><select v-model="backupChoice" :disabled="restoring" aria-label="配置备份" @change="chooseBackup"><option value="">请选择备份</option><option v-if="backupChoice && !backups.backups.some((b: any) => b.id === backupChoice)" :value="backupChoice" disabled>原备份已不可用，请重新选择</option><option v-for="b in backups.backups" :key="b.id" :value="b.id">修订 {{ b.revision }} · {{ b.counts.upstreams }} 上游 / {{ b.counts.bindings }} 接入 · {{ b.id.slice(0, 10) }}</option></select></label><p v-if="!backups.backups.length" class="hint">暂无有效备份。保存配置时会自动建立备份。</p><div class="actions"><button type="button" :disabled="restoring" @click="loadBackups">刷新备份列表</button><button v-if="writable || backups.can_repair" class="primary" type="button" :disabled="!backupChoice || saveBusy || !!pending || backupConflict || !backups.backups.some((b: any) => b.id === backupChoice)" @click="restoreBackup">{{ restoring ? '正在恢复…' : backups.can_repair ? '从备份修复配置' : '恢复所选备份' }}</button></div></section></template>
          <template v-else-if="page === 'defaults'"><div class="page-heading"><div><h1>默认选择</h1><p>图片和视频分别选择，已有任务沿用原接入。</p></div></div><form class="panel settings" @submit.prevent="saveDefaults"><p v-if="defaultNotice" class="hint" role="status">{{ defaultNotice }}</p><button v-if="defaultDraftConflict" type="button" :disabled="defaultSaving" @click="defaultDraft.fork({kind: 'defaults', ...defaultForm}, defaultSource)">将当前默认输入另存新草稿</button><div v-if="defaultConflict" class="notice">默认选择草稿来源已变化。<button type="button" :disabled="defaultSaving" @click="rebaseRecovery('defaults')">使用当前默认配置重新核对</button></div><div class="default-grid"><section v-for="k in mediaKinds" :key="k.id"><h2>{{ k.name }}</h2><label class="field"><span>{{ k.name }}默认接入</span><select v-model="defaultForm[k.id].binding" :disabled="!writable || defaultSaving" :aria-label="k.name + '默认接入'"><option value="">暂不指定</option><option v-if="defaultForm[k.id].binding && !defaultOptions(k.id).some((b: any) => b.id === defaultForm[k.id].binding)" :value="defaultForm[k.id].binding" disabled>原默认未就绪，请重新选择</option><option v-for="b in defaultOptions(k.id)" :key="b.id" :value="b.id">{{ b.name }} · {{ b.upstream_name }}</option></select></label><label class="field"><span>未明确选择时</span><select v-model="defaultForm[k.id].policy" :disabled="!writable || defaultSaving" :aria-label="k.name + '默认策略'"><option value="ask">先询问我</option><option value="use-default">直接沿用默认</option></select></label><p v-if="!defaultOptions(k.id).length" class="hint">暂无已就绪的{{ k.name }}接入；可先由 Codex 整理合同。</p></section></div><button v-if="writable" class="primary" type="submit" :disabled="saveBusy || !!pending || defaultConflict || !!defaultOffer">{{ defaultSaving ? '正在保存…' : '保存默认选择' }}</button></form></template>
          <template v-else-if="page === 'checks'"><div class="page-heading"><div><h1>检查与记录</h1><p>目录、合同、小样和内容质量分别记录。</p></div></div><section class="panel settings"><h2>上游目录与文档</h2><label class="field"><span>选择上游</span><select v-model="provider" aria-label="检查上游" @change="readCatalog(false)"><option v-for="p in packet.upstreams" :key="p.id" :value="p.id">{{ p.name }}{{ p.archived ? '（已归档）' : '' }}</option></select></label><div class="actions"><button :disabled="checking || !provider" @click="readCatalog(false)">查看本机记录</button><button :disabled="checking || !provider || current?.archived" @click="readCatalog(true)">{{ checking ? '正在读取…' : '检查目录（只读）' }}</button></div><p class="hint">只有点击“检查目录”才访问所选上游。目录不代表能力、收费或内容质量。</p><div v-if="observation.message" class="notice">{{ observation.message }}</div><p v-else-if="observation.status === 'no-observation'" class="hint">当前账户尚无目录记录。已有明确文档可直接用于整理。</p><template v-if="observation.rows?.length"><div class="section-title"><h3>目录观察</h3><small>{{ observation.observed_at }}</small></div><div class="observation-list"><label v-for="r in observation.rows" :key="r.remote_model" class="checkline"><input v-model="importIds" type="checkbox" :value="r.remote_model" :disabled="!writable || !r.importable"><span class="mono">{{ r.remote_model }}</span><small>{{ r.local_status === 'registered' ? '已登记' : r.catalog_status === 'absent' ? '本次未见' : '未配置' }}</small></label></div><div v-if="writable" class="actions"><select v-model="importKind" aria-label="导入媒体类型"><option value="video">视频</option><option value="image">图片</option></select><button :disabled="!importIds.length || saveBusy || !!pending" @click="importCatalog">保存所选禁用草稿</button></div></template><div class="contract-list"><h3>已有明确文档</h3><p v-if="!observation.contracts?.length" class="hint">暂无可直接应用到此地址的内置合同。请让 Codex 核对已有文档中的精确型号、操作、参数和来源；无需先付费生成。</p><div v-for="c in observation.contracts" :key="c.id" class="contract-card"><strong>{{ c.title }}</strong><p>{{ c.source }}</p><p class="hint">{{ c.scope }}</p><button v-if="writable" :disabled="saveBusy || !!pending" @click="applyContract(c)">按此文档整理接入</button></div></div></section><Diagnostics/></template>
          <footer><span>配置保存在本机 · 视频制作继续在 Codex 中进行</span><span>{{ configStates[packet.summary.status] }}</span></footer>
        </template>
      </main>
    </div>
    <dialog ref="dialog" aria-labelledby="upstream-title" @keydown="containDialogFocus" @cancel.prevent="closeForm">
      <form @submit.prevent="saveUpstream" :aria-busy="saving">
        <div class="dialog-head"><h2 id="upstream-title">{{ form.mode === 'update' ? '编辑上游资料' : form.mode === 'rotate' ? '更换同账户密钥' : '添加上游' }}</h2><p>填写 URL 和 Key，模型接入由 Codex 整理。</p></div>
        <div class="dialog-body">
          <div v-if="commitIssue" class="notice" role="alert">{{ commitIssue }}<button type="button" :disabled="!canReconcile" data-reconcile @click="reconcile">核对保存结果</button></div>
          <fieldset class="form-fields" :disabled="saving" aria-label="上游配置"><div v-if="formError" class="error" role="alert">{{ formError }}</div><p v-if="draftNotice" class="hint">{{ draftNotice }}</p><button v-if="draftConflict" type="button" @click="upstreamDraft.fork(nonsecretForm(), formSource)">将当前上游输入另存新草稿</button><div v-if="formSource && formSource !== packet.summary.token" class="notice">配置来源已变化，请先核对并合并输入。<button type="button" @click="rebaseForm">使用当前配置重新核对</button></div>
          <label v-if="form.mode !== 'rotate'" class="field"><span>API 地址（URL）</span><input v-model="form.url" type="url" required :readonly="form.mode === 'update'" placeholder="https://example.com/v1"></label>
          <label v-if="form.mode !== 'update'" class="field"><span>API 密钥（Key）</span><input v-model="form.key" type="password" autocomplete="new-password" required></label>
          <label v-if="form.mode === 'rotate'" class="checkline"><input v-model="form.same_account" type="checkbox" required>确认新密钥属于原上游的同一个账户</label>
          <p v-if="form.mode === 'rotate'" class="hint">更换账户请添加新上游；原密钥版本继续供旧任务恢复。</p>
          <details v-else><summary>名称与备注（可选）</summary><label class="field"><span>显示名称</span><input v-model="form.name" maxlength="200" placeholder="留空使用域名"></label><label class="field"><span>备注</span><textarea v-model="form.notes" rows="4" maxlength="16000"></textarea></label></details>
          </fieldset>
        </div>
        <div class="dialog-foot"><span>只保存配置</span><div class="actions"><button type="button" :disabled="saving" @click="closeForm">取消</button><button type="submit" class="primary" :disabled="saving || !!pending || (formSource !== packet.summary.token)">{{ saving ? '正在保存…' : '保存上游' }}</button></div></div>
      </form>
    </dialog>
  </div>
</template>
