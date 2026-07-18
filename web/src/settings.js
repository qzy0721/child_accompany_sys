import { createApp } from 'vue'
import SettingsApp from './SettingsApp.vue'
import './styles.css'

document.body.classList.add('settings-body')
createApp(SettingsApp).mount('#app')
