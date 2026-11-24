import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const usePreferences = defineStore('preferences', () => {
  const defaultLanguage = navigator.language.startsWith('zh') ? 'zh' : 'en'
  const locale = ref(localStorage.getItem('studio-language') || defaultLanguage)
  const theme = ref(localStorage.getItem('studio-theme') || 'system')

  watch(locale, value => {
    document.documentElement.lang = value === 'zh' ? 'zh-Hans' : 'en'
    localStorage.setItem('studio-language', value)
  }, {immediate: true})
  watch(theme, value => {
    document.documentElement.dataset.theme = value
    localStorage.setItem('studio-theme', value)
  }, {immediate: true})

  async function connect(load: () => Promise<{locale: string; theme: string} | null>,
                         save: (options: {locale: string; theme: string}) => Promise<void>) {
    const saved = await load()
    if (saved) {
      locale.value = saved.locale
      theme.value = saved.theme
    }
    let pending = Promise.resolve()
    watch([locale, theme], ([locale, theme]) => {
      pending = pending.then(() => save({locale, theme}))
    })
  }

  return {locale, theme, connect}
})
