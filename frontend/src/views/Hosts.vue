<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import PasswordInput from '../components/PasswordInput.vue'

const props = defineProps({ hosts: Array })
const emit = defineEmits(['changed'])

const checked = ref(new Set())
const status = ref({}) // id -> 'online' | 'offline' | 'checking'
const showAdd = ref(false)
const form = ref({ name: '', ip: '', port: 9901, token: '', agent_port: 9110, agent_token: '' })
const addErr = ref('')
const busy = ref(false)
const discovering = ref(false)

async function discoverLocal() {
  addErr.value = ''
  discovering.value = true
  try {
    const d = await api.discoverLocal()
    form.value.ip = d.ip
    form.value.port = d.port
    form.value.token = d.token
    if (!form.value.name) form.value.name = 'local'
  } catch (e) {
    addErr.value = e.message
  } finally {
    discovering.value = false
  }
}

// --- remote install (SSH provisioning) ---
const showInstall = ref(false)
const instBusy = ref(false)
const instErr = ref('')
const instResult = ref(null)
const inst = ref(defaultInstall())

function defaultInstall() {
  return {
    target: 'agent', // 'agent' | 'router'
    ssh: { host: '', port: 22, user: 'root', authMethod: 'password', password: '', key: '' },
    name: '',
    agent_bind: '0.0.0.0', agent_port: '',
    api_bind: '0.0.0.0', api_port: 9901,
    version: '',
  }
}

function openInstall() {
  inst.value = defaultInstall()
  instErr.value = ''
  instResult.value = null
  showInstall.value = true
}

async function runInstall() {
  instErr.value = ''
  instResult.value = null
  instBusy.value = true
  const i = inst.value
  const ssh = { host: i.ssh.host, port: Number(i.ssh.port) || 22, user: i.ssh.user }
  if (i.ssh.authMethod === 'key') ssh.key = i.ssh.key
  else ssh.password = i.ssh.password
  try {
    if (i.target === 'agent') {
      instResult.value = await api.provisionAgent({
        ssh, name: i.name || i.ssh.host, agent_bind: i.agent_bind,
        agent_port: i.agent_port ? Number(i.agent_port) : null,
        version: i.version || null,
      })
    } else {
      instResult.value = await api.provisionRouter({
        ssh, name: i.name || i.ssh.host, api_bind: i.api_bind,
        api_port: Number(i.api_port) || 9901,
        version: i.version || null,
      })
    }
    emit('changed')
    setTimeout(pingAll, 500)
  } catch (e) {
    instErr.value = e.message
  } finally {
    instBusy.value = false
  }
}

function toggle(id) {
  checked.value.has(id) ? checked.value.delete(id) : checked.value.add(id)
  checked.value = new Set(checked.value)
}
function toggleAll(e) {
  checked.value = e.target.checked ? new Set(props.hosts.map((h) => h.id)) : new Set()
}

async function pingAll() {
  for (const h of props.hosts) {
    if (h?.id == null) continue // never ping a host without an id (avoids /hosts/undefined/status)
    status.value[h.id] = 'checking'
    try {
      await api.status(h.id)
      status.value[h.id] = 'online'
    } catch {
      status.value[h.id] = 'offline'
    }
  }
}

async function addHost() {
  addErr.value = ''
  busy.value = true
  try {
    await api.addHost(form.value)
    showAdd.value = false
    form.value = { name: '', ip: '', port: 9901, token: '', agent_port: 9110, agent_token: '' }
    emit('changed')
    setTimeout(pingAll, 300)
  } catch (e) {
    addErr.value = e.message
  } finally {
    busy.value = false
  }
}

async function removeOne(id) {
  if (!confirm('Delete this host?')) return
  await api.deleteHost(id)
  emit('changed')
}

async function removeChecked() {
  if (!checked.value.size || !confirm(`Delete ${checked.value.size} host(s)?`)) return
  await api.deleteHosts([...checked.value])
  checked.value = new Set()
  emit('changed')
}

onMounted(pingAll)
</script>

<template>
  <div>
    <div class="mb-5 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-slate-100">Hosts</h1>
      <div class="flex gap-2">
        <button class="btn-danger" :disabled="!checked.size" @click="removeChecked">
          Delete selected ({{ checked.size }})
        </button>
        <button class="btn-ghost" @click="openInstall">⇩ Remote install</button>
        <button class="btn-primary" @click="showAdd = true">+ Add Host</button>
      </div>
    </div>

    <div class="card overflow-x-auto p-0">
      <table class="w-full text-sm">
        <thead class="border-b border-slate-800 text-left text-slate-400">
          <tr>
            <th class="w-10 p-3"><input type="checkbox" @change="toggleAll" /></th>
            <th class="p-3">Name</th>
            <th class="p-3">IP : Port</th>
            <th class="p-3">API Status</th>
            <th class="w-16 p-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in hosts" :key="h.id" class="border-b border-slate-800/60 hover:bg-slate-800/30">
            <td class="p-3"><input type="checkbox" :checked="checked.has(h.id)" @change="toggle(h.id)" /></td>
            <td class="p-3 font-medium text-slate-200">{{ h.name }}</td>
            <td class="p-3 text-slate-400">{{ h.ip }}:{{ h.port }}</td>
            <td class="p-3">
              <span class="inline-flex items-center gap-2">
                <span class="h-2.5 w-2.5 rounded-full"
                  :class="{
                    'bg-emerald-500': status[h.id] === 'online',
                    'bg-red-500': status[h.id] === 'offline',
                    'bg-slate-500 animate-pulse': status[h.id] === 'checking' || !status[h.id],
                  }"></span>
                <span class="text-slate-400">{{ status[h.id] || 'checking' }}</span>
              </span>
            </td>
            <td class="p-3">
              <button class="text-red-500 hover:text-red-400" title="Delete" @click="removeOne(h.id)">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 6h18M8 6V4h8v2m-9 0v14a2 2 0 002 2h6a2 2 0 002-2V6M10 11v6M14 11v6" />
                </svg>
              </button>
            </td>
          </tr>
          <tr v-if="!hosts.length">
            <td colspan="5" class="p-8 text-center text-slate-500">No hosts yet. Add one to start.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add modal -->
    <div v-if="showAdd" class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
         @click.self="showAdd = false">
      <div class="card w-full max-w-md">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-lg font-semibold text-slate-100">Add Host</h2>
          <button class="text-slate-400 hover:text-slate-200" @click="showAdd = false">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <button type="button" class="btn-ghost mb-4 w-full justify-center" :disabled="discovering"
                @click="discoverLocal">
          {{ discovering ? 'Searching…' : '🔍 Find local sni-router config' }}
        </button>
        <form @submit.prevent="addHost">
          <label class="label">Server Name</label>
          <input v-model="form.name" class="input mb-3" required />
          <div class="mb-3 grid grid-cols-3 gap-3">
            <div class="col-span-2">
              <label class="label">API IP</label>
              <input v-model="form.ip" class="input" placeholder="127.0.0.1" required />
            </div>
            <div>
              <label class="label">API Port</label>
              <input v-model.number="form.port" type="number" class="input" required />
            </div>
          </div>
          <label class="label">API Token (required for save/restart)</label>
          <PasswordInput v-model="form.token" class="mb-3" placeholder="Bearer token" />
          <div class="mb-3">
            <label class="label">Agent port</label>
            <input v-model.number="form.agent_port" type="number" class="input" />
          </div>
          <label class="label">Agent token (blank = same as API token)</label>
          <PasswordInput v-model="form.agent_token" class="mb-3" placeholder="leave blank to reuse API token" />
          <p v-if="addErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ addErr }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="showAdd = false">Close</button>
            <button class="btn-primary" :disabled="busy">Add</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Remote install modal -->
    <div v-if="showInstall" class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
         @click.self="showInstall = false">
      <div class="card max-h-[90vh] w-full max-w-lg overflow-y-auto">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-lg font-semibold text-slate-100">Remote install (SSH)</h2>
          <button class="text-slate-400 hover:text-slate-200" @click="showInstall = false">✕</button>
        </div>

        <template v-if="!instResult">
          <label class="label">What to install</label>
          <div class="mb-4 flex gap-2">
            <button type="button" class="flex-1 rounded-lg px-3 py-2 text-sm"
              :class="inst.target === 'agent' ? 'bg-brand text-white' : 'bg-slate-800 text-slate-300'"
              @click="inst.target = 'agent'">Metrics agent</button>
            <button type="button" class="flex-1 rounded-lg px-3 py-2 text-sm"
              :class="inst.target === 'router' ? 'bg-brand text-white' : 'bg-slate-800 text-slate-300'"
              @click="inst.target = 'router'">sni-router</button>
          </div>

          <form @submit.prevent="runInstall">
            <div class="mb-3 grid grid-cols-3 gap-3">
              <div class="col-span-2">
                <label class="label">SSH host / IP</label>
                <input v-model="inst.ssh.host" class="input" placeholder="203.0.113.5" required />
              </div>
              <div>
                <label class="label">SSH port</label>
                <input v-model.number="inst.ssh.port" type="number" class="input" />
              </div>
            </div>
            <label class="label">SSH user</label>
            <input v-model="inst.ssh.user" class="input mb-3" placeholder="root" />

            <label class="label">Authentication</label>
            <div class="mb-2 flex gap-2">
              <button type="button" class="flex-1 rounded-lg px-3 py-2 text-sm"
                :class="inst.ssh.authMethod === 'password' ? 'bg-brand text-white' : 'bg-slate-800 text-slate-300'"
                @click="inst.ssh.authMethod = 'password'">Password</button>
              <button type="button" class="flex-1 rounded-lg px-3 py-2 text-sm"
                :class="inst.ssh.authMethod === 'key' ? 'bg-brand text-white' : 'bg-slate-800 text-slate-300'"
                @click="inst.ssh.authMethod = 'key'">Private key</button>
            </div>
            <PasswordInput v-if="inst.ssh.authMethod === 'password'" v-model="inst.ssh.password"
                   class="mb-3" placeholder="SSH password" autocomplete="off" />
            <textarea v-else v-model="inst.ssh.key" class="input mb-3 h-24 font-mono text-xs"
                      placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea>

            <label class="label">Host name (shown in UI)</label>
            <input v-model="inst.name" class="input mb-3" :placeholder="inst.ssh.host || 'my-server'" />

            <div v-if="inst.target === 'agent'" class="mb-3 grid grid-cols-2 gap-3">
              <div><label class="label">Agent bind IP</label><input v-model="inst.agent_bind" class="input" /></div>
              <div><label class="label">Agent port (blank = random)</label><input v-model="inst.agent_port" type="number" class="input" /></div>
            </div>
            <div v-else class="mb-3 grid grid-cols-2 gap-3">
              <div><label class="label">API bind IP</label><input v-model="inst.api_bind" class="input" /></div>
              <div><label class="label">API port</label><input v-model.number="inst.api_port" type="number" class="input" /></div>
            </div>

            <label class="label">Version (blank = latest)</label>
            <input v-model="inst.version" class="input mb-3" placeholder="latest" />

            <p class="mb-3 text-xs text-slate-500">
              SSH credentials are used once for this install and never stored. The token is generated automatically.
            </p>
            <p v-if="instErr" class="mb-3 whitespace-pre-wrap rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ instErr }}</p>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="showInstall = false">Close</button>
              <button class="btn-primary" :disabled="instBusy">{{ instBusy ? 'Installing…' : 'Install' }}</button>
            </div>
          </form>
        </template>

        <template v-else>
          <div class="mb-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">
            Installed. Host saved / updated in the list.
          </div>
          <div class="mb-3 space-y-1 text-sm">
            <div v-if="instResult.token">
              <span class="text-slate-400">Token:</span>
              <span class="break-all font-mono text-slate-200">{{ instResult.token }}</span>
            </div>
            <div v-if="instResult.agent_port">
              <span class="text-slate-400">Agent port:</span> <span class="text-slate-200">{{ instResult.agent_port }}</span>
            </div>
            <div v-if="instResult.api_port">
              <span class="text-slate-400">API port:</span> <span class="text-slate-200">{{ instResult.api_port }}</span>
            </div>
          </div>
          <label class="label">Install log</label>
          <pre class="mb-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ instResult.log }}</pre>
          <div class="flex justify-end">
            <button class="btn-primary" @click="showInstall = false">Done</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
