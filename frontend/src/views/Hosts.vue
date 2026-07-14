<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const props = defineProps({ hosts: Array })
const emit = defineEmits(['changed'])

const checked = ref(new Set())
const status = ref({}) // id -> 'online' | 'offline' | 'checking'
const showAdd = ref(false)
const form = ref({ name: '', ip: '', port: 9901, token: '', metrics_port: 9100, agent_port: 9110 })
const addErr = ref('')
const busy = ref(false)

function toggle(id) {
  checked.value.has(id) ? checked.value.delete(id) : checked.value.add(id)
  checked.value = new Set(checked.value)
}
function toggleAll(e) {
  checked.value = e.target.checked ? new Set(props.hosts.map((h) => h.id)) : new Set()
}

async function pingAll() {
  for (const h of props.hosts) {
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
    form.value = { name: '', ip: '', port: 9901, token: '', metrics_port: 9100, agent_port: 9110 }
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
        <form @submit.prevent="addHost">
          <label class="label">Server Name</label>
          <input v-model="form.name" class="input mb-3" required />
          <div class="mb-3 grid grid-cols-3 gap-3">
            <div class="col-span-2">
              <label class="label">Admin API IP</label>
              <input v-model="form.ip" class="input" placeholder="127.0.0.1" required />
            </div>
            <div>
              <label class="label">Port</label>
              <input v-model.number="form.port" type="number" class="input" required />
            </div>
          </div>
          <label class="label">API Token (required for save/restart)</label>
          <input v-model="form.token" class="input mb-3" placeholder="Bearer token" />
          <div class="mb-3 grid grid-cols-2 gap-3">
            <div>
              <label class="label">Metrics port</label>
              <input v-model.number="form.metrics_port" type="number" class="input" />
            </div>
            <div>
              <label class="label">Agent port</label>
              <input v-model.number="form.agent_port" type="number" class="input" />
            </div>
          </div>
          <p v-if="addErr" class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ addErr }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="showAdd = false">Close</button>
            <button class="btn-primary" :disabled="busy">Add</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
