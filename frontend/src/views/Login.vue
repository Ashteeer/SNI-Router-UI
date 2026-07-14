<script setup>
import { ref } from 'vue'
import { api } from '../api'
import PasswordInput from '../components/PasswordInput.vue'

const props = defineProps({ mode: String }) // 'setup' | 'login'
const emit = defineEmits(['authed'])

const username = ref('')
const password = ref('')
const whitelist = ref('')
const err = ref('')
const busy = ref(false)

async function submit() {
  err.value = ''
  busy.value = true
  try {
    if (props.mode === 'setup') {
      const ip_whitelist = whitelist.value.split(',').map((s) => s.trim()).filter(Boolean)
      await api.setup({ username: username.value, password: password.value, ip_whitelist })
    } else {
      await api.login({ username: username.value, password: password.value })
    }
    emit('authed')
  } catch (e) {
    err.value = e.message || 'Failed'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="grid h-full place-items-center p-6">
    <form class="card w-full max-w-sm" @submit.prevent="submit">
      <div class="mb-1 flex items-center gap-2">
        <div class="grid h-9 w-9 place-items-center rounded-lg bg-brand font-bold text-white">S</div>
        <h1 class="text-lg font-semibold text-slate-100">SNI-Router UI</h1>
      </div>
      <p class="mb-5 text-sm text-slate-400">
        {{ mode === 'setup' ? 'Create the admin account to get started.' : 'Sign in to continue.' }}
      </p>

      <label class="label">Username</label>
      <input v-model="username" class="input mb-3" autocomplete="username" required />

      <label class="label">Password</label>
      <PasswordInput v-model="password" class="mb-3"
             :autocomplete="mode === 'setup' ? 'new-password' : 'current-password'" required />

      <template v-if="mode === 'setup'">
        <label class="label">IP whitelist (optional, comma-separated)</label>
        <input v-model="whitelist" class="input mb-3" placeholder="127.0.0.1, 10.0.0.0/8" />
        <p class="mb-3 text-xs text-slate-500">Clients from these IPs skip the login screen.</p>
      </template>

      <p v-if="err" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ err }}</p>

      <button class="btn-primary w-full justify-center" :disabled="busy">
        {{ busy ? 'Please wait…' : mode === 'setup' ? 'Create account' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>
