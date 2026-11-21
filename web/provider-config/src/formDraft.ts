import {ref} from 'vue'
import {request, stateKey} from './api'

// Browser storage contains only an opaque identifier. Each mutation uses the
// last observed byte version, including when tabs share the same cookie.
export function useFormDraft(storageKey: string) {
  const token = ref(''), version = ref('')
  const offer = ref<any>(null), notice = ref(''), conflict = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let queue: Promise<void> = Promise.resolve()
  let generation = 0
  function remember(result: any) {
    token.value = result.draft_token; version.value = result.draft_version
    sessionStorage.setItem(stateKey(storageKey), token.value)
    // Legacy tokens have no path identity. Migrate only after this server has
    // successfully loaded/saved that exact capability; a 404 elsewhere preserves it.
    if (sessionStorage.getItem(storageKey) === token.value) sessionStorage.removeItem(storageKey)
  }
  function failed(e: any) {
    if (e.code === 'draft_conflict' || e.code === 'draft_owner' || e.code === 'draft_missing') conflict.value = true
    notice.value = e.message || '非秘密草稿暂存失败；关闭前请先完成保存。'
  }
  function schedule(form: any, source: string) {
    clearTimeout(timer)
    if (!source || offer.value || conflict.value) return
    const snapshot = JSON.parse(JSON.stringify(form)), current = ++generation
    timer = setTimeout(() => {
      queue = queue.then(async () => {
        if (current !== generation || conflict.value) return
        try {
          const result = await request('drafts/save', {draft_token: token.value || undefined,
            expected_version: version.value || undefined, source_token: source, form: snapshot})
          remember(result)
          notice.value = result.omitted_sections?.length
            ? '基础输入已暂存；无效或含未知字段的高级 JSON 未暂存，关闭前请核对。'
            : storageKey === 'vc-upstream-draft' ? '非秘密输入已暂存；API 密钥不会保存到表单草稿。'
            : '非秘密输入已暂存七天；恢复后仍须核对并手动保存。'
        } catch (e: any) { failed(e) }
      })
    }, 600)
  }
  async function adopt(row: any) {
    ++generation; clearTimeout(timer); await queue
    const result = await request('drafts/load', {draft_token: row.draft_token, expected_version: row.draft_version})
    remember(result); offer.value = result; conflict.value = false
  }
  async function find() {
    token.value = sessionStorage.getItem(stateKey(storageKey)) || sessionStorage.getItem(storageKey) || ''
    if (!token.value) return
    try { const result = await request('drafts/load', {draft_token: token.value}); remember(result); offer.value = result }
    catch (e: any) {
      if (e.code === 'draft_missing') { forget(); return }
      notice.value = e.message; offer.value = {unavailable: true}
    }
  }
  async function restore() {
    try {
      const result = await request('drafts/load', {draft_token: token.value, claim: true, expected_version: version.value})
      remember(result); offer.value = null; conflict.value = false
      notice.value = result.conflict ? '草稿来源已变化，必须核对当前配置后再保存。' : '已恢复非秘密输入；尚未修改配置。'
      if (result.omitted_sections?.length) notice.value += '部分高级 JSON 未恢复，请重新核对。'
      return result
    } catch (e: any) { failed(e); throw e }
  }
  function forget() {
    token.value = ''; version.value = ''; offer.value = null; notice.value = ''; conflict.value = false
    sessionStorage.removeItem(stateKey(storageKey))
  }
  async function discard() {
    ++generation; clearTimeout(timer); await queue
    // On failure preserve the capability so the user can retry explicit discard.
    try {
      if (token.value) await request('drafts/discard', {draft_token: token.value, expected_version: version.value || undefined})
      forget()
    } catch (e: any) { failed(e); throw e }
  }
  async function fork(form: any, source: string) {
    ++generation; clearTimeout(timer); await queue
    forget(); schedule(form, source)
  }
  async function cleanup() {
    try { await discard(); return true }
    catch { forget(); return false } // A successful config commit stays successful.
  }
  function forgetOffer(identity: string) {
    if (token.value === identity && offer.value) { stop(); forget() }
  }
  function stop() { ++generation; clearTimeout(timer) }
  return {token, version, offer, notice, conflict, schedule, find, adopt, restore, discard, cleanup, fork, stop, forgetOffer}
}
