<script setup lang="ts">
import {computed, ref} from 'vue'
import ReferenceFields from './ReferenceFields.vue'
const props = defineProps<{value: Record<string, any>}>()
const emit = defineEmits<{update: [section: string, raw: string]}>()
const feedback = ref('')
type Field = {path: string, name: string, type?: 'number'|'list'|'select', options?: string[]}
const groups: {id: string, title: string, fields: Field[]}[] = [
  {id:'declared_capabilities', title:'供应商声明（不授予可执行能力）', fields:[
    {path:'summary',name:'能力摘要'}, {path:'references.images',name:'声明图片参考数量',type:'number'},
    {path:'references.videos',name:'声明视频参考数量',type:'number'}, {path:'references.audios',name:'声明音频参考数量',type:'number'},
    {path:'references.combined_total',name:'声明参考总数量',type:'number'},
    {path:'duration.minimum',name:'声明最短秒数',type:'number'}, {path:'duration.maximum',name:'声明最长秒数',type:'number'},
    {path:'resolutions',name:'声明分辨率（逗号分隔）',type:'list'}, {path:'source.kind',name:'声明来源类型',type:'select',options:['user','documentation','screenshot','catalog','observed']},
    {path:'source.url',name:'声明来源 URL'}, {path:'source.observed_at',name:'声明观察时间'},
    {path:'human_reference_note',name:'人物参考声明说明'}, {path:'audio_note',name:'声音声明说明'}]},
  {id:'capability_overrides', title:'明确合同的可执行约束', fields:[
    {path:'duration.minimum',name:'执行最短秒数',type:'number'}, {path:'duration.maximum',name:'执行最长秒数',type:'number'}, {path:'duration.step',name:'执行秒数步长',type:'number'},
    {path:'resolutions',name:'执行分辨率（逗号分隔）',type:'list'}, {path:'aspect_ratios',name:'执行宽高比（逗号分隔）',type:'list'},
    {path:'audio_control',name:'执行声音模式',type:'select',options:['unknown','explicit','model-default','unsupported','not-applicable']},
    {path:'max_reference_images',name:'旧图片数组协议参考图上限',type:'number'}, {path:'max_additional_reference_images',name:'旧图片数组协议附加参考图上限',type:'number'},
    {path:'reference_mime_types',name:'旧图片数组协议 MIME（逗号分隔）',type:'list'},
    {path:'prompt_limit.maximum',name:'提示词上限',type:'number'}, {path:'prompt_limit.counting_rule',name:'提示词计数规则',type:'select',options:['unicode-codepoints','utf16-code-units','utf8-bytes']}]},
  {id:'listed_pricing', title:'展示报价（实际账单仍未知）', fields:[
    {path:'amount',name:'展示报价金额',type:'number'}, {path:'currency',name:'展示报价币种'},
    {path:'unit',name:'展示报价单位',type:'select',options:['request','second','image','unknown']},
    {path:'display_symbol',name:'展示报价符号（不换算币种）'}, {path:'account_group',name:'展示报价账户组'}, {path:'billing_event',name:'展示报价计费事件'}, {path:'refund_policy',name:'退款说明'},
    {path:'source.kind',name:'展示报价来源类型',type:'select',options:['user','documentation','screenshot','catalog','observed']},
    {path:'source.url',name:'展示报价来源 URL'}, {path:'source.observed_at',name:'展示报价观察时间'}, {path:'source.effective_at',name:'展示报价生效时间'}, {path:'notes',name:'展示报价说明'}]},
  {id:'pricing', title:'预算价格与条件档位（不代表实付）', fields:[
    {path:'currency',name:'预算价格币种'}, {path:'status',name:'预算价格证据状态',type:'select',options:['unverified','confirmed']},
    {path:'per_request',name:'预算每请求价格',type:'number'}, {path:'per_second',name:'预算每秒价格',type:'number'},
    {path:'per_image',name:'预算每张价格（仅图片）',type:'number'},
    {path:'minimum_seconds',name:'最低计费秒数',type:'number'}, {path:'round_seconds',name:'计费秒数取整步长',type:'number'},
    {path:'version',name:'预算价格版本'}, {path:'effective_at',name:'预算价格生效时间'}, {path:'valid_until',name:'预算价格到期时间'},
    {path:'account_group',name:'预算价格账户组'}, {path:'billing_event',name:'预算价格计费事件'},
    {path:'source.kind',name:'预算价格来源类型',type:'select',options:['user','documentation','screenshot','catalog','observed']}, {path:'source.url',name:'预算价格来源 URL'}]}
]
const tierFields: Field[] = [{path:'when.operation',name:'操作'},{path:'when.resolution',name:'分辨率'},
  {path:'when.aspect_ratio',name:'宽高比'},{path:'when.minimum_seconds',name:'起始秒数',type:'number'},
  {path:'when.maximum_seconds',name:'截止秒数',type:'number'},{path:'per_request',name:'每请求价格',type:'number'},{path:'per_second',name:'每秒价格',type:'number'},
  {path:'per_image',name:'每张价格（仅图片）',type:'number'}]
const conditionFields: Field[] = [{path:'when.operation',name:'操作',type:'select',options:['text-to-video','image-to-video','reference-to-video','text-to-image','image-edit','video-edit','video-extend']},
  {path:'when.resolution',name:'分辨率'}, {path:'when.aspect_ratio',name:'宽高比'}, {path:'max_seconds',name:'最长秒数',type:'number'}]
function parse(section: string) {
  try {const obj = JSON.parse(props.value[section] || '{}'); return obj && typeof obj === 'object' && !Array.isArray(obj) ? obj : null}
  catch {return null}
}
function get(obj: any, path: string, list=false) {
  const value = path.split('.').reduce((current, key) => current?.[key], obj)
  return list && Array.isArray(value) ? value.join(', ') : value ?? ''
}
function put(obj: any, path: string, value: string, type?: string) {
  const keys=path.split('.'), last=keys.pop()!, parents: [any,string][]=[]
  for(const key of keys) {if(!obj[key] || typeof obj[key] !== 'object' || Array.isArray(obj[key])) obj[key]={};parents.push([obj,key]);obj=obj[key]}
  if(value === '') delete obj[last]
  else if(type === 'number') {const number=Number(value);if(!Number.isFinite(number)) throw new Error('请填写有限数字。');obj[last]=number}
  else obj[last] = type === 'list' ? value.split(',').map(v=>v.trim()).filter(Boolean) : value
  for(const [parent,key] of parents.reverse()) if(!Object.keys(parent[key]).length) delete parent[key]
}
function publish(section: string, obj: any) {emit('update',section,JSON.stringify(obj,null,2));feedback.value='已应用到当前模型表单；点击“保存模型资料”后才写入配置。'}
function update(section: string, field: Field, event: Event, index?: number, array='tiers') {
  const obj = parse(section); if(!obj) return
  try {put(index === undefined ? obj : obj[array][index],field.path,(event.target as HTMLInputElement).value,field.type);publish(section,obj)}
  catch(e: any) {feedback.value=e.message}
}
const tiers = computed<any[]>(() => {const value=parse('pricing')?.tiers;return Array.isArray(value)?value:[]})
const conditions = computed<any[]>(() => {const value=parse('capability_overrides')?.conditions;return Array.isArray(value)?value:[]})
function addCondition() {
  const obj=parse('capability_overrides');if(!obj)return
  if(obj.conditions !== undefined && !Array.isArray(obj.conditions)){feedback.value='现有执行条件需要 JSON 数组，请先在下方修正。';return}
  obj.conditions=[...(obj.conditions || []),{when:{}}];publish('capability_overrides',obj)
}
function removeCondition(index: number) {const obj=parse('capability_overrides');if(obj){obj.conditions.splice(index,1);if(!obj.conditions.length)delete obj.conditions;publish('capability_overrides',obj)}}
function addTier() {
  const obj=parse('pricing');if(!obj)return
  if(obj.tiers !== undefined && !Array.isArray(obj.tiers)){feedback.value='现有档位需要 JSON 数组，请先在下方修正。';return}
  obj.tiers=[...(obj.tiers || []),{when:{}}];publish('pricing',obj)
}
function removeTier(index: number) {const obj=parse('pricing');if(obj){obj.tiers.splice(index,1);if(!obj.tiers.length)delete obj.tiers;publish('pricing',obj)}}
function clear(section: string) {if(confirm('清除此组声明或价格？保存模型资料后恢复为未知，不会记录为零价或已验证。'))publish(section,{})}
</script>
<template><section class="contract-fields" aria-label="结构化合同与报价编辑">
  <h3>结构化填写</h3><p class="hint">仅填写有明确依据的内容，留空保持未知。这里和下方 JSON 共用当前表单，不会单独保存或发起生成。</p>
  <p v-if="feedback" class="hint" role="status">{{ feedback }}</p>
  <details v-for="group in groups" :key="group.id" class="contract-group"><summary>{{ group.title }}</summary>
    <p v-if="!parse(group.id)" class="error" role="alert">此组 JSON 尚不完整，请先在下方 JSON 输入中修正；结构化字段暂不可编辑。</p>
    <template v-else><div class="task-fields"><label v-for="f in group.fields" :key="f.path" class="field"><span>{{ f.name }}</span>
      <select v-if="f.type === 'select'" :aria-label="f.name" :value="get(parse(group.id),f.path)" @change="update(group.id,f,$event)"><option value="">未记录</option><option v-for="v in f.options" :key="v" :value="v">{{ v }}</option></select>
      <input v-else :aria-label="f.name" :type="f.type === 'number' ? 'number' : 'text'" :step="f.type === 'number' ? 'any' : undefined" :value="get(parse(group.id),f.path,f.type === 'list')" @change="update(group.id,f,$event)">
    </label></div>
    <template v-if="group.id === 'capability_overrides'">
      <h4>按条件限制时长</h4><p class="hint">条件留空表示不限定该项；同时符合多条时取最严格上限，不能扩展基础时长范围。</p>
      <fieldset v-for="(condition,index) in conditions" :key="index" class="price-tier"><legend>执行条件 {{ index + 1 }}</legend><div class="task-fields"><label v-for="f in conditionFields" :key="f.path" class="field"><span>{{ f.name }}</span>
        <select v-if="f.type === 'select'" :aria-label="`执行条件 ${index+1} ${f.name}`" :value="get(condition,f.path)" @change="update(group.id,f,$event,index,'conditions')"><option value="">不限操作</option><option v-for="v in f.options" :key="v" :value="v">{{ v }}</option></select>
        <input v-else :aria-label="`执行条件 ${index+1} ${f.name}`" :type="f.type === 'number' ? 'number' : 'text'" :step="f.type === 'number' ? 'any' : undefined" :value="get(condition,f.path)" @change="update(group.id,f,$event,index,'conditions')">
      </label></div><button type="button" @click="removeCondition(index)">删除此执行条件</button></fieldset>
      <button type="button" @click="addCondition">添加执行条件</button>
      <ReferenceFields :raw="value.capability_overrides" @update="emit('update','capability_overrides',$event)" />
    </template>
    <template v-if="group.id === 'pricing'"><p class="hint">档位按明确条件匹配；重叠、缺少条件或不匹配时估算未知，不能任取较低价。每档至少填写一种价格；选中档位的费率替代基础费率。每请求费与每秒费或每张费相加。按张仅用于图片，张数来自请求明确发送的出图数量；省略数量时保持未知，不推定供应商默认值。参考图数量、GIF 帧数和返回图片数量不参与预算张数。按张不能混用秒费、时长规则或时长档位条件；其他单位仅保留在展示报价或说明中。</p>
      <fieldset v-for="(tier,index) in tiers" :key="index" class="price-tier"><legend>价格档位 {{ index + 1 }}</legend><div class="task-fields"><label v-for="f in tierFields" :key="f.path" class="field"><span>{{ f.name }}</span><input :aria-label="`档位 ${index+1} ${f.name}`" :type="f.type === 'number' ? 'number' : 'text'" :step="f.type === 'number' ? 'any' : undefined" :value="get(tier,f.path)" @change="update('pricing',f,$event,index)"></label></div><button type="button" @click="removeTier(index)">删除此档位</button></fieldset>
      <button type="button" @click="addTier">添加价格档位</button>
    </template><button type="button" class="clear-claim" @click="clear(group.id)">清除此组，恢复未知</button></template>
  </details>
</section></template>
<style scoped>
.contract-fields{margin:24px 0;border-top:1px solid var(--line);padding-top:20px}.contract-fields>h3{font-size:14px}.contract-group{padding:12px;background:#f6f8f7;border-radius:8px}.contract-group>summary{color:var(--accent)}.price-tier{min-width:0;border:1px solid var(--line);border-radius:8px;margin:18px 0;padding:12px}.price-tier legend{font-size:12px}.clear-claim{margin:12px 0 0 8px}.contract-fields .task-fields{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}.contract-fields .field{margin:12px 0}
</style>
