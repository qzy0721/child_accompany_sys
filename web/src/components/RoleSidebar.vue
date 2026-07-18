<script setup>
import { ref } from 'vue'

const props = defineProps({
  roles: { type: Array, default: () => [] },
  selectedRole: { type: String, default: null },
  roleStatus: { type: String, default: '' },
})

const emit = defineEmits(['select-role', 'delete-role', 'upload-vrm', 'show-memories', 'generate-memory', 'clear-memories', 'clear-history'])

const vrmInput = ref(null)

function chooseVrm(event) {
  const file = event.target.files?.[0]
  if (file) emit('upload-vrm', file)
  event.target.value = ''
}

</script>

<template>
  <aside class="sidebar">
    <section class="panel">
      <div class="sidebar-heading">
        <h3>角色</h3>
        <a class="sidebar-create-role-button" href="./role-manager.html">新建角色</a>
      </div>
      <div class="role-list">
        <span v-if="roleStatus" class="muted-text">{{ roleStatus }}</span>
        <template v-else-if="roles.length">
          <button
            v-for="name in roles"
            :key="name"
            class="role-row"
            :class="{ active: name === selectedRole }"
            type="button"
            @click="emit('select-role', name)"
          >
            <span>{{ name }}</span>
            <span class="role-delete" title="删除角色" @click.stop="emit('delete-role', name)">&times;</span>
          </button>
        </template>
        <span v-else class="muted-text">暂无角色</span>
      </div>
    </section>

    <slot name="stage"></slot>

    <section class="panel">
      <h3>工具</h3>
      <div class="tool-row">
        <input ref="vrmInput" class="visually-hidden" type="file" accept=".vrm" @change="chooseVrm" />
        <button class="btn btn-secondary btn-small" type="button" @click="vrmInput?.click()">上传 VRM</button>
        <button class="btn btn-secondary btn-small" type="button" @click="emit('show-memories')">查看记忆</button>
        <button class="btn btn-secondary btn-small" type="button" @click="emit('generate-memory')">生成记忆</button>
        <button class="btn btn-secondary btn-small" type="button" @click="emit('clear-memories')">清空记忆</button>
        <button class="btn btn-secondary btn-small" type="button" @click="emit('clear-history')">清空历史</button>
        <a class="btn btn-secondary btn-small tool-link" href="./settings.html">服务设置</a>
      </div>
    </section>
  </aside>
</template>
