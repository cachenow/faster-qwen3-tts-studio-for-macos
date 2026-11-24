import vue from 'eslint-plugin-vue'
import typescript from '@typescript-eslint/parser'

export default [
  { ignores: ['dist/**', 'test-results/**'] },
  ...vue.configs['flat/essential'],
  {
    files: ['**/*.ts'],
    languageOptions: { parser: typescript },
    rules: { 'no-debugger': 'error', 'no-unreachable': 'error', 'no-unsafe-finally': 'error' },
  },
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: typescript } },
    rules: { 'vue/multi-word-component-names': 'off', 'no-debugger': 'error' },
  },
]
