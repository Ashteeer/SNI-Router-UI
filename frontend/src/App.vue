<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from './api'
import Login from './views/Login.vue'
import Dashboard from './views/Dashboard.vue'
import Hosts from './views/Hosts.vue'
import Configs from './views/Configs.vue'
import Settings from './views/Settings.vue'

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

// icons kept inline (arrays of SVG path `d`) so there's no icon dependency
const tabs = [
  { id: 'dashboard', label: 'Dashboard', icon: ['M3 3h7v7H3z', 'M14 3h7v4h-7z', 'M14 10h7v11h-7z', 'M3 13h7v8H3z'] },
  { id: 'hosts', label: 'Hosts', icon: ['M3 4h18v6H3z', 'M3 14h18v6H3z', 'M7 7h.01', 'M7 17h.01'] },
  { id: 'configs', label: 'Configs', icon: ['M4 21v-7', 'M4 10V3', 'M12 21v-9', 'M12 8V3', 'M20 21v-5', 'M20 12V3', 'M1 14h6', 'M9 8h6', 'M17 16h6'] },
  { id: 'settings', label: 'Settings', icon: ['M12 15a3 3 0 100-6 3 3 0 000 6z', 'M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z'] },
]

// the global host switcher only makes sense on host-scoped tabs
const showHostSwitcher = computed(() => tab.value === 'dashboard' || tab.value === 'configs')
</script>

<template>
  <div class="aurora" aria-hidden="true"></div>

  <div v-if="authState === 'loading'" class="grid h-full place-items-center text-slate-500">
    <div class="flex items-center gap-3 animate-fade-up">
      <span class="dot dot-wait"></span> Loading…
    </div>
  </div>

  <Login
    v-else-if="authState === 'setup' || authState === 'login'"
    :mode="authState"
    @authed="refreshAuth"
  />

  <div v-else class="flex min-h-full flex-col">
    <!-- Top navbar (sticky glass) -->
    <header class="sticky top-0 z-40 border-b border-[var(--border)] bg-[rgba(10,11,16,0.65)] backdrop-blur-xl">
      <div class="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
        <!-- brand -->
        <div class="flex items-center gap-2.5">
          <div class="grid h-9 w-9 place-items-center rounded-xl font-bold text-white shadow-lg"
               style="background: linear-gradient(135deg, var(--accent-strong), var(--accent-2)); box-shadow: 0 8px 20px -8px var(--glow)">S</div>
          <div class="hidden font-semibold tracking-tight text-slate-100 sm:block">SNI-Router</div>
        </div>

        <!-- desktop nav -->
        <nav class="ml-4 hidden items-center gap-1 md:flex">
          <button v-for="t in tabs" :key="t.id"
            class="nav-link" :class="{ 'nav-link--active': tab === t.id }" @click="tab = t.id">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path v-for="(d, i) in t.icon" :key="i" :d="d" />
            </svg>
            {{ t.label }}
          </button>
        </nav>

        <div class="ml-auto flex items-center gap-2 sm:gap-3">
          <!-- global host switcher -->
          <div v-if="showHostSwitcher && hosts.length" class="relative">
            <svg class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01" />
            </svg>
            <select v-model="currentHostId"
              class="input w-[8.5rem] cursor-pointer !py-1.5 !pl-8 text-sm sm:w-44">
              <option v-for="h in hosts" :key="h.id" :value="h.id">{{ h.name }}</option>
            </select>
          </div>

          <button class="btn-ghost !px-2.5" title="Log out" @click="logout">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
            <span class="hidden sm:inline">Log out</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Main -->
    <main class="mx-auto w-full max-w-7xl flex-1 px-4 pb-24 pt-6 sm:px-6 md:pb-10">
      <!-- grid so entering/leaving views stack in the same cell (clean crossfade,
           and the new view mounts immediately — never gated on the leave finishing) -->
      <div class="grid">
        <Transition name="view" type="transition" appear>
          <Dashboard v-if="tab === 'dashboard'" key="dashboard" :hosts="hosts" v-model:hostId="currentHostId" />
          <Hosts v-else-if="tab === 'hosts'" key="hosts" :hosts="hosts" @changed="loadHosts" />
          <Configs v-else-if="tab === 'configs'" key="configs" :hosts="hosts" v-model:hostId="currentHostId" />
          <Settings v-else key="settings" />
        </Transition>
      </div>
    </main>

    <!-- Mobile bottom tab bar -->
    <nav class="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--border)] bg-[rgba(10,11,16,0.8)] backdrop-blur-xl md:hidden">
      <div class="mx-auto grid max-w-md grid-cols-4">
        <button v-for="t in tabs" :key="t.id"
          class="flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors"
          :class="tab === t.id ? 'text-white' : 'text-slate-500'"
          @click="tab = t.id">
          <span class="grid h-8 w-12 place-items-center rounded-lg transition-all"
                :class="tab === t.id ? 'bg-[var(--surface-3)]' : ''">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path v-for="(d, i) in t.icon" :key="i" :d="d" />
            </svg>
          </span>
          {{ t.label }}
        </button>
      </div>
    </nav>
  </div>
</template>
