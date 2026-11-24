import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import Studio from './Studio.vue'
import './studio.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: ['custom', 'clone', 'design', 'dialogue', 'batch', 'voices', 'history', 'models', 'settings'].map((mode) => ({
    path: mode === 'custom' ? '/' : '/' + mode,
    name: mode,
    component: Studio,
  })),
})
createApp(Studio).use(createPinia()).use(router).mount('#app')
