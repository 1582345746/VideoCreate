<script setup lang="ts">
import {computed, ref} from 'vue'
const props = defineProps<{raw: string}>()
const emit = defineEmits<{update: [raw: string]}>()
const feedback = ref('')
const kinds = [
  {id:'image', name:'图片', roles:[['opening-frame','首帧'],['identity','角色身份'],['prop','道具'],['scene','场景'],['style','风格']]},
  {id:'video', name:'视频', roles:[['motion','动作'],['scene','场景'],['style','风格']]},
  {id:'audio', name:'音频', roles:[['sound','声音']]}
]
const combinations = [ ['image'], ['video'], ['audio'], ['image','video'], ['image','audio'], ['video','audio'], ['image','video','audio'] ]
const labels: Record<string,string> = {image:'图片',video:'视频',audio:'音频'}
const common = [
  {key:'maximum_count', name:'最多文件数', integer:true}, {key:'maximum_bytes', name:'单文件字节上限', integer:true},
  {key:'maximum_total_bytes', name:'同类总字节上限', integer:true}
]
const optional: Record<string, {key:string,name:string,integer?:boolean}[]> = {
  image:[{key:'maximum_width',name:'最大宽度（像素）',integer:true},{key:'maximum_height',name:'最大高度（像素）',integer:true}],
  video:[{key:'maximum_duration_seconds',name:'单文件最长秒数'},{key:'maximum_total_duration_seconds',name:'同类总时长上限'},
    {key:'maximum_width',name:'最大宽度（像素）',integer:true},{key:'maximum_height',name:'最大高度（像素）',integer:true}],
  audio:[{key:'maximum_duration_seconds',name:'单文件最长秒数'},{key:'maximum_total_duration_seconds',name:'同类总时长上限'},
    {key:'maximum_sample_rate',name:'最高采样率（Hz）',integer:true},{key:'maximum_channels',name:'最多声道数',integer:true}]
}
function object(value: any) {return !!value && typeof value === 'object' && !Array.isArray(value)}
const parent = computed<any>(() => {try {const value=JSON.parse(props.raw);return object(value)?value:null}catch{return null}})
const limits = computed<any>(() => parent.value?.media_reference_limits)
const editable = computed(() => object(limits.value) && kinds.every(k => limits.value[k.id] === undefined ||
  (object(limits.value[k.id]) && ['roles','mime_types'].every(key=>limits.value[k.id][key] === undefined ||
    (Array.isArray(limits.value[k.id][key]) && limits.value[k.id][key].every((v:any)=>typeof v==='string'))))) &&
  (limits.value.allowed_combinations === undefined || (Array.isArray(limits.value.allowed_combinations) &&
    limits.value.allowed_combinations.every((c:any)=>Array.isArray(c)&&c.every((v:any)=>typeof v==='string')))))
function publish(obj: any) {emit('update',JSON.stringify(obj,null,2));feedback.value='已应用到当前表单，尚未保存配置。必填约束需依据明确合同逐项填写。'}
function begin() {
  if (!parent.value || limits.value !== undefined) return
  const obj=JSON.parse(props.raw);obj.media_reference_limits={image:{},video:{},audio:{},allowed_combinations:[]};publish(obj)
}
function mutate(edit: (limits: any) => void) {
  if(!editable.value)return
  const obj=JSON.parse(props.raw);edit(obj.media_reference_limits);publish(obj)
}
function scalar(key: string, event: Event, kind?: string, integer=false) {
  const raw=(event.target as HTMLInputElement).value
  if (raw !== '' && key !== 'mime_types' && key !== 'audio_reference_with_generated_audio') {
    const n=Number(raw)
    if(!Number.isFinite(n) || (integer && !Number.isSafeInteger(n))) {feedback.value=integer?'请填写有效的安全整数。':'请填写有限数字。';return}
  }
  mutate(limits=>{
    const target=kind?(limits[kind] ||= {}):limits
    if(raw==='')delete target[key]
    else if(key==='mime_types')target[key]=raw.split(',').map(s=>s.trim()).filter(Boolean)
    else target[key]=key==='audio_reference_with_generated_audio'?raw==='true':Number(raw)
  })
}
function role(kind: string, name: string, checked: boolean) {
  mutate(limits=>{const target=(limits[kind] ||= {});target.roles=checked?[...(target.roles || []),name]:(target.roles || []).filter((r:string)=>r!==name)})
}
const comboKey = (values: string[]) => [...new Set(values)].sort().join(',')
function selected(combo: string[]) {return (limits.value?.allowed_combinations || []).some((values:string[])=>comboKey(values)===comboKey(combo))}
function combination(combo: string[], checked: boolean) {
  mutate(limits=>{limits.allowed_combinations=checked?[...(limits.allowed_combinations||[]),combo]:(limits.allowed_combinations||[]).filter((values:string[])=>comboKey(values)!==comboKey(combo))})
}
function remove() {
  if(parent.value && confirm('移除此组参考约束并恢复未知？已启用的参考操作必须重新核对，保存时仍会验证。')) {
    const obj=JSON.parse(props.raw);delete obj.media_reference_limits;publish(obj)
  }
}
</script>
<template><section class="reference-contract" aria-label="多媒体参考合同编辑">
  <h4>图片、视频与音频参考约束</h4>
  <p class="hint">仅依据明确文档维护；当前执行合同适用于 xingapi-video-v2。数量、字节、角色与组合共同约束，不会因填写声明而自动启用。实际参考素材和同类素材的顺序继续在 Codex 制作计划中维护。</p>
  <p v-if="feedback" class="hint" role="status">{{ feedback }}</p>
  <button v-if="parent && limits === undefined" type="button" @click="begin">填写明确的多媒体参考合同</button>
  <p v-else-if="!editable" class="error" role="alert">参考约束结构不完整或类型不符，请先在下方 JSON 中修正；当前内容保留。</p>
  <template v-else>
    <p class="hint">总数量、总字节、URL 有效期、声音并用选项、允许组合，以及每类数量/字节/MIME/角色为必填项。不支持的类别明确填 0 个，MIME 和角色填空列表；其余上限仍需正数。留空不会推断为零或供应商默认。</p>
    <div class="task-fields"><label v-for="[key,name] in [['maximum_total_count','三类参考总数量上限'],['maximum_total_bytes','三类参考总字节上限'],['minimum_url_validity_seconds','URL 至少剩余有效秒数']]" :key="key" class="field"><span>{{ name }}</span><input type="number" step="1" :aria-label="name" :value="limits[key] ?? ''" @change="scalar(key!,$event,undefined,true)"></label>
      <label class="field"><span>音频参考与生成声音并用</span><select aria-label="音频参考与生成声音并用" :value="limits.audio_reference_with_generated_audio === undefined ? '' : String(limits.audio_reference_with_generated_audio)" @change="scalar('audio_reference_with_generated_audio',$event)"><option value="">未确认</option><option value="true">合同允许</option><option value="false">合同不允许</option></select></label>
    </div>
    <fieldset><legend>允许的参考组合</legend><label v-for="combo in combinations" :key="comboKey(combo)" class="checkline"><input type="checkbox" :aria-label="'允许组合：' + combo.map(k=>labels[k]).join(' + ')" :checked="selected(combo)" @change="combination(combo,($event.target as HTMLInputElement).checked)">{{ combo.map(k=>labels[k]).join(' + ') }}</label></fieldset>
    <fieldset v-for="kind in kinds" :key="kind.id"><legend>{{ kind.name }}参考</legend>
      <div class="task-fields"><label v-for="f in [...common,...optional[kind.id]!]" :key="f.key" class="field"><span>{{ f.name }}</span><input type="number" :step="f.integer ? '1' : 'any'" :aria-label="kind.name + '参考' + f.name" :value="limits[kind.id]?.[f.key] ?? ''" @change="scalar(f.key,$event,kind.id,!!f.integer)"></label>
        <label class="field"><span>MIME 类型（逗号分隔）</span><input :aria-label="kind.name + '参考 MIME 类型'" :value="limits[kind.id]?.mime_types?.join(', ') || ''" @change="scalar('mime_types',$event,kind.id)"></label>
      </div>
      <p class="hint">{{ kind.id === 'image' ? '首帧只用于明确支持的首帧语义，不代表尾帧锁定。' : '允许此类参考时，必须填写单文件与同类总时长上限。' }}不支持的类别可明确设置空 MIME 和角色列表。</p>
      <div class="actions"><button type="button" @click="mutate(limits=>{(limits[kind.id] ||= {}).mime_types=[];(limits[kind.id] ||= {}).roles=[]})">{{ kind.name }} MIME 与角色设为空列表</button></div>
      <div class="tags"><label v-for="[roleName,label] in kind.roles" :key="roleName" class="checkline"><input type="checkbox" :aria-label="kind.name + '参考角色：' + label" :checked="limits[kind.id]?.roles?.includes(roleName) || false" @change="role(kind.id,roleName!,($event.target as HTMLInputElement).checked)">{{ label }}</label></div>
    </fieldset>
    <button type="button" @click="remove">移除参考约束，恢复未知</button>
  </template>
</section></template>
<style scoped>
.reference-contract{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}.reference-contract h4{font-size:13px}.reference-contract fieldset{min-width:0;border:1px solid var(--line);border-radius:8px;margin:16px 0;padding:12px}.reference-contract legend{font-size:12px}.reference-contract .task-fields{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}.reference-contract .field{margin:10px 0}.reference-contract .tags{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
</style>
