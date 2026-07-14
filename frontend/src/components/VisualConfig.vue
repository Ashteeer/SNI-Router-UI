<script setup>
// Mode-aware forms over the parsed config object. Mutates `model` in place;
// the parent watches it deeply and re-serializes to YAML (kept in sync with
// the manual editor). See config.md for the field-applicability matrix.
const props = defineProps({ model: Object })

const MODES = ['passthrough', 'terminate', 'terminate_tcp', 'redirect_https']
const PROXY = ['none', 'v1', 'v2']
const BALANCE = ['round_robin', 'least_conn']
const ACTIONS = ['forward', 'respond', 'redirect']

// field applicability by mode
const uses = {
  servers: (m) => m !== 'redirect_https',
  proxy_protocol: (m) => m === 'passthrough' || m === 'terminate_tcp',
  balance: (m) => m !== 'redirect_https',
  tls: (m) => m === 'terminate' || m === 'terminate_tcp',
  backend_tls: (m) => m === 'terminate',
  headers: (m) => m === 'terminate',
  http2: (m) => m === 'terminate',
  http_rules: (m) => m === 'terminate' || m === 'redirect_https',
}

function ensure(obj, key, val) {
  if (obj[key] == null) obj[key] = val
  return obj[key]
}

// listeners
function addListener() {
  ensure(props.model, 'listeners', [])
  props.model.listeners.push({ name: 'listener', bind: [''], proto: 'tcp', routes: [] })
}
function delListener(i) { props.model.listeners.splice(i, 1) }
function addBind(l) { l.bind.push('') }
function addRoute(l) { ensure(l, 'routes', []).push({ sni: '*', backend: backendNames()[0] || '' }) }

// backends (map)
function backendNames() { return Object.keys(props.model.backends || {}) }
function addBackend() {
  ensure(props.model, 'backends', {})
  let n = 'backend', i = 1
  while (props.model.backends[n]) n = 'backend' + ++i
  props.model.backends[n] = { mode: 'passthrough', servers: [''] }
}
function renameBackend(oldName, e) {
  const nn = e.target.value.trim()
  if (!nn || nn === oldName || props.model.backends[nn]) { e.target.value = oldName; return }
  const val = props.model.backends[oldName]
  delete props.model.backends[oldName]
  props.model.backends[nn] = val
}
function delBackend(name) { delete props.model.backends[name] }
function addServer(be) { ensure(be, 'servers', []).push('') }
function addRule(be) { ensure(be, 'http_rules', []).push({ path: '/', action: 'respond', status: 200 }) }
</script>

<template>
  <div v-if="model" class="space-y-6">
    <!-- Listeners -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Listeners</h3>
        <button class="btn-ghost" @click="addListener">+ Listener</button>
      </div>
      <div v-for="(l, li) in model.listeners" :key="li" class="card mb-3">
        <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label class="label">Name</label>
            <input v-model="l.name" class="input" />
          </div>
          <div>
            <label class="label">Proto</label>
            <select v-model="l.proto" class="input">
              <option value="tcp">tcp</option>
              <option value="udp">udp (QUIC)</option>
            </select>
          </div>
          <div class="flex items-end justify-end">
            <button class="btn-danger" @click="delListener(li)">Remove</button>
          </div>
        </div>

        <label class="label">Bind (IP:port)</label>
        <div v-for="(b, bi) in l.bind" :key="bi" class="mb-2 flex gap-2">
          <input v-model="l.bind[bi]" class="input" placeholder="0.0.0.0:443" />
          <button class="btn-ghost" @click="l.bind.splice(bi, 1)">✕</button>
        </div>
        <button class="btn-ghost mb-3" @click="addBind(l)">+ bind</button>

        <label class="label">Routes (first match wins)</label>
        <div v-for="(r, ri) in l.routes" :key="ri" class="mb-2 flex gap-2">
          <input v-model="r.sni" class="input" placeholder="*.example.com or *" />
          <select v-model="r.backend" class="input">
            <option v-for="n in backendNames()" :key="n" :value="n">{{ n }}</option>
          </select>
          <button class="btn-ghost" @click="l.routes.splice(ri, 1)">✕</button>
        </div>
        <button class="btn-ghost" @click="addRoute(l)">+ route</button>
      </div>
    </section>

    <!-- Backends -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Backends</h3>
        <button class="btn-ghost" @click="addBackend">+ Backend</button>
      </div>
      <div v-for="(be, name) in model.backends" :key="name" class="card mb-3">
        <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label class="label">Name</label>
            <input :value="name" class="input" @change="renameBackend(name, $event)" />
          </div>
          <div>
            <label class="label">Mode</label>
            <select v-model="be.mode" class="input">
              <option v-for="m in MODES" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="flex items-end justify-end">
            <button class="btn-danger" @click="delBackend(name)">Remove</button>
          </div>
        </div>

        <!-- servers -->
        <template v-if="uses.servers(be.mode)">
          <label class="label">Servers (IP:port)</label>
          <div v-for="(s, si) in be.servers" :key="si" class="mb-2 flex gap-2">
            <input v-model="be.servers[si]" class="input" placeholder="127.0.0.1:8080" />
            <button class="btn-ghost" @click="be.servers.splice(si, 1)">✕</button>
          </div>
          <button class="btn-ghost mb-3" @click="addServer(be)">+ server</button>
        </template>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div v-if="uses.proxy_protocol(be.mode)">
            <label class="label">PROXY protocol</label>
            <select v-model="be.proxy_protocol" class="input">
              <option v-for="p in PROXY" :key="p" :value="p">{{ p }}</option>
            </select>
          </div>
          <div v-if="uses.balance(be.mode)">
            <label class="label">Balance</label>
            <select v-model="be.balance" class="input">
              <option v-for="b in BALANCE" :key="b" :value="b">{{ b }}</option>
            </select>
          </div>
        </div>

        <div v-if="uses.balance(be.mode)" class="mt-2 flex items-center gap-2">
          <input :id="'hc' + name" v-model="be.health_check" type="checkbox" />
          <label :for="'hc' + name" class="text-sm text-slate-300">Health check (TCP probe)</label>
        </div>
        <div v-if="uses.http2(be.mode)" class="mt-2 flex items-center gap-2">
          <input :id="'h2' + name" v-model="be.http2" type="checkbox" />
          <label :for="'h2' + name" class="text-sm text-slate-300">HTTP/2 (h2)</label>
        </div>

        <!-- tls -->
        <template v-if="uses.tls(be.mode)">
          <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="label">TLS cert path</label>
              <input :value="be.tls?.cert" class="input"
                @input="ensure(be, 'tls', {}).cert = $event.target.value" placeholder="(or use default_tls)" />
            </div>
            <div>
              <label class="label">TLS key path</label>
              <input :value="be.tls?.key" class="input"
                @input="ensure(be, 'tls', {}).key = $event.target.value" />
            </div>
          </div>
        </template>

        <!-- headers -->
        <template v-if="uses.headers(be.mode)">
          <label class="label mt-3">Injected headers</label>
          <div class="flex flex-wrap gap-4">
            <label v-for="h in ['x_real_ip', 'x_forwarded_for', 'x_forwarded_proto']" :key="h"
                   class="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" :checked="be.headers?.[h]"
                @change="ensure(be, 'headers', {})[h] = $event.target.checked" />
              {{ h }}
            </label>
          </div>
        </template>

        <!-- http_rules -->
        <template v-if="uses.http_rules(be.mode)">
          <label class="label mt-3">HTTP rules (first match wins)</label>
          <div v-for="(r, ri) in be.http_rules" :key="ri" class="mb-2 rounded-lg border border-slate-800 p-2">
            <div class="flex gap-2">
              <input v-model="r.path" class="input" placeholder="/path or *" />
              <select v-model="r.action" class="input w-40">
                <option v-for="a in ACTIONS" :key="a" :value="a">{{ a }}</option>
              </select>
              <button class="btn-ghost" @click="be.http_rules.splice(ri, 1)">✕</button>
            </div>
            <div class="mt-2 grid grid-cols-2 gap-2">
              <input v-if="r.action !== 'forward'" v-model.number="r.status" type="number" class="input" placeholder="status" />
              <input v-if="r.action === 'redirect'" v-model="r.to" class="input" placeholder="https or absolute URL" />
              <input v-if="r.action === 'respond'" v-model="r.body" class="input" placeholder="body" />
              <input v-if="r.action === 'respond'" v-model="r.content_type" class="input" placeholder="content_type" />
            </div>
          </div>
          <button class="btn-ghost" @click="addRule(be)">+ rule</button>
        </template>
      </div>
    </section>

    <!-- Global scalars -->
    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div class="card">
        <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Timeouts (s)</h3>
        <div class="grid grid-cols-2 gap-3">
          <div v-for="k in ['handshake', 'connect', 'idle', 'health_interval', 'drain']" :key="k">
            <label class="label">{{ k }}</label>
            <input :value="model.timeouts?.[k]" type="number" class="input"
              @input="ensure(model, 'timeouts', {})[k] = Number($event.target.value)" />
          </div>
        </div>
      </div>
      <div class="card">
        <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Limits / Log / API</h3>
        <label class="label">max_conns_per_ip</label>
        <input :value="model.limits?.max_conns_per_ip" type="number" class="input mb-3"
          @input="ensure(model, 'limits', {}).max_conns_per_ip = Number($event.target.value)" />
        <label class="label">log.level</label>
        <select :value="model.log?.level" class="input mb-3"
          @change="ensure(model, 'log', {}).level = $event.target.value">
          <option v-for="lv in ['error', 'warn', 'info', 'debug', 'trace']" :key="lv" :value="lv">{{ lv }}</option>
        </select>
        <label class="label">api.bind (config + metrics + control)</label>
        <input :value="model.api?.bind" class="input mb-3" placeholder="0.0.0.0:9901"
          @input="ensure(model, 'api', {}).bind = $event.target.value" />
        <label class="label">api.token</label>
        <input :value="model.api?.token" class="input" placeholder="Bearer token"
          @input="ensure(model, 'api', {}).token = $event.target.value" />
      </div>
      <div class="card">
        <h3 class="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">Default TLS</h3>
        <p class="mb-3 text-xs text-slate-500">
          Shared cert for any <code>terminate</code> backend that has no <code>tls</code> of its own.
        </p>
        <label class="label">default_tls.cert path</label>
        <input :value="model.default_tls?.cert" class="input mb-3" placeholder="/etc/ssl/fullchain.pem"
          @input="ensure(model, 'default_tls', {}).cert = $event.target.value" />
        <label class="label">default_tls.key path</label>
        <input :value="model.default_tls?.key" class="input" placeholder="/etc/ssl/privkey.pem"
          @input="ensure(model, 'default_tls', {}).key = $event.target.value" />
      </div>
    </section>
  </div>
</template>
