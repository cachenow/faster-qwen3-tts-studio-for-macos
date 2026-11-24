<script setup lang="ts">
import { computed, nextTick, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { AudioLines, Boxes, History, Layers, Library, MessagesSquare, Mic, Settings, Sparkles, Volume2 } from 'lucide-vue-next'
import WaveSurfer from 'wavesurfer.js'
import { Preview, recordedWav } from './audio'
import ModelManager from './ModelManager.vue'
import MicrophoneCapture from './MicrophoneCapture.vue'
import StorageManager from './StorageManager.vue'
import QueueWorkspace from './QueueWorkspace.vue'
import { usePreferences } from './preferences'

type Model = { id: string; name: string; mode: string; quantizations: {id: string; installed: boolean}[] }
type Record = { id: string; duration: number; ttfa: number; rtf: number; mock: boolean; request: {text: string; model: string} }
type Voice = { id: string; name: string; notes: string; reference: string; transcript: string; xvec: boolean; tags?: string[]; favorite?: boolean }
const route = useRoute()
const router = useRouter()
const preferences = usePreferences()
const {locale, theme} = storeToRefs(preferences)
const t = (zh: string, en: string) => locale.value === 'zh' ? zh : en
const nav = [
  ['custom', '语音生成', 'Speech', Volume2], ['clone', '声音克隆', 'Voice clone', Mic],
  ['design', '声音设计', 'Voice design', Sparkles],
  ['dialogue', '多角色对话', 'Dialogue', MessagesSquare], ['batch', '批量生成', 'Batch', Layers],
  ['voices', '我的音色', 'Voice library', Library],
  ['history', '历史记录', 'History', History],
  ['models', '模型管理', 'Models', Boxes], ['settings', '系统设置', 'Settings', Settings],
] as const
const mode = computed(() => String(route.name || 'custom'))
const title = computed(() => { const item = nav.find(([id]) => id === mode.value) ?? nav[0]; return t(item[1], item[2]) })
const models = ref<Model[]>([])
const model = ref('')
const quant = ref('Q8_0')
const selection = computed(() => models.value.filter(item => item.mode === mode.value))
const weightsReady = computed(() => health.value?.mode === 'mock' || !!selection.value
  .find(item => item.id === model.value)?.quantizations.find(item => item.id === quant.value)?.installed)
const generationHint = computed(() => {
  if (!health.value) return t('正在连接本地服务…','Connecting to the local service…')
  if (!weightsReady.value) return t('请先安装所选模型。','Install the selected model to continue.')
  if (mode.value === 'clone' && !reference.value) return t('请先导入参考音频或录音。','Import or record a reference clip.')
  if (mode.value === 'clone' && !xvec.value && !transcript.value.trim()) return t('填写参考音频转录，或选择 X-vector Only。','Add the reference transcript or choose X-vector Only.')
  if (mode.value === 'design' && !instruct.value.trim()) return t('请描述想要的声音。','Describe the voice to generate.')
  if (!text.value.trim()) return t('输入朗读文本后即可生成。','Enter a script to generate audio.')
  return ''
})
const text = ref('')
const language = ref('Auto')
const temperature = ref(0.9)
const topK = ref(50)
const topP = ref(1)
const maxTokens = ref(2048)
const instruct = ref('')
const speaker = ref('Vivian')
const transcript = ref('')
const xvec = ref(false)
const reference = ref('')
const referenceAudio = ref('')
const referenceWave = ref<HTMLElement>()
const trimStart = ref(0)
const trimEnd = ref<number>()
const health = ref<{mode: string; arch: string; platform: string; metalVerified: boolean}>()
const voices = ref<Voice[]>([])
const voiceSearch = ref('')
const voiceLayout = ref('cards')
const editVoice = ref<Voice>()
const editTags = ref('')
const visibleVoices = computed(() => voices.value.filter(voice =>
  [voice.name, voice.notes, ...(voice.tags ?? [])].join(' ').toLowerCase().includes(voiceSearch.value.trim().toLowerCase())
).sort((a, b) => Number(!!b.favorite) - Number(!!a.favorite)))
const voiceName = ref('')
const voiceNotes = ref('')
const items = ref<Record[]>([])
const output = ref('')
const result = ref<Record>()
const pending = ref('')
const error = ref('')
const notice = ref('')
watch(mode,()=>{error.value='';notice.value='';void refresh()})
const waveform = ref<HTMLElement>()
let wave: WaveSurfer | undefined
const preview = shallowRef<Preview>()
let generationController: AbortController | undefined
watch(selection, list => { if (list.length && !list.some(item => item.id === model.value)) model.value = list[0]?.id ?? '' }, { immediate: true })
watch([referenceWave, referenceAudio], ([container, url], _, onCleanup) => {
  if (!container || !url) return
  const referencePlot = WaveSurfer.create({
    container, url, height: 36, waveColor:'#9192ae', interact:false, barWidth:2,
  })
  referencePlot.on('ready', duration => { trimStart.value = 0; trimEnd.value = Number(duration.toFixed(3)) })
  referencePlot.on('error', report)
  onCleanup(() => referencePlot.destroy())
}, {flush:'post'})
const authorization = 'Bearer ' + document.querySelector<HTMLMetaElement>('meta[name=studio-token]')?.content
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api/v1' + path, { ...options, headers: { ...options.headers, Authorization: authorization } })
  if (!response.ok) {
    const body = await response.json()
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item: {msg: string}) => item.msg).join(' · ')
      : body.detail
    throw new Error(typeof detail === 'string' ? detail : body.error ?? 'HTTP ' + response.status)
  }
  return response
}
function report(e: unknown) { error.value = e instanceof Error ? e.message : String(e) }
async function refresh() {
  try {
    health.value = await (await api('/health')).json()
    models.value = await (await api('/models')).json()
    items.value = await (await api('/history')).json()
    voices.value = await (await api('/voices')).json()
  } catch (e) { report(e) }
}
onMounted(() => {
  void refresh()
  void preferences.connect(
    async () => (await api('/settings')).json(),
    async options => {
      try {
        await api('/settings', {method:'PUT', headers:{'Content-Type':'application/json'},
          body:JSON.stringify(options)})
      } catch (e) { report(e) }
    },
  ).catch(report)
})
async function upload(file?: File) {
  if (!file) return
  notice.value = t('正在处理参考音频…','Preparing reference audio…')
  error.value = ''
  try {
    if (!file.name.toLowerCase().endsWith('.wav')) file = await recordedWav(file)
    const form = new FormData()
    form.append('file', file)
    reference.value = (await (await api('/references', {method:'POST', body:form})).json()).id
    if (referenceAudio.value) URL.revokeObjectURL(referenceAudio.value)
    referenceAudio.value = URL.createObjectURL(file)
    notice.value = t('参考音频已载入，可试听或裁剪。','Reference clip loaded. Preview or trim it below.')
    return true
  } catch (e) { notice.value=''; report(e) }
}
async function cloneFromDesign() {
  if (!result.value || !output.value) return
  try {
    const clip = await (await fetch(output.value)).blob()
    if (await upload(new File([clip], 'design.wav', {type:'audio/wav'}))) {
      transcript.value = result.value.request.text
      xvec.value = false
      await router.push({name:'clone'})
    }
  } catch (e) { report(e) }
}
function clearReference() {
  URL.revokeObjectURL(referenceAudio.value)
  referenceAudio.value = ''
  reference.value = ''
  transcript.value = ''
}
async function trimReference() {
  try {
    const blob = await (await fetch(referenceAudio.value)).blob()
    await upload(await recordedWav(blob, trimStart.value, trimEnd.value))
  } catch (e) { report(e) }
}
async function saveVoice() {
  try {
    await api('/voices', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      name:voiceName.value, notes:voiceNotes.value, reference:reference.value,
      transcript:transcript.value, xvec:xvec.value,
    })})
    notice.value = t('音色已保存到「我的音色」。','Voice saved to your library.')
    voiceName.value = ''
    voiceNotes.value = ''
    await refresh()
  } catch (e) { report(e) }
}
async function useVoice(id: string) {
  const voice = voices.value.find(item => item.id === id)
  if (!voice) return
  try {
    const audio = await (await api('/references/' + voice.reference + '/audio')).blob()
    if (referenceAudio.value) URL.revokeObjectURL(referenceAudio.value)
    referenceAudio.value = URL.createObjectURL(audio)
    reference.value = voice.reference
    transcript.value = voice.transcript
    xvec.value = voice.xvec
  } catch (e) { report(e) }
}
async function removeVoice(id: string) {
  if (!window.confirm(t('从音色库移除此音色？','Remove this voice from the library?'))) return
  try { await api('/voices/' + id, {method:'DELETE'}); await refresh() }
  catch (e) { report(e) }
}
async function updateVoice(voice: Voice) {
  try {
    await api('/voices/' + voice.id, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(voice)})
    editVoice.value = undefined
    await refresh()
  } catch (e) { report(e) }
}
async function importVoice(file?: File) {
  if (!file) return
  const body = new FormData()
  body.append('file', file)
  try { await api('/voices/import', {method:'POST', body}); await refresh() }
  catch (e) { report(e) }
}
function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
async function exportVoice(voice: Voice) {
  try { saveBlob(await (await api('/voices/' + voice.id + '/package')).blob(), voice.name + '.voice.json') }
  catch (e) { report(e) }
}
async function exportDiagnostics() {
  try {
    saveBlob(await (await api('/system/diagnostics')).blob(), 'studio-diagnostics.json')
  } catch (e) { report(e) }
}
async function deleteClip(id:string) {
  if (!confirm(t('永久删除这条历史记录和音频？','Permanently delete this clip and history entry?'))) return
  try {
    await api('/history/'+id,{method:'DELETE'})
    if (result.value?.id === id) {
      wave?.destroy()
      wave = undefined
      URL.revokeObjectURL(output.value)
      output.value = ''
      result.value = undefined
    }
    await refresh()
  } catch(e) { report(e) }
}
async function openAudio(record: Record) {
  try {
    const response = await api('/history/' + record.id + '/audio')
    if (output.value) URL.revokeObjectURL(output.value)
    output.value = URL.createObjectURL(await response.blob())
    result.value = record
    await nextTick()
    wave?.destroy()
    if (waveform.value) wave = WaveSurfer.create({
      container: waveform.value, url: output.value, height: 44, waveColor: '#9192ae',
      progressColor: '#7052df', interact: false, barWidth: 2, barGap: 2,
    })
  } catch (e) { report(e) }
}
async function generate(request?: { [key: string]: unknown }, live = true) {
  if (pending.value) return
  const id = crypto.randomUUID()
  const controller = new AbortController()
  generationController = controller
  pending.value = id
  error.value = ''
  try {
    await preview.value?.close()
    const playback = live ? new Preview() : undefined
    preview.value = playback
    await playback?.start()
    const response = await api('/tts/stream/' + id, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      signal:controller.signal,
      body: JSON.stringify(request ?? {text:text.value, model:model.value, quant:quant.value, speaker:speaker.value,
        language:language.value,
        instruct:mode.value === 'design' || model.value === '1.7b-customvoice' ? instruct.value : '',
        transcript:transcript.value, xvec:xvec.value,
        temperature:temperature.value, top_k:topK.value, top_p:topP.value, max_new_tokens:maxTokens.value,
        reference:mode.value === 'clone' ? reference.value || null : null}),
    })
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let generated: Record | undefined
    try {
      while (true) {
        const value = await reader.read()
        if (value.done) break
        buffer += decoder.decode(value.value, {stream:true})
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const event = JSON.parse(line)
          if (event.error) throw new Error(event.error)
          if (event.pcm) playback?.append(event.rate, event.pcm)
          if (event.result) generated = event.result
        }
      }
    } finally { await reader.cancel() }
    if (!generated) throw new Error(t('生成已中断','Generation interrupted'))
    if (live) await openAudio(generated)
    await refresh()
    return generated.id
  } catch (e) {
    if (!controller.signal.aborted) report(e)
    await preview.value?.close()
    preview.value = undefined
  } finally {
    pending.value = ''
    generationController = undefined
  }
}
async function cancel() {
  const id = pending.value
  if (!id) return
  generationController?.abort()
  try {
    await fetch('/api/v1/tasks/' + id + '/cancel', {method:'POST', headers:{Authorization:authorization}})
  } catch (e) { report(e) }
}
async function exportClips(format: 'zip' | 'wav', clips: {id:string; pause_ms:number}[]) {
  try {
    const response = await api('/exports', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({format, clips})})
    saveBlob(await response.blob(), format === 'zip' ? 'batch.zip' : 'dialogue.wav')
  } catch (e) { report(e) }
}
async function loadWorkspace(kind: 'dialogue' | 'batch') {
  try { return await (await api('/workspaces/' + kind)).json() || undefined }
  catch (e) { report(e) }
}
async function saveWorkspace(kind: 'dialogue' | 'batch', state: unknown) {
  try {
    await api('/workspaces/' + kind, {method:'PUT', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(state)})
  } catch (e) { report(e) }
}
</script>

<template>
  <div class="shell">
    <aside>
      <div class="brand"><AudioLines :size="23" /> <div>Faster Qwen3<small>TTS Studio</small></div></div>
      <nav>
        <template v-for="([id, zh, en, icon], index) of nav" :key="id">
          <small v-if="index === 0 || index === 3 || index === 5" class="nav-label">{{index === 0 ? t('声音创作','Create') : index === 3 ? t('项目','Projects') : t('资料与设置','Library & settings')}}</small>
          <RouterLink :to="{name:id}"><component :is="icon" :size="18" />{{t(zh,en)}}</RouterLink></template>
      </nav>
    </aside>
    <main>
      <header><h1>{{ title }}</h1><div class="actions">
        <span v-if="pending" role="status">{{t('正在生成','Generating')}}</span>
        <span v-if="model && selection.length">{{model}} · {{quant}}</span>
        <span class="status">{{ health?.mode === 'mock' ? t('开发模拟 · 测试音','Development mock · test tone') : health?.metalVerified ? 'Metal · MTL0' : health ? t('Metal 运行时 · 待验证','Metal runtime · awaiting verification') : t('服务未连接','Service disconnected') }}</span>
      </div></header>
      <div v-if="error" class="error actions" role="alert">{{error}}<button @click="error=''; refresh()">{{t('刷新','Refresh')}}</button></div>
      <p v-if="notice" class="panel" role="status">{{notice}}</p>
      <section v-if="['custom','clone','design'].includes(mode)" class="work">
        <div class="panel editor stack">
          <div v-if="mode === 'clone'" class="reference-box stack" @dragover.prevent @drop.prevent="upload($event.dataTransfer?.files[0])">
            <label v-if="voices.length">{{t('已保存音色','Saved voice')}}<select @change="useVoice(($event.target as HTMLSelectElement).value)">
              <option value="">{{t('选择音色','Choose a voice')}}</option>
              <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{voice.name}}</option>
            </select></label>
            <label>{{t('参考音频','Reference audio')}}<span class="drop-input">{{t('选择或拖入获授权的音频文件','Choose or drop an authorized audio file')}}<input type="file" accept=".wav,.mp3,.flac,.m4a,audio/*" @change="upload(($event.target as HTMLInputElement).files?.[0])"></span></label>
            <MicrophoneCapture :t="t" :upload="upload" />
            <template v-if="referenceAudio">
              <div ref="referenceWave"></div>
              <audio :src="referenceAudio" controls></audio>
              <button @click="clearReference">{{t('移除参考音频','Remove reference')}}</button>
              <div class="trim">
                <label>{{t('起点（秒）','Start (s)')}}<input v-model.number="trimStart" type="number" min="0" step="0.01"></label>
                <label>{{t('终点（秒）','End (s)')}}<input v-model.number="trimEnd" type="number" min="0" step="0.01"></label>
                <button :disabled="!trimEnd || trimEnd <= trimStart" @click="trimReference">{{t('裁剪','Trim')}}</button>
              </div>
            </template>
            <label class="check"><input v-model="xvec" type="checkbox">{{t('仅提取音色，无需转录（X-vector）','Speaker embedding only, no transcript (X-vector)')}}</label>
            <label v-if="!xvec">{{t('参考音频转录','Reference transcript')}}<textarea v-model="transcript" rows="3"></textarea></label>
            <template v-if="reference">
              <label>{{t('音色名称','Voice name')}}<input v-model="voiceName" maxlength="100"></label>
              <label>{{t('备注','Notes')}}<input v-model="voiceNotes" maxlength="2000"></label>
              <button :disabled="!voiceName.trim() || (!xvec && !transcript.trim())" @click="saveVoice">{{t('保存音色','Save voice')}}</button>
            </template>
          </div>
          <label v-if="mode === 'design'">{{t('声音描述','Voice description')}}<textarea v-model="instruct" rows="4"></textarea></label>
          <label v-if="mode === 'custom' && model === '1.7b-customvoice'">{{t('语气描述','Delivery instruction')}}<textarea v-model="instruct" rows="3"></textarea></label>
          <label>{{t('输入文本','Script')}} <textarea v-model="text" maxlength="12000" :placeholder="t('输入要朗读的文字…','Write something to speak…')" rows="7"></textarea></label>
          <small>{{text.length}} / 12000</small>
        </div>
        <div class="panel options">
          <h2>{{t('生成设置','Generation settings')}}</h2>
          <label>{{t('模型','Model')}}<select v-model="model"><option v-for="item of selection" :key="item.id" :value="item.id">{{item.id}}</option></select></label>
          <label>{{t('量化','Quantization')}}<select v-model="quant"><option>Q8_0</option><option>BF16</option><option>Q4_K_M</option></select></label>
          <label>{{t('语言','Language')}}<select v-model="language"><option v-for="lang of ['Auto','Chinese','English','Japanese','Korean','German','French','Russian','Portuguese','Spanish','Italian']" :key="lang">{{lang}}</option></select></label>
          <label v-if="mode === 'custom'">{{t('音色','Speaker')}}<select v-model="speaker"><option v-for="name of ['Vivian','Serena','Ryan','Aiden','Dylan','Eric','Ono_Anna','Sohee','Uncle_Fu']" :key="name">{{name}}</option></select></label>
          <details>
            <summary>{{t('高级推理参数','Advanced inference')}}</summary>
            <div class="trim">
              <label>Temperature<input v-model.number="temperature" type="number" min="0.01" max="2" step="0.05"></label>
              <label>Top K<input v-model.number="topK" type="number" min="1" max="1000" step="1"></label>
              <label>Top P<input v-model.number="topP" type="number" min="0.01" max="1" step="0.05"></label>
              <label>{{t('最大令牌数','Max tokens')}}<input v-model.number="maxTokens" type="number" min="16" max="2048" step="1"></label>
            </div>
          </details>
          <div class="generation-controls stack">
          <p v-if="generationHint" class="hint">{{generationHint}}</p>
          <div class="controls">
          <button class="primary" :disabled="!!pending || !!generationHint" @click="generate()">{{t('生成语音','Generate')}}</button>
          <button v-if="pending" @click="cancel">{{t('停止生成','Cancel generation')}}</button></div>
          <RouterLink v-if="health && !weightsReady" :to="{name:'models',query:{from:mode,model,quant}}" class="model-link">
            {{t('先下载所选模型权重','Download the selected model weights first')}}
          </RouterLink>
          </div>
        </div>
      </section>
      <section v-else-if="mode === 'voices'" class="stack">
        <div class="panel actions">
          <label>{{t('搜索音色','Search voices')}}<input v-model="voiceSearch" type="search"></label>
          <label>{{t('显示方式','Layout')}}<select v-model="voiceLayout">
            <option value="cards">{{t('卡片','Cards')}}</option><option value="list">{{t('列表','List')}}</option>
          </select></label>
          <label>{{t('导入音色包','Import voice package')}}<input type="file" accept=".json" @change="importVoice(($event.target as HTMLInputElement).files?.[0])"></label>
        </div>
        <div v-if="editVoice" class="panel stack">
          <label>{{t('名称','Name')}}<input v-model="editVoice.name" maxlength="100"></label>
          <label>{{t('备注','Notes')}}<textarea v-model="editVoice.notes" maxlength="2000" rows="3"></textarea></label>
          <label>{{t('标签（逗号分隔）','Tags (comma-separated)')}}<input v-model="editTags" maxlength="240"></label>
          <div class="actions">
            <button @click="editVoice = undefined">{{t('取消','Cancel')}}</button>
            <button @click="updateVoice({...editVoice, tags:editTags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean).slice(0,12)})">{{t('保存','Save')}}</button>
          </div>
        </div>
        <p class="empty" v-if="!voices.length">{{t('在声音克隆页面保存参考音色。','Save a reference voice from the clone workspace.')}}</p>
        <div :class="voiceLayout === 'cards' ? 'voice-cards' : 'stack'">
          <article v-for="voice in visibleVoices" :key="voice.id" class="panel stack">
            <div class="voice-title"><span class="avatar" aria-hidden="true">{{Array.from(voice.name)[0]}}</span>
              <div><strong>{{voice.name}}</strong><p>{{voice.notes}}</p><small>{{voice.tags?.join(' · ')}}</small></div>
            </div>
            <div class="actions">
              <RouterLink :to="{name:'clone'}" @click="useVoice(voice.id)">{{t('用于克隆','Use for cloning')}}</RouterLink>
              <button :aria-pressed="!!voice.favorite" @click="updateVoice({...voice, favorite:!voice.favorite})">{{voice.favorite ? t('取消收藏','Unfavorite') : t('收藏','Favorite')}}</button>
              <button @click="editVoice = {...voice}; editTags = (voice.tags ?? []).join(', ')">{{t('编辑','Edit')}}</button>
              <button @click="exportVoice(voice)">{{t('导出','Export')}}</button>
              <button @click="removeVoice(voice.id)">{{t('移除音色','Remove voice')}}</button>
            </div>
          </article>
          </div>
      </section>
      <ModelManager v-else-if="mode === 'models'" :models="models" :api="api" :refresh="refresh" :t="t" />
      <section v-else-if="mode === 'history'" class="stack">
        <p class="empty" v-if="!items.length">{{t('生成的语音将在这里显示。','Generated clips will appear here.')}}</p>
        <article v-for="item of items" :key="item.id" class="panel model"><span>{{item.request.text.slice(0,150)}} <small v-if="item.mock">Mock</small></span><div class="controls"><button @click="openAudio(item)">{{t('载入播放','Load audio')}}</button><button @click="deleteClip(item.id)">{{t('删除','Delete')}}</button></div></article>
      </section>
      <section v-else-if="mode === 'settings'" class="panel options">
        <label>{{t('主题','Theme')}}<select v-model="theme"><option value="system">{{t('系统','System')}}</option><option value="light">{{t('浅色','Light')}}</option><option value="dark">{{t('深色','Dark')}}</option></select></label>
        <label>{{t('界面语言','Interface language')}}<select v-model="locale"><option value="zh">简体中文</option><option value="en">English</option></select></label>
        <h2>{{t('本地服务','Local service')}}</h2>
        <p v-if="health">{{health.platform}} · {{health.arch}}</p>
        <StorageManager @changed="refresh" :api="api" :t="t" :busy="!!pending" />
        <button @click="exportDiagnostics">{{t('导出系统诊断','Export system diagnostics')}}</button>
      </section>
      <QueueWorkspace v-show="mode === 'dialogue'" :dialogue="true" :chinese="locale === 'zh'" :busy="!!pending"
        :models="models" :voices="voices" :generate="request => generate(request, false)" :export-clips="exportClips"
        :cancel="cancel" :load-workspace="() => loadWorkspace('dialogue')" :save-workspace="state => saveWorkspace('dialogue', state)" />
      <QueueWorkspace v-show="mode === 'batch'" :dialogue="false" :chinese="locale === 'zh'" :busy="!!pending"
        :models="models" :voices="voices" :generate="request => generate(request, false)" :export-clips="exportClips"
        :cancel="cancel" :load-workspace="() => loadWorkspace('batch')" :save-workspace="state => saveWorkspace('batch', state)" />
      <footer v-if="output || pending || preview" class="panel player">
        <div v-show="output" ref="waveform"></div>
        <div class="actions">
          <button v-if="preview" @click="preview.toggle()">{{t('暂停或继续流式试听','Pause or resume live preview')}}</button>
          <audio v-if="output" controls :src="output"></audio>
          <a v-if="output" :href="output" :download="result?.id + '.wav'">{{t('导出 WAV','Export WAV')}}</a>
          <button v-if="result?.request.model.endsWith('-voicedesign')" @click="cloneFromDesign">{{t('用设计音色克隆','Clone this design')}}</button>
          <span v-if="result">{{result.duration.toFixed(2)}} s · TTFA {{result.ttfa.toFixed(2)}} s · RTF {{result.rtf.toFixed(2)}}</span>
          <span v-if="!output && !pending">{{t('暂无试听音频','No preview audio')}}</span>
        </div>
      </footer>
    </main>
  </div>
</template>
