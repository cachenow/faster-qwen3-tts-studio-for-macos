<script setup lang="ts">
import {onMounted,ref,computed} from 'vue'
const props=defineProps<{api:(path:string,options?:RequestInit)=>Promise<Response>;t:(zh:string,en:string)=>string;busy:boolean}>()
const emit=defineEmits<{changed:[]}>()
const groups=[['models','已安装模型','Installed weights'],['partials','未完成下载','Partial downloads'],['unused','未保存为音色的参考录音','Reference clips outside the voice library'],['outputs','生成历史与音频','History and audio'],['voices','音色库与全部参考录音','Voices and reference clips'],['cache','推理及工具缓存','Inference and tool caches'],['logs','运行日志','Logs'],['workspaces','批量与对话草稿','Batch and dialogue drafts'],['settings','语言与外观设置','Language and appearance']] as const
const picked=ref<string[]>([])
const sizes=ref<Record<string,number>>({})
const message=ref('')
const clearing=ref(false)
const amount=(n:number)=>n<1048576 ? Math.ceil(n/1024)+' KiB' : (n/1048576).toFixed(1)+' MiB'
const names=computed(()=>groups.filter(([key])=>picked.value.includes(key)).map(([,zh,en])=>props.t(zh,en)))
async function refresh(){
  try { sizes.value=await (await props.api('/storage')).json() } catch(e){message.value=String(e)}
}
onMounted(refresh)
async function clean(){
  const reload = picked.value.some(key=>['settings','voices','outputs','workspaces','unused'].includes(key))
  const reloadHint = reload ? props.t('清理后将重新载入工作区。','The workspace will reload after cleanup.') : ''
  if (!confirm(props.t('永久清除以下数据？','Permanently delete the following data?')+'\n'+names.value.join('\n')+'\n'+reloadHint)) return
  clearing.value=true
  try{
    await props.api('/storage/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(picked.value)})
    if(picked.value.includes('settings')){
      localStorage.removeItem('studio-language')
      localStorage.removeItem('studio-theme')
    }
    if (reload) {
      sessionStorage.setItem('studio-cleaned','1')
      window.location.reload()
    } else {
      picked.value=[]
      message.value=props.t('所选数据已清理。','Selected data cleared.')
      clearing.value=false
      await refresh()
      emit('changed')
    }
  }catch(e){message.value=String(e);clearing.value=false}
}
onMounted(()=>{if(sessionStorage.getItem('studio-cleaned')){message.value=props.t('所选数据已清理。','Selected data cleared.');sessionStorage.removeItem('studio-cleaned')}})
</script>
<template>
<section class="stack storage">
  <div class="actions"><h2>{{t('数据管理','Storage management')}}</h2><button @click="refresh">{{t('刷新占用','Refresh usage')}}</button></div>
  <label v-for="[key,zh,en] in groups" :key="key" class="storage-row"><input v-model="picked" type="checkbox" :value="key"><span>{{t(zh,en)}}</span><small v-if="key in sizes">{{amount(sizes[key])}}</small></label>
  <small v-if="sizes.database !== undefined">{{t('索引与设置数据库','Index and settings database')}} · {{amount(sizes.database)}}</small>
  <div class="controls"><button @click="picked=picked.length===groups.length?[]:groups.map(g=>g[0])">{{picked.length===groups.length?t('取消全选','Deselect all'):t('全选','Select all')}}</button><button class="danger" :disabled="busy || clearing || !picked.length" @click="clean">{{t('清理所选数据','Clear selected data')}} ({{picked.length}})</button></div>
  <p v-if="message" role="status">{{message}}</p>
  <details><summary>{{t('完整卸载','Complete uninstall')}}</summary><p>{{t('退出应用，打开安装 DMG，运行 Uninstall Studio.command。工具会列出将删除的应用和用户目录，确认后清理。','Quit Studio, open the DMG and run Uninstall Studio.command. Review the listed application and data locations before confirming.')}}</p></details>
</section>
</template>
