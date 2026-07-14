<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import PasswordInput from '../components/PasswordInput.vue'

const props = defineProps({ hosts: Array })
const emit = defineEmits(['changed'])

const checked = ref(new Set())
const status = ref({})       // id -> 'online' | 'offline' | 'checking'  (router API)
const agentStatus = ref({})  // id -> 'online' | 'offline' | 'checking'  (agent API)
const showAdd = ref(false)
const editId = ref(null)     // null = adding a new host, else editing this id
const form = ref(blankForm())
const addErr = ref('')
const busy = ref(false)
const discovering = ref(false)

function blankForm() {
  return { name: '', ip: '', port: 9901, token: '',
           agent_ip: '', agent_port: 9110, agent_token: '' }
}
function openAdd() {
  editId.value = null
  form.value = blankForm()
  addErr.value = ''
  showAdd.value = true
}
function openEdit(h) {
  editId.value = h.id
  // tokens aren't returned by the API (only has_token) — leave blank = keep existing
  form.value = { name: h.name, ip: h.ip, port: h.port, token: '',
                 agent_ip: h.agent_ip || '', agent_port: h.agent_port, agent_token: '' }
  addErr.value = ''
  showAdd.value = true
}
function closeModal() {
  showAdd.value = false
  editId.value = null
}
// blank agent IP means "same as the API IP" — fill it in when the field loses focus
function fillAgentIp() {
  if (!form.value.agent_ip) form.value.agent_ip = form.value.ip
}

const routerEndpoint = (h) => `${h.ip}:${h.port}`
const agentEndpoint = (h) => `${h.agent_ip || h.ip}:${h.agent_port}`
function dotClass(state) {
  return {
    'bg-emerald-500': state === 'online',
    'bg-red-500': state === 'offline',
    'bg-slate-500 animate-pulse': state === 'checking' || !state,
  }
}

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

// --- remote install (SSH provisioning; always a clean install) ---
const showInstall = ref(false)
const instBusy = ref(false)
const instErr = ref('')
const instResult = ref(null)
const inst = ref(defaultInstall())

function defaultInstall() {
  return {
    targets: { agent: true, router: false },
    mode: 'new',      // 'new' | 'update'
    host_id: null,    // set when mode === 'update'
    ssh: { host: '', port: 22, user: 'root', authMethod: 'password', password: '', key: '' },
    name: '',
    api_bind: '0.0.0.0', api_port: 9901,
    agent_bind: '0.0.0.0', agent_port: '', agent_ip: '',
    version: '',
  }
}
function openInstall() {
  inst.value = defaultInstall()
  instErr.value = ''
  instResult.value = null
  showInstall.value = true
}
function selectUpdateHost(id) {
  const h = props.hosts.find((x) => x.id === id)
  inst.value.host_id = id
  if (!h) return
  // prefill current values as a starting point — the operator overwrites them
  inst.value.name = h.name
  inst.value.ssh.host = h.ip
  inst.value.api_port = h.port
  inst.value.agent_ip = h.agent_ip || ''
  inst.value.agent_port = h.agent_port || ''
}
// blank agent IP → the SSH/API host on blur (mirrors the Add-host behaviour)
function fillInstAgentIp() {
  if (!inst.value.agent_ip) inst.value.agent_ip = inst.value.ssh.host
}

async function runInstall() {
  instErr.value = ''
  const i = inst.value
  const targets = Object.keys(i.targets).filter((k) => i.targets[k])
  if (!targets.length) { instErr.value = 'Select at least one thing to install.'; return }
  if (i.mode === 'update' && !i.host_id) { instErr.value = 'Pick a host to update.'; return }

  const ssh = { host: i.ssh.host, port: Number(i.ssh.port) || 22, user: i.ssh.user }
  if (i.ssh.authMethod === 'key') ssh.key = i.ssh.key
  else ssh.password = i.ssh.password

  const payload = { targets, ssh, name: i.name || i.ssh.host, version: i.version || null }
  if (i.targets.router) { payload.api_bind = i.api_bind; payload.api_port = Number(i.api_port) || 9901 }
  if (i.targets.agent) {
    payload.agent_bind = i.agent_bind
    payload.agent_port = i.agent_port ? Number(i.agent_port) : null
    payload.agent_ip = i.agent_ip || null
  }
  if (i.mode === 'update' && i.host_id) payload.host_id = i.host_id

  instResult.value = null
  instBusy.value = true
  try {
    instResult.value = await api.provision(payload)
    emit('changed')
    setTimeout(pingAll, 800)
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
    agentStatus.value[h.id] = 'checking'
    api.status(h.id).then(() => (status.value[h.id] = 'online'), () => (status.value[h.id] = 'offline'))
    api.agentInfo(h.id).then(() => (agentStatus.value[h.id] = 'online'), () => (agentStatus.value[h.id] = 'offline'))
  }
}

async function saveHost() {
  addErr.value = ''
  busy.value = true
  try {
    const f = form.value
    if (editId.value != null) {
      // send tokens only when filled — blank means "keep the stored one"
      const payload = { name: f.name, ip: f.ip, port: f.port,
                        agent_ip: f.agent_ip, agent_port: f.agent_port }
      if (f.token) payload.token = f.token
      if (f.agent_token) payload.agent_token = f.agent_token
      await api.updateHost(editId.value, payload)
    } else {
      await api.addHost(f)
    }
    closeModal()
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
        <button class="btn-primary" @click="openAdd">+ Add Host</button>
      </div>
    </div>

    <div class="card overflow-x-auto p-0">
      <table class="w-full text-sm">
        <thead class="border-b border-slate-800 text-left text-slate-400">
          <tr>
            <th class="w-10 p-3"><input type="checkbox" @change="toggleAll" /></th>
            <th class="p-3">Name</th>
            <th class="p-3">sni-router API</th>
            <th class="p-3">Metrics agent</th>
            <th class="w-16 p-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in hosts" :key="h.id" class="border-b border-slate-800/60 hover:bg-slate-800/30">
            <td class="p-3"><input type="checkbox" :checked="checked.has(h.id)" @change="toggle(h.id)" /></td>
            <td class="p-3 font-medium text-slate-200">{{ h.name }}</td>
            <td class="p-3">
              <div class="font-mono text-xs text-slate-400">{{ routerEndpoint(h) }}</div>
              <span class="mt-1 inline-flex items-center gap-2">
                <span class="h-2.5 w-2.5 rounded-full" :class="dotClass(status[h.id])"></span>
                <span class="text-xs text-slate-400">{{ status[h.id] || 'checking' }}</span>
              </span>
            </td>
            <td class="p-3">
              <div class="font-mono text-xs text-slate-400">{{ agentEndpoint(h) }}</div>
              <span class="mt-1 inline-flex items-center gap-2">
                <span class="h-2.5 w-2.5 rounded-full" :class="dotClass(agentStatus[h.id])"></span>
                <span class="text-xs text-slate-400">{{ agentStatus[h.id] || 'checking' }}</span>
              </span>
            </td>
            <td class="p-3">
              <div class="flex items-center gap-3">
                <button class="text-slate-400 hover:text-slate-200" title="Edit" @click="openEdit(h)">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4 12.5-12.5z" />
                  </svg>
                </button>
                <button class="text-red-500 hover:text-red-400" title="Delete" @click="removeOne(h.id)">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M8 6V4h8v2m-9 0v14a2 2 0 002 2h6a2 2 0 002-2V6M10 11v6M14 11v6" />
                  </svg>
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!hosts.length">
            <td colspan="5" class="p-8 text-center text-slate-500">No hosts yet. Add one to start.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add / Edit modal -->
    <div v-if="showAdd" class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
         @click.self="closeModal">
      <div class="card w-full max-w-md">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-lg font-semibold text-slate-100">{{ editId != null ? 'Edit Host' : 'Add Host' }}</h2>
          <button class="text-slate-400 hover:text-slate-200" @click="closeModal">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <button v-if="editId == null" type="button" class="btn-ghost mb-4 w-full justify-center"
                :disabled="discovering" @click="discoverLocal">
          {{ discovering ? 'Searching…' : '🔍 Find local sni-router config' }}
        </button>
        <form @submit.prevent="saveHost">
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
          <PasswordInput v-model="form.token" class="mb-3"
            :placeholder="editId != null ? 'leave blank to keep current token' : 'Bearer token'" />
          <div class="mb-3 grid grid-cols-3 gap-3">
            <div class="col-span-2">
              <label class="label">Agent IP</label>
              <input v-model="form.agent_ip" class="input" :placeholder="form.ip || 'same as API IP'"
                     @blur="fillAgentIp" />
            </div>
            <div>
              <label class="label">Agent Port</label>
              <input v-model.number="form.agent_port" type="number" class="input" />
            </div>
          </div>
          <label class="label">Agent token (blank = same as API token)</label>
          <PasswordInput v-model="form.agent_token" class="mb-3"
            :placeholder="editId != null ? 'leave blank to keep current agent token' : 'leave blank to reuse API token'" />
          <p v-if="addErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ addErr }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="closeModal">Close</button>
            <button class="btn-primary" :disabled="busy">{{ editId != null ? 'Save' : 'Add' }}</button>
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
          <label class="label">What to install (clean install — wipes old config)</label>
          <div class="mb-4 flex flex-wrap gap-4">
            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" v-model="inst.targets.agent" /> Metrics agent
            </label>
            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" v-model="inst.targets.router" /> sni-router
            </label>
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

            <div v-if="inst.targets.router" class="mb-3 grid grid-cols-2 gap-3">
              <div><label class="label">sni-router API bind IP</label><input v-model="inst.api_bind" class="input" /></div>
              <div><label class="label">sni-router API port</label><input v-model.number="inst.api_port" type="number" class="input" /></div>
            </div>
            <div v-if="inst.targets.agent" class="mb-3 grid grid-cols-3 gap-3">
              <div><label class="label">Agent bind IP</label><input v-model="inst.agent_bind" class="input" /></div>
              <div>
                <label class="label">Agent IP (reach)</label>
                <input v-model="inst.agent_ip" class="input" :placeholder="inst.ssh.host || 'same as API IP'" @blur="fillInstAgentIp" />
              </div>
              <div><label class="label">Agent port</label><input v-model="inst.agent_port" type="number" class="input" placeholder="random" /></div>
            </div>

            <label class="label">Version (blank = latest)</label>
            <input v-model="inst.version" class="input mb-4" placeholder="latest" />

            <!-- new connection vs update existing -->
            <div class="mb-3 flex overflow-hidden rounded-lg border border-slate-700">
              <button type="button" class="flex-1 px-3 py-2 text-sm"
                :class="inst.mode === 'new' ? 'bg-brand text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'"
                @click="inst.mode = 'new'; inst.host_id = null">Create new connection</button>
              <button type="button" class="flex-1 px-3 py-2 text-sm"
                :class="inst.mode === 'update' ? 'bg-brand text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'"
                @click="inst.mode = 'update'">Update existing</button>
            </div>
            <div v-if="inst.mode === 'new'" class="mb-3">
              <label class="label">Host name (shown in UI)</label>
              <input v-model="inst.name" class="input" :placeholder="inst.ssh.host || 'my-server'" />
            </div>
            <div v-else class="mb-3">
              <label class="label">Host to overwrite</label>
              <select class="input" :value="inst.host_id"
                @change="selectUpdateHost(Number($event.target.value))">
                <option :value="null" disabled>— pick a host —</option>
                <option v-for="h in hosts" :key="h.id" :value="h.id">{{ h.name }} ({{ h.ip }})</option>
              </select>
              <p class="mt-1 text-xs text-slate-500">Reinstalls and overwrites its IP:PORT + tokens with the values above.</p>
            </div>

            <p class="mb-3 text-xs text-slate-500">
              SSH credentials are used once for this install and never stored. A fresh token is generated automatically.
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
            Installed ({{ instResult.targets?.join(' + ') }}). Host saved / updated in the list.
          </div>
          <div class="mb-3 space-y-1 text-sm">
            <div v-if="instResult.token">
              <span class="text-slate-400">Token:</span>
              <span class="break-all font-mono text-slate-200">{{ instResult.token }}</span>
            </div>
            <div v-if="instResult.api_port">
              <span class="text-slate-400">API port:</span> <span class="text-slate-200">{{ instResult.api_port }}</span>
            </div>
            <div v-if="instResult.agent_port">
              <span class="text-slate-400">Agent:</span>
              <span class="text-slate-200">{{ instResult.agent_ip }}:{{ instResult.agent_port }}</span>
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
