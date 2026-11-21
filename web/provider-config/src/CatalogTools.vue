<script setup lang="ts">
import {ref, watch} from 'vue'
import {request} from './api'
const props = defineProps<{rows: any[], token?: string}>()
const emit = defineEmits<{filter: [value: any]}>()
const chosen = ref<string[]>([]), cards = ref<any[]>([]), errors = ref(''), busy = ref(false), fit = ref<any[]>([])
const scenario = ref<any>({operation:'text-to-video',seconds:5,resolution:'720p',aspect_ratio:'9:16'})
const counts = ref<any>({image:0,video:0,audio:0})
watch(() => props.token, () => {clear(); chosen.value = []})
// Results describe one set of inputs. A changed scenario/selection invalidates
// them, including an older response that arrives after the user edits again.
let comparisonVersion = 0, filterVersion = 0
watch([scenario,counts], () => {comparisonVersion++; filterVersion++; clear()}, {deep:true,flush:'sync'})
watch(chosen, () => {comparisonVersion++; cards.value=[]}, {deep:true,flush:'sync'})
function values() {
  const s: any = {operation:scenario.value.operation}
  if (!['text-to-image','image-edit'].includes(s.operation)) {
    for (const k of ['seconds','resolution','aspect_ratio']) if (scenario.value[k]) s[k] = scenario.value[k]
  }
  return s
}
async function filter() {
  const version = ++filterVersion
  busy.value = true; errors.value = ''
  try { const r = await request('catalog/filter', {scenario: {...values(),reference_counts:counts.value}}); if(version !== filterVersion)return; fit.value = r.rows; emit('filter', Object.fromEntries(r.rows.map((v:any) => [v.id,v.fit]))) }
  catch (e:any) {if(version === filterVersion)errors.value = e.message}
  finally {busy.value = false}
}
async function compare() {
  const version = ++comparisonVersion
  busy.value = true; errors.value = ''
  try { const r = await request('catalog/compare', {bindings:chosen.value,scenario:values()}); if(version === comparisonVersion)cards.value = r.cards }
  catch (e:any) {if(version === comparisonVersion)errors.value = e.message}
  finally {busy.value = false}
}
function clear() {comparisonVersion++;filterVersion++;errors.value='';fit.value=[];cards.value=[];emit('filter',null)}
</script>
<template><details class="panel catalog-tools">
  <summary>按任务条件筛选与比较（可选）</summary>
  <p class="hint">仅核对已配置参数；凭据、完整素材、质量和实际付款仍需各自检查。修改条件后请重新筛选或比较。</p>
  <div v-if="errors" class="error" role="alert">{{ errors }}</div>
  <div class="task-fields">
    <label class="field"><span>操作</span><select v-model="scenario.operation" aria-label="任务操作"><option v-for="op in ['text-to-video','image-to-video','reference-to-video','text-to-image','image-edit']" :key="op">{{ op }}</option></select></label>
    <template v-if="!['text-to-image','image-edit'].includes(scenario.operation)">
      <label class="field"><span>秒数</span><input v-model.number="scenario.seconds" type="number" min="1" aria-label="任务秒数"></label>
      <label class="field"><span>分辨率</span><input v-model="scenario.resolution" aria-label="任务分辨率"></label>
      <label class="field"><span>画幅</span><input v-model="scenario.aspect_ratio" aria-label="任务画幅"></label>
    </template>
    <label v-for="(name,k) in {image:'图片',video:'视频',audio:'音频'}" :key="k" class="field"><span>{{ name }}参考数量</span><input v-model.number="counts[k]" type="number" min="0" step="1"></label>
  </div>
  <div class="actions"><button :disabled="busy" @click="filter">按任务筛选</button><button @click="clear">清除任务筛选</button></div>
  <div v-if="fit.length" class="fit-results"><p v-for="r in fit.filter(v => rows.some(b => b.id === v.id))" :key="r.id">
    <strong>{{ rows.find(b => b.id === r.id)?.name }}</strong> · {{ r.fit.matches ? '参数相符' : r.fit.status === 'excluded' ? '已排除' : '待核实' }}
    <small>{{ [...r.fit.reasons,...r.fit.unknowns].join('；') }}</small>
    <small v-if="r.fit.quote?.explanation">计费：{{ r.fit.quote.explanation }}</small>
  </p></div>
  <h3>选择二至四个接入并排比较</h3>
  <div class="comparison-picker"><label v-for="b in rows" :key="b.id" class="checkline"><input v-model="chosen" type="checkbox" :value="b.id" :disabled="chosen.length >= 4 && !chosen.includes(b.id)">{{ b.name }} · {{ b.upstream_name }}</label></div>
  <button :disabled="busy || chosen.length < 2" @click="compare">比较所选接入</button>
  <div v-if="cards.length" class="comparison-grid"><article v-for="c in cards" :key="c.id"><h3>{{ c.name }}</h3><dl><template v-for="(v,k) in c.fields" :key="String(k)"><dt>{{ k }}</dt><dd>{{ v }}</dd></template></dl></article></div>
</details></template>
