<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref,computed} from 'vue'
type Transfer = {source?:string; model?:string; quant?:string; active:boolean; state?:string; file?:string; part?:number; total?:number; received?:number; bytesPerSecond?:number; error?:string}
import {useRoute} from 'vue-router'
const route=useRoute()
const filter=ref('all')
const props = defineProps<{models:{id:string;name:string;mode:string;quantizations:{id:string;installed:boolean;downloadBytes?:number}[]}[]; t:(zh:string,en:string)=>string; api:(path:string, options?:RequestInit)=>Promise<Response>; refresh:()=>Promise<void>}>()
const visible = computed(()=>props.models.filter(m=>filter.value === 'all' || m.mode === filter.value)
  .sort((a,b)=>Number(b.id===route.query.model)-Number(a.id===route.query.model)))
const job = ref<Transfer>({active:false})
const source = ref(sessionStorage.getItem('studio-download-source') === 'mirror' ? 'mirror' : 'official')
const waiting = ref(false)
const warning = ref('')
let timer:number
let serial = 0
let mounted = true
const labels = computed(()=>({
  downloading:job.value.total ? job.value.total === job.value.received ? props.t('校验文件','Verifying file') : props.t('正在下载','Downloading') : props.t('连接模型源…','Connecting to source…'),
  cancelling:props.t('正在取消…','Cancelling…'),cancelled:props.t('已取消','Cancelled'),
  pausing:props.t('正在暂停…','Pausing…'),paused:props.t('已暂停 · 保留下载进度','Paused · progress saved'),
  failed:props.t('下载失败','Download failed'),complete:props.t('已安装','Installed')
}))
const stateLabel = computed(()=>labels.value[job.value.state as keyof typeof labels.value])
const size = (n=0)=>(n/1048576).toFixed(1)+' MiB'
async function update(path='/models/download', options?:RequestInit) {
  const version = ++serial
  clearTimeout(timer)
  try {
    const data = await (await props.api(path,options)).json() as Transfer
    if (!mounted || version !== serial) return
    const wasComplete = job.value.state === 'complete'
    if (data.active && data.source) source.value = data.source
    job.value = data
    warning.value = ''
    if (data.state === 'complete' && !wasComplete) await props.refresh()
  } catch(e) { if (mounted && version === serial) warning.value = props.t('无法获取下载状态，将重新连接。','Cannot read download status. Reconnecting.')+' '+String(e) }
  finally {
    if (mounted && version === serial) {
      waiting.value = false
      timer = window.setTimeout(()=>void update(),job.value.active || warning.value ? 700 : 3000)
    }
  }
}
function start(model:string,quant:string) {
  waiting.value = true
  sessionStorage.setItem('studio-download-source',source.value)
  void update('/models/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model,quant,source:source.value})})
}
function cancel() {
  if (!confirm(props.t('取消下载并删除此任务的未完成文件？','Cancel and delete partial files for this download?'))) return
  waiting.value = true
  void update('/models/download/cancel',{method:'POST'})
}
function pause() {
  waiting.value = true
  void update('/models/download/pause',{method:'POST'})
}
async function remove(model:string,quant:string) {
  if (!confirm(props.t('删除此模型权重？其他模型使用的共享文件将保留。','Delete these weights? Files shared with installed models are kept.'))) return
  waiting.value = true
  try { await props.api('/models/'+model+'/'+quant,{method:'DELETE'}); await props.refresh(); await update() }
  catch(e) { warning.value=String(e) }
  finally { waiting.value=false }
}
onMounted(()=>void update())
onBeforeUnmount(()=>{ mounted=false; clearTimeout(timer) })
</script>
<template>
  <section class="stack">
    <RouterLink v-if="['clone','custom','design'].includes(String(route.query.from))" :to="{name:String(route.query.from)}" class="model-link">← {{t('返回创作','Back to creation')}}</RouterLink>
    <div class="panel model-tools"><label>{{t('模型用途','Model family')}}<select v-model="filter"><option value="all">{{t('全部','All')}}</option><option value="custom">{{t('预设音色','Preset voices')}}</option><option value="clone">{{t('声音克隆','Voice clone')}}</option><option value="design">{{t('声音设计','Voice design')}}</option></select></label><label>{{t('模型下载源','Download source')}}<select v-model="source" :disabled="job.active"><option value="official">Hugging Face</option><option value="mirror">HF-Mirror</option></select></label></div>
    <article v-if="job.model" class="panel stack transfer">
      <div class="actions"><strong>{{job.model}} · {{job.quant}}</strong><span role="status">{{stateLabel}}</span></div>
      <small v-if="job.file">{{job.part}} / 2 · {{job.file}}</small>
      <progress v-if="job.state !== 'complete'" aria-label="Download progress" :value="job.total ? job.received : undefined" :max="job.total || 1"/>
      <div v-if="job.total" class="actions"><span>{{Math.floor(100*(job.received || 0)/job.total)}}% · {{size(job.received)}} / {{size(job.total)}}</span><span v-if="job.active">{{size(job.bytesPerSecond)}}/s</span></div>
      <p v-if="job.error" role="alert">{{t('检查网络，或切换下载源后重试。','Check your connection or switch source, then retry.')}} {{job.error}}</p>
      <div v-if="job.active" class="controls"><button :disabled="waiting || job.state !== 'downloading'" @click="pause">{{t('暂停下载','Pause download')}}</button><button :disabled="waiting || job.state !== 'downloading'" @click="cancel">{{t('取消并清除下载','Cancel and discard')}}</button></div>
      <button v-else-if="job.state === 'paused' || job.state === 'failed'" class="primary" :disabled="waiting" @click="start(job.model,job.quant!)">{{job.state === 'paused' ? t('继续下载','Resume download') : t('重试下载','Retry download')}}</button>
    </article>
    <p v-if="warning" role="alert">{{warning}}</p>
    <article v-for="item in visible" :key="item.id" class="panel stack">
      <div><strong>{{item.name.replace('Qwen/Qwen3-TTS-12Hz-','')}}</strong><p><small>{{item.mode === 'clone' ? t('参考音频克隆','Reference audio cloning') : item.mode === 'design' ? t('声音描述生成','Voice design') : t('预设音色生成','Preset voices')}}</small></p></div>
      <div class="controls"><button :class="{primary:item.id===route.query.model && q.id===route.query.quant && !q.installed}" v-for="q in item.quantizations" :key="q.id" :disabled="waiting || job.active" @click="q.installed ? remove(item.id,q.id) : start(item.id,q.id)">{{q.id}} · {{q.installed ? t('已安装 · 删除','Installed · Remove') : t('下载','Download')}} <small v-if="!q.installed">{{size(q.downloadBytes)}}</small></button></div>
    </article>
  </section>
</template>
