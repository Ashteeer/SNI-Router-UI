// Thin fetch wrapper. Cookies carry the session, so credentials: 'include'.
async function req(method, path, body, raw = false) {
  const opts = { method, credentials: 'include', headers: {} }
  if (body !== undefined) {
    if (raw) {
      opts.headers['Content-Type'] = 'text/plain'
      opts.body = body
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  const r = await fetch('/api' + path, opts)
  const ct = r.headers.get('content-type') || ''
  const data = ct.includes('application/json') ? await r.json() : await r.text()
  if (!r.ok) {
    const msg = typeof data === 'object' ? data.detail || JSON.stringify(data) : data
    throw Object.assign(new Error(msg || r.statusText), { status: r.status, data })
  }
  return data
}

export const api = {
  me: () => req('GET', '/me'),
  setup: (d) => req('POST', '/setup', d),
  login: (d) => req('POST', '/login', d),
  logout: () => req('POST', '/logout'),
  getSettings: () => req('GET', '/settings'),
  putSettings: (d) => req('PUT', '/settings', d),

  // local site config (Settings tab)
  getLocalConfig: () => req('GET', '/config'),
  putLocalConfig: (values) => req('PUT', '/config', { values }),

  // discover a sni-router config on the UI host (Add Host convenience)
  discoverLocal: () => req('GET', '/config/discover'),

  // remote provisioning over SSH (clean install of agent and/or sni-router)
  provision: (d) => req('POST', '/provision', d),

  hosts: () => req('GET', '/hosts'),
  addHost: (d) => req('POST', '/hosts', d),
  updateHost: (id, d) => req('PUT', '/hosts/' + id, d),
  deleteHost: (id) => req('DELETE', '/hosts/' + id),
  deleteHosts: (ids) => req('POST', '/hosts/delete', { ids }),

  // version + self-update
  version: () => req('GET', '/version'),
  updateUi: () => req('POST', '/update/ui'),
  agentInfo: (id) => req('GET', `/hosts/${id}/agent`),
  updateAgent: (id) => req('POST', `/hosts/${id}/agent-update`),

  status: (id) => req('GET', `/hosts/${id}/status`),
  live: (id) => req('GET', `/hosts/${id}/live`),
  history: (id, range) => req('GET', `/hosts/${id}/history?range=${range}`),

  getConfig: (id) => req('GET', `/hosts/${id}/config`),
  putConfig: (id, yaml) => req('PUT', `/hosts/${id}/config`, yaml, true),
  reload: (id) => req('POST', `/hosts/${id}/reload`),
  restart: (id) => req('POST', `/hosts/${id}/restart`),
}
