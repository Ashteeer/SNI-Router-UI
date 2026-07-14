<script setup>
import { ref, onMounted } from 'vue'
import { api } from './api'
import Login from './views/Login.vue'
import Dashboard from './views/Dashboard.vue'
import Hosts from './views/Hosts.vue'
import Configs from './views/Configs.vue'

const authState = ref('loading') // loading | setup | login | ready
const tab = ref('dashboard')
const hosts = ref([])
const currentHostId = ref(null)

async function refreshAuth() {
  const me = await api.me()
  if (me.needs_setup) authState.value = 'setup'
  else if (!me.authenticated) authState.value = 'login'
  else { authState.value = 'ready'; await loadHosts() }
}

async function loadHosts() {
  hosts.value = await api.hosts()
  if (!currentHostId.value && hosts.value.length) currentHostId.value = hosts.value[0].id
  if (currentHostId.value && !hosts.value.find((h) => h.id === currentHostId.value))
    currentHostId.value = hosts.value[0]?.id ?? null
}

async function logout() {
  await api.logout()
  authState.value = 'login'
}

onMounted(refreshAuth)

const tabs = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'hosts', label: 'Hosts' },
  { id: 'configs', label: 'Configs' },
]
</script>

<template>
  <div v-if="authState === 'loading'" class="grid h-full place-items-center text-slate-500">
    Loading…
  </div>

  <Login
    v-else-if="authState === 'setup' || authState === 'login'"
    :mode="authState"
    @authed="refreshAuth"
  />

  <div v-else class="flex h-full">
    <!-- Sidebar -->
    <aside class="flex w-56 flex-col border-r border-slate-800 bg-slate-900/60 p-4">
      <div class="mb-6 flex items-center gap-2 px-1">
        <div class="grid h-8 w-8 place-items-center rounded-lg bg-brand text-white font-bold">S</div>
        <div class="font-semibold text-slate-100">SNI-Router</div>
      </div>
      <nav class="flex flex-col gap-1">
        <button
          v-for="t in tabs"
          :key="t.id"
          class="rounded-lg px-3 py-2 text-left text-sm transition-colors"
          :class="tab === t.id ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'"
          @click="tab = t.id"
        >
          {{ t.label }}
        </button>
      </nav>
      <button class="btn-ghost mt-auto justify-center" @click="logout">Log out</button>
    </aside>

    <!-- Main -->
    <main class="flex-1 overflow-auto p-6">
      <Dashboard
        v-if="tab === 'dashboard'"
        :hosts="hosts"
        v-model:hostId="currentHostId"
      />
      <Hosts v-else-if="tab === 'hosts'" :hosts="hosts" @changed="loadHosts" />
      <Configs
        v-else
        :hosts="hosts"
        v-model:hostId="currentHostId"
      />
    </main>
  </div>
</template>
