<script setup>
// Mode-aware forms over the parsed config object. Mutates `model` in place;
// the parent watches it deeply and re-serializes to YAML (kept in sync with
// the manual editor). See config.md for the field-applicability matrix.
import { ref } from 'vue'

const props = defineProps({ model: Object })

const MODES = ['passthrough', 'terminate', 'terminate_tcp', 'redirect_https']
const PROXY = ['none', 'v1', 'v2']
const BALANCE = ['round_robin', 'least_conn']

// field applicability by mode
const uses = {
  servers: (m) => m !== 'redirect_https',
  proxy_protocol: (m) => m === 'passthrough' || m === 'terminate_tcp',
  balance: (m) => m !== 'redirect_https',
  health_check: (m) => m !== 'redirect_https',
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
// fast_open is tcp-only — on udp it's a hard config error, so drop it with the proto
function setProto(l, p) {
  l.proto = p
  if (p !== 'tcp') delete l.fast_open
}
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
// Switching mode must also drop the fields the new mode doesn't use: a leftover
// `servers: ['']` from the passthrough default is a hard validation error on
// redirect_https (empty string isn't a valid IP:port), and the rest would only
// earn "field ignored for this mode" warnings.
function setMode(be, m) {
  be.mode = m
  for (const [k, applies] of Object.entries(uses)) if (!applies(m)) delete be[k]
  if (uses.servers(m)) ensure(be, 'servers', [''])
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
// new rules default to a 404 catch-all (path "*") — a valid, common "deny the rest"
function addRule(be) {
  ensure(be, 'http_rules', []).push({ path: '*', action: 'respond', status: 404, body: 'not found\n', content_type: 'text/plain' })
}

// --- HTTP-rule presets: hide sni-router's action/status syntax behind simple types.
// The two presets (301 / 404) auto-fill everything; forward/respond/redirect are the
// manual "advanced" escapes. ruleType() derives the current type from the raw rule.
function ruleType(r) {
  if (r.action === 'redirect') return (r.status == null || r.status === 301) ? '301' : 'redirect'
  if (r.action === 'respond') return r.status === 404 ? '404' : 'respond'
  return r.action || 'forward'
}
function setRuleType(r, type) {
  const keepTo = r.to
  delete r.status; delete r.to; delete r.body; delete r.content_type
  if (type === '301') { r.action = 'redirect'; r.status = 301; r.to = keepTo || 'https' }
  else if (type === '404') { r.action = 'respond'; r.status = 404; r.body = 'not found\n'; r.content_type = 'text/plain' }
  else if (type === 'forward') { r.action = 'forward' }
  else if (type === 'respond') { r.action = 'respond'; r.status = 200 }
  else if (type === 'redirect') { r.action = 'redirect'; r.status = 302; r.to = keepTo || 'https' }
}

// --- drag-to-reorder (native HTML5 DnD, no dep). `kind` scopes the drag so items
// can't cross categories; `key` scopes routes to their listener / rules to their
// backend. The drop handler nulls `drag` first, so a bubbled parent drop is a no-op.
const drag = ref(null) // { kind, key, from } | null
function dragStart(kind, from, key = null) { drag.value = { kind, key, from } }
function dragEnd() { drag.value = null }
function moveArr(arr, from, to) {
  if (!arr || from === to || from < 0) return
  const [it] = arr.splice(from, 1)
  arr.splice(to, 0, it)
}
function moveBackend(from, to) {
  const names = Object.keys(props.model.backends || {})
  if (from === to || from < 0) return
  const [n] = names.splice(from, 1)
  names.splice(to, 0, n)
  const rebuilt = {}
  for (const k of names) rebuilt[k] = props.model.backends[k]
  props.model.backends = rebuilt // reassign a map property → deep watcher re-dumps
}
function dropOn(kind, to, key = null) {
  const d = drag.value
  drag.value = null
  if (!d || d.kind !== kind || d.key !== key) return
  if (kind === 'listener') moveArr(props.model.listeners, d.from, to)
  else if (kind === 'backend') moveBackend(d.from, to)
  else if (kind === 'route') moveArr(props.model.listeners[key].routes, d.from, to)
  else if (kind === 'rule') moveArr(props.model.backends[key].http_rules, d.from, to)
}
</script>

<template>
  <div v-if="model" class="space-y-6">
    <!-- Listeners -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Listeners</h3>
        <button class="btn-ghost" @click="addListener">+ Listener</button>
      </div>
      <div v-for="(l, li) in model.listeners" :key="li" class="card mb-3"
           :class="{ 'opacity-50': drag?.kind === 'listener' && drag?.from === li }"
           @dragover.prevent @drop="dropOn('listener', li)">
        <div class="mb-2 flex items-center gap-2">
          <span class="cursor-grab select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                draggable="true" @dragstart="dragStart('listener', li)" @dragend="dragEnd"
                title="Drag to reorder">⠿</span>
          <span class="text-xs uppercase tracking-wide text-slate-500">Listener {{ li + 1 }}</span>
        </div>
        <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label class="label">Name</label>
            <input v-model="l.name" class="input" />
          </div>
          <div>
            <label class="label">Proto</label>
            <select :value="l.proto || 'tcp'" class="input" @change="setProto(l, $event.target.value)">
              <option value="tcp">tcp</option>
              <option value="udp">udp (QUIC)</option>
            </select>
          </div>
          <div class="flex items-end justify-end">
            <button class="btn-danger" @click="delListener(li)">Remove</button>
          </div>
        </div>

        <!-- fast_open (TFO) — tcp only -->
        <div v-if="(l.proto || 'tcp') === 'tcp'" class="mb-3">
          <label class="flex items-center gap-2 text-sm text-slate-300">
            <input :id="'tfo' + li" type="checkbox" :checked="!!l.fast_open"
                   @change="l.fast_open = $event.target.checked" />
            TCP Fast Open
          </label>
          <p class="mt-1 text-xs text-slate-500">
            Lets a returning client send its ClientHello inside the SYN, saving one RTT.
            Needs <code>net.ipv4.tcp_fastopen = 3</code> on the host — otherwise the router
            still starts, TFO just stays inactive. Changing this restarts the listener.
          </p>
        </div>

        <label class="label">Bind (IP:port)</label>
        <div v-for="(b, bi) in l.bind" :key="bi" class="mb-2 flex gap-2">
          <input v-model="l.bind[bi]" class="input" placeholder="0.0.0.0:443" />
          <button class="btn-ghost" @click="l.bind.splice(bi, 1)">✕</button>
        </div>
        <button class="btn-ghost mb-3" @click="addBind(l)">+ bind</button>

        <label class="label">Routes (first match wins — drag ⠿ to reorder)</label>
        <div v-for="(r, ri) in l.routes" :key="ri" class="mb-2 flex items-center gap-2"
             :class="{ 'opacity-50': drag?.kind === 'route' && drag?.key === li && drag?.from === ri }"
             @dragover.prevent @drop="dropOn('route', ri, li)">
          <span class="cursor-grab select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                draggable="true" @dragstart="dragStart('route', ri, li)" @dragend="dragEnd"
                title="Drag to reorder">⠿</span>
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
      <div v-for="(be, name, bi) in model.backends" :key="name" class="card mb-3"
           :class="{ 'opacity-50': drag?.kind === 'backend' && drag?.from === bi }"
           @dragover.prevent @drop="dropOn('backend', bi)">
        <div class="mb-2 flex items-center gap-2">
          <span class="cursor-grab select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                draggable="true" @dragstart="dragStart('backend', bi)" @dragend="dragEnd"
                title="Drag to reorder">⠿</span>
          <span class="text-xs uppercase tracking-wide text-slate-500">Backend</span>
        </div>
        <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label class="label">Name</label>
            <input :value="name" class="input" @change="renameBackend(name, $event)" />
          </div>
          <div>
            <label class="label">Mode</label>
            <select :value="be.mode" class="input" @change="setMode(be, $event.target.value)">
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

        <div v-if="uses.health_check(be.mode)" class="mt-2 flex items-center gap-2">
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
          <label class="label mt-3">HTTP rules (first match wins — drag ⠿ to reorder)</label>
          <div v-for="(r, ri) in be.http_rules" :key="ri"
               class="mb-2 rounded-lg border border-slate-800 p-2"
               :class="{ 'opacity-50': drag?.kind === 'rule' && drag?.key === name && drag?.from === ri }"
               @dragover.prevent @drop="dropOn('rule', ri, name)">
            <div class="flex items-center gap-2">
              <span class="cursor-grab select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                    draggable="true" @dragstart="dragStart('rule', ri, name)" @dragend="dragEnd"
                    title="Drag to reorder">⠿</span>
              <input v-model="r.path" class="input" placeholder="*  (all paths)  or  /prefix" />
              <select :value="ruleType(r)" @change="setRuleType(r, $event.target.value)" class="input w-52">
                <option value="301">301 → https / custom port</option>
                <option value="404">404 Not Found</option>
                <option value="forward">forward (advanced)</option>
                <option value="respond">respond (advanced)</option>
                <option value="redirect">redirect (advanced)</option>
              </select>
              <button class="btn-ghost" @click="be.http_rules.splice(ri, 1)">✕</button>
            </div>
            <p class="mt-1 pl-8 text-xs text-slate-500">
              Path is a <b>prefix</b> match: <code>/api</code> matches <code>/api</code> and <code>/api/…</code>.
              For <b>all</b> paths use <code>*</code> — no trailing <code>*</code> after a slash needed.
            </p>

            <!-- 301 preset: only the target to fill -->
            <div v-if="ruleType(r) === '301'" class="mt-2 pl-8">
              <input v-model="r.to" class="input" placeholder="https   ·   or   https://host:8443" />
              <p class="mt-1 text-xs text-slate-500">
                Sends <b>301</b> → <code>Location</code>. <code>https</code> upgrades to HTTPS on the
                same host (:443); for a <b>custom port</b> enter a full URL, e.g. <code>https://host:8443</code>.
              </p>
            </div>
            <!-- 404 preset: nothing to fill -->
            <p v-else-if="ruleType(r) === '404'" class="mt-2 pl-8 text-xs text-slate-500">
              Returns <b>404</b> with body “not found”. Nothing else to configure.
            </p>
            <!-- forward: nothing to fill -->
            <p v-else-if="ruleType(r) === 'forward'" class="mt-2 pl-8 text-xs text-slate-500">
              Forwards matching requests to this backend's servers.
            </p>
            <!-- respond (advanced) -->
            <div v-else-if="ruleType(r) === 'respond'" class="mt-2 grid grid-cols-2 gap-2 pl-8">
              <input v-model.number="r.status" type="number" class="input" placeholder="status (e.g. 200)" />
              <input v-model="r.content_type" class="input" placeholder="content_type (text/plain)" />
              <input v-model="r.body" class="input col-span-2" placeholder="body" />
            </div>
            <!-- redirect (advanced) -->
            <div v-else class="mt-2 grid grid-cols-2 gap-2 pl-8">
              <input v-model.number="r.status" type="number" class="input" placeholder="status (302 / 307 / 308)" />
              <input v-model="r.to" class="input" placeholder="https or absolute URL" />
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
