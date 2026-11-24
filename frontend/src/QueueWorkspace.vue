<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

type Voice = {id:string; name:string; reference:string; transcript:string; xvec:boolean}
type Model = {id:string; mode:string}
type Row = {id:number; text:string; role:number; pause:number; result?:string; status:string}
type Snapshot = {
  rows: Row[]; roles: {name:string; voice:string}[]; custom:string;
  base:string; quant:string; language:string;
}
const props = defineProps<{
  dialogue: boolean; chinese: boolean; busy: boolean; models: Model[]; voices: Voice[];
  generate: (request: Record<string, unknown>) => Promise<string | undefined>;
  exportClips: (format: 'wav' | 'zip', clips: {id:string; pause_ms:number}[]) => Promise<void>;
  cancel: () => Promise<void>;
  loadWorkspace: () => Promise<Snapshot | undefined>;
  saveWorkspace: (state: Snapshot) => Promise<void>;
}>()
const t = (zh:string, en:string) => props.chinese ? zh : en
let next = 0
const newRow = (text = ''): Row => ({id:++next, text, role:0, pause:250, status:''})
const rows = ref<Row[]>([newRow()])
const roles = ref([{name:'', voice:'Vivian'}])
const importText = ref('')
const custom = ref('0.6b-customvoice')
const base = ref('0.6b-base')
const quant = ref('Q8_0')
const language = ref('Auto')
const running = ref(false)
const stopping = ref(false)
const complete = computed(() => !!rows.value.length && rows.value.every(row => row.result))
const customModels = computed(() => props.models.filter(model => model.mode === 'custom'))
const baseModels = computed(() => props.models.filter(model => model.mode === 'clone'))
const speakers = ['Vivian','Serena','Ryan','Aiden','Dylan','Eric','Ono_Anna','Sohee','Uncle_Fu']
let ready = false
let saveTimer: number | undefined
let write = Promise.resolve()

onMounted(async () => {
  const state = await props.loadWorkspace()
  if (state) {
    rows.value = state.rows.map(row => ({...row, status:row.result ? 'ready' : ''}))
    roles.value = state.roles
    custom.value = state.custom
    base.value = state.base
    quant.value = state.quant
    language.value = state.language
    next = Math.max(0, ...rows.value.map(row => row.id))
  }
  ready = true
})

watch([rows, roles, custom, base, quant, language], () => {
  if (!ready) return
  clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    const state = {
      rows:rows.value.map(row => ({...row, pause:Math.min(10000, Math.max(0, Math.round(row.pause || 0)))})),
      roles:roles.value.map(role => ({...role})), custom:custom.value, base:base.value,
      quant:quant.value, language:language.value,
    }
    write = write.then(() => props.saveWorkspace(state))
  }, 180)
}, {deep:true, flush:'sync'})

function addTexts() {
  const lines = importText.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
  if (!lines.length) return
  const existing = rows.value.filter(row => row.text.trim())
  rows.value = existing.concat(lines.slice(0, 50 - existing.length).map(line => newRow(line.slice(0,12000))))
  importText.value = ''
}
function move(index: number, offset: number) {
  const destination = index + offset
  if (destination < 0 || destination >= rows.value.length) return
  const [row] = rows.value.splice(index, 1)
  rows.value.splice(destination, 0, row)
}
function invalidate() {
  for (const row of rows.value) { row.result = undefined; row.status = '' }
}
async function run(list: Row[]) {
  if (running.value || props.busy) return
  running.value = true
  stopping.value = false
  try {
    for (const row of list) {
      if (stopping.value) break
      if (!row.text.trim()) continue
      row.result = undefined
      row.status = 'running'
      const voiceId = roles.value[row.role]?.voice || 'Vivian'
      const voice = props.voices.find(item => item.id === voiceId)
      row.result = await props.generate({
        text:row.text, language:language.value, quant:quant.value,
        model: voice ? base.value : custom.value, speaker: voice ? 'Vivian' : voiceId,
        reference:voice?.reference, transcript:voice?.transcript, xvec:voice?.xvec,
      })
      row.status = row.result ? 'ready' : 'failed'
    }
  } finally { running.value = false }
}
async function stop() {
  stopping.value = true
  if (props.busy) await props.cancel()
}
async function exportAll() {
  if (!complete.value) return
  await props.exportClips(props.dialogue ? 'wav' : 'zip', rows.value.map((row, index) => ({
    id:row.result!, pause_ms:props.dialogue && index < rows.value.length - 1 ? row.pause : 0,
  })))
}
</script>

<template>
  <div class="stack">
    <section class="panel stack">
      <div class="actions">
        <label>{{t('预设音色模型','Preset model')}}<select v-model="custom" :disabled="running" @change="invalidate"><option v-for="item in customModels" :key="item.id">{{item.id}}</option></select></label>
        <label>{{t('克隆模型','Clone model')}}<select v-model="base" :disabled="running" @change="invalidate"><option v-for="item in baseModels" :key="item.id">{{item.id}}</option></select></label>
        <label>{{t('量化','Quantization')}}<select v-model="quant" :disabled="running" @change="invalidate"><option>Q8_0</option><option>BF16</option><option>Q4_K_M</option></select></label>
        <label>{{t('语言','Language')}}<select v-model="language" :disabled="running" @change="invalidate"><option v-for="item in ['Auto','Chinese','English','Japanese','Korean','German','French','Russian','Portuguese','Spanish','Italian']" :key="item">{{item}}</option></select></label>
      </div>
      <div v-for="(role, index) in roles" :key="index" class="queue-fields">
        <label v-if="dialogue">{{t('角色','Role')}} {{index + 1}}<input v-model="role.name" :disabled="running" maxlength="80"></label>
        <label>{{t('音色','Voice')}}<select v-model="role.voice" :disabled="running" @change="invalidate">
          <option v-for="speaker in speakers" :key="speaker">{{speaker}}</option>
          <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{voice.name}}</option>
        </select></label>
      </div>
      <button v-if="dialogue" :disabled="running || roles.length >= 12" @click="roles.push({name:'',voice:'Vivian'})">{{t('添加角色','Add role')}}</button>
      <template v-else>
        <label>{{t('粘贴多条文本，每行一条','Paste one clip per line')}}<textarea v-model="importText" :disabled="running" maxlength="120000" rows="4"></textarea></label>
        <button :disabled="running || !importText.trim()" @click="addTexts">{{t('导入文本','Import text')}}</button>
      </template>
    </section>
    <article v-for="(row,index) in rows" :key="row.id" class="panel stack">
      <div class="actions">
        <label v-if="dialogue">{{t('角色','Role')}}<select v-model.number="row.role" :disabled="running" @change="row.result = undefined; row.status = ''">
          <option v-for="(role, i) in roles" :key="i" :value="i">{{role.name || t('角色','Role') + ' ' + (i + 1)}}</option>
        </select></label>
        <label v-if="dialogue">{{t('段后停顿（毫秒）','Pause after (ms)')}}<input v-model.number="row.pause" :disabled="running" type="number" min="0" max="10000" step="50"></label>
        <span role="status">{{row.status === 'ready' ? t('已生成','Ready') : row.status === 'running' ? t('生成中','Generating') : row.status === 'failed' ? t('已中断或失败','Stopped or failed') : ''}}</span>
      </div>
      <label>{{t('文本','Text')}} {{index + 1}}<textarea v-model="row.text" :disabled="running" maxlength="12000" rows="3" @input="row.result = undefined; row.status = ''"></textarea></label>
      <div class="actions">
        <button :disabled="running || busy || !row.text.trim()" @click="run([row])">{{row.status === 'failed' ? t('重试','Retry') : t('生成本段','Generate clip')}}</button>
        <button :disabled="running || index === 0" @click="move(index,-1)">{{t('上移','Move up')}}</button>
        <button :disabled="running || index === rows.length - 1" @click="move(index,1)">{{t('下移','Move down')}}</button>
        <button :disabled="running" @click="rows.splice(index,1)">{{t('删除','Remove')}}</button>
      </div>
    </article>
    <div class="actions">
      <button :disabled="running || rows.length >= 50" @click="rows.push(newRow())">{{t('添加段落','Add clip')}}</button>
      <button class="primary" :disabled="running || busy || !rows.some(row => row.text.trim() && !row.result)" @click="run(rows.filter(row => !row.result))">{{t('生成未完成段落','Generate pending clips')}}</button>
      <button v-if="running" @click="stop">{{t('停止队列','Stop queue')}}</button>
      <button :disabled="running || !complete" @click="exportAll">{{dialogue ? t('导出合并 WAV','Export merged WAV') : t('导出 ZIP','Export ZIP')}}</button>
    </div>
  </div>
</template>
