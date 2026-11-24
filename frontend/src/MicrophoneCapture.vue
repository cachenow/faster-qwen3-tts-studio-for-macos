<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { recordedWav } from './audio'

const props = defineProps<{t:(zh:string,en:string)=>string; upload:(file:File)=>Promise<boolean|undefined>}>()
const phase = ref<'closed'|'choosing'|'recording'|'review'>('closed')
const devices = ref<MediaDeviceInfo[]>([])
const selected = ref('')
const busy = ref(false)
const message = ref('')
const seconds = ref(0)
const preview = ref('')
let stream: MediaStream | undefined
let recorder: MediaRecorder | undefined
let timer: number
let draft: Blob | undefined
let session = 0

function stopTracks() {
  clearInterval(timer)
  stream?.getTracks().forEach(track => track.stop())
  stream = undefined
}
function close() {
  ++session
  if (recorder?.state === 'recording') recorder.stop()
  recorder = undefined
  stopTracks()
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  draft = undefined
  phase.value = 'closed'
  busy.value = false
  message.value = ''
}
onBeforeUnmount(close)
function failure(e: unknown) {
  message.value = e instanceof DOMException && e.name === 'NotAllowedError'
    ? props.t('请在系统隐私设置中允许麦克风访问，然后重试。','Allow microphone access in Privacy settings, then retry.')
    : String(e)
}
async function choose() {
  close()
  const id = session
  phase.value = 'choosing'
  devices.value = []
  busy.value = true
  let probe: MediaStream | undefined
  try {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined')
      throw new Error(props.t('当前窗口无法使用麦克风，可以导入参考音频。','Microphone unavailable. Import a reference file instead.'))
    probe = await navigator.mediaDevices.getUserMedia({audio:true})
    const list = await navigator.mediaDevices.enumerateDevices()
    if (session !== id) return
    devices.value = list.filter(d => d.kind === 'audioinput')
    selected.value = devices.value[0]?.deviceId || ''
    if (!devices.value.length) message.value = props.t('未找到输入设备，请连接麦克风后刷新。','Connect a microphone and refresh devices.')
  } catch (e) { if (session === id) failure(e) }
  finally { probe?.getTracks().forEach(track => track.stop()); if (session === id) busy.value = false }
}
async function start() {
  const id = session
  busy.value = true
  message.value = ''
  try {
    const input = await navigator.mediaDevices.getUserMedia({audio:selected.value ? {deviceId:{exact:selected.value}} : true})
    if (id !== session) { input.getTracks().forEach(track => track.stop()); return }
    stream = input
    const current = new MediaRecorder(input)
    recorder = current
    const chunks: Blob[] = []
    current.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    current.onerror = () => { if (session === id) { close(); failure(props.t('录音中断，请重新选择设备。','Recording interrupted. Select the device again.')) } }
    current.onstop = () => {
      if (id !== session) return
      stopTracks()
      draft = new Blob(chunks, {type:current.mimeType})
      if (!draft.size) { close(); failure(props.t('未收到音频，请重试。','No audio captured. Please retry.')); return }
      preview.value = URL.createObjectURL(draft)
      phase.value = 'review'
    }
    current.start()
    phase.value = 'recording'
    seconds.value = 0
    const began = Date.now()
    timer = window.setInterval(() => {
      seconds.value = Math.floor((Date.now()-began)/1000)
      if (seconds.value >= 90 && current.state === 'recording') current.stop()
    },250)
  } catch (e) { if (id === session) { stopTracks(); failure(e) } }
  finally { if (id === session) busy.value = false }
}
async function accept() {
  if (!draft) return
  busy.value = true
  try { if (await props.upload(await recordedWav(draft))) close() }
  catch (e) { failure(e) }
  finally { busy.value = false }
}
</script>
<template>
  <section class="capture stack">
    <button v-if="phase === 'closed'" @click="choose">{{t('选择麦克风','Choose microphone')}}</button>
    <template v-if="phase === 'choosing'">
      <label>{{t('录音设备','Recording device')}}<select v-model="selected" :disabled="busy">
        <option v-for="(device,i) in devices" :key="device.deviceId || i" :value="device.deviceId">{{device.label || t('麦克风','Microphone')+' '+(i+1)}}</option>
      </select></label>
      <small v-if="busy" role="status">{{t('正在获取输入设备…','Finding input devices…')}}</small>
      <div class="controls"><button class="primary" :disabled="busy || !devices.length" @click="start">{{t('开始录音','Start recording')}}</button>
        <button :disabled="busy" @click="choose">{{t('刷新设备','Refresh devices')}}</button><button @click="close">{{t('取消','Cancel')}}</button></div>
    </template>
    <template v-if="phase === 'recording'">
      <strong role="status">{{t('正在录音','Recording')}} · {{seconds}} / 90 s</strong>
      <div class="controls"><button class="primary" @click="recorder?.stop()">{{t('停止并试听','Stop and review')}}</button><button @click="close">{{t('放弃录音','Discard recording')}}</button></div>
    </template>
    <template v-if="phase === 'review'">
      <strong>{{t('试听录音','Review recording')}}</strong><audio :src="preview" controls/>
      <div class="controls"><button class="primary" :disabled="busy" @click="accept">{{t('使用此录音','Use this recording')}}</button><button :disabled="busy" @click="choose">{{t('重录','Record again')}}</button><button :disabled="busy" @click="close">{{t('丢弃','Discard')}}</button></div>
    </template>
    <p v-if="message" role="alert">{{message}}</p>
  </section>
</template>
