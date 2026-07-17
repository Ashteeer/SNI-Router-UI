<script setup>
import { ref, onMounted } from 'vue'
import PasswordInput from '../components/PasswordInput.vue'
import { api } from '../api'

const fields = ref([])
const values = ref({})
const confPath = ref('')
const whitelist = ref('')

const cfgMsg = ref('')
const cfgErr = ref('')
const wlMsg = ref('')
const wlErr = ref('')
const busyCfg = ref(false)
const busyWl = ref(false)

// admin login/password
const acct = ref({ username: '', password: '' })
const acctMsg = ref('')
const acctErr = ref('')
const busyAcct = ref(false)

async function load() {
  try {
    const c = await api.getLocalConfig()
    fields.value = c.fields
    values.value = { ...c.values }
    confPath.value = c.path
  } catch (e) {
    cfgErr.value = e.message
  }
  try {
    const s = await api.getSettings()
    whitelist.value = (s.ip_whitelist || []).join(', ')
    acct.value.username = s.admin_user || ''
  } catch (e) {
    wlErr.value = e.message
  }
}

async function saveAccount() {
  acctMsg.value = ''
  acctErr.value = ''
  busyAcct.value = true
  try {
    await api.changeAccount({ username: acct.value.username, password: acct.value.password })
    acct.value.password = ''
    acctMsg.value = 'Login updated. Use the new credentials next time you sign in.'
  } catch (e) {
    acctErr.value = e.message
  } finally {
    busyAcct.value = false
  }
}

async function saveConfig() {
  cfgMsg.value = ''
  cfgErr.value = ''
  busyCfg.value = true
  try {
    await api.putLocalConfig(values.value)
    cfgMsg.value = 'Saved. Restart the UI service for host/port/DB changes to take effect.'
  } catch (e) {
    cfgErr.value = e.message
  } finally {
    busyCfg.value = false
  }
}

async function saveWhitelist() {
  wlMsg.value = ''
  wlErr.value = ''
  busyWl.value = true
  try {
    const ip_whitelist = whitelist.value.split(',').map((s) => s.trim()).filter(Boolean)
    await api.putSettings({ ip_whitelist })
    wlMsg.value = 'Whitelist saved.'
  } catch (e) {
    wlErr.value = e.message
  } finally {
    busyWl.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="max-w-2xl">
    <h1 class="mb-5 text-2xl font-semibold tracking-tight text-slate-100">Settings</h1>

    <!-- Admin login -->
    <div class="card mb-6">
      <h2 class="mb-1 text-lg font-semibold text-slate-100">Admin login</h2>
      <p class="mb-4 text-sm text-slate-400">
        Change the sign-in username and/or password. Leave the password blank to keep the current one.
      </p>
      <label class="label">Username</label>
      <input v-model="acct.username" class="input mb-3" autocomplete="username" />
      <label class="label">New password</label>
      <PasswordInput v-model="acct.password" class="mb-3" placeholder="leave blank to keep current"
                     autocomplete="new-password" />
      <p v-if="acctErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ acctErr }}</p>
      <p v-if="acctMsg" class="mb-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">{{ acctMsg }}</p>
      <div class="flex justify-end">
        <button class="btn-primary" :disabled="busyAcct || !acct.username" @click="saveAccount">Save login</button>
      </div>
    </div>

    <!-- Local site config -->
    <div class="card mb-6">
      <h2 class="mb-1 text-lg font-semibold text-slate-100">Site configuration</h2>
      <p class="mb-4 text-sm text-slate-400">
        Local config of the machine running this UI
        <span v-if="confPath" class="text-slate-500">({{ confPath }})</span>.
        Only local config is editable here — agents are configured on their own hosts.
      </p>

      <div v-for="f in fields" :key="f.key" class="mb-3">
        <label class="label">
          {{ f.label }}
          <span v-if="f.restart" class="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-400">restart</span>
        </label>
        <input v-model="values[f.key]" class="input" :placeholder="f.key" />
        <p v-if="f.hint" class="mt-1 text-xs text-slate-500">{{ f.hint }}</p>
      </div>

      <p v-if="cfgErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ cfgErr }}</p>
      <p v-if="cfgMsg" class="mb-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">{{ cfgMsg }}</p>
      <div class="flex justify-end">
        <button class="btn-primary" :disabled="busyCfg" @click="saveConfig">Save config</button>
      </div>
    </div>

    <!-- IP whitelist -->
    <div class="card">
      <h2 class="mb-1 text-lg font-semibold text-slate-100">IP whitelist</h2>
      <p class="mb-4 text-sm text-slate-400">
        Clients from these IPs/CIDRs skip the login screen. Comma-separated.
      </p>
      <input v-model="whitelist" class="input mb-3" placeholder="127.0.0.1, 10.0.0.0/8" />
      <p v-if="wlErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ wlErr }}</p>
      <p v-if="wlMsg" class="mb-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">{{ wlMsg }}</p>
      <div class="flex justify-end">
        <button class="btn-primary" :disabled="busyWl" @click="saveWhitelist">Save whitelist</button>
      </div>
    </div>
  </div>
</template>
