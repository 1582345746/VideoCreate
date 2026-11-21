let csrf = ''
let configId = ''
export function stateKey(key: string) {
  if (!configId) throw new Error('尚未确认当前配置身份，请重新打开配置页面。')
  return key + ':' + configId
}
export async function request(path: string, body?: unknown): Promise<any> {
  const response = await fetch('/api/' + path, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'X-VC-Client': '1', ...(configId ? {'X-VC-Config': configId} : {}),
      ...(body === undefined ? {} : { 'Content-Type': 'application/json', 'X-VC-CSRF': csrf }) },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  const data = await response.json()
  if (!response.ok) throw Object.assign(new Error(data.error?.message || '读取失败，请重试。'), data.error, {status: response.status})
  return data
}
export async function session() {
  let data
  try { data = await request('session') }
  catch (e: any) {
    if (e.status !== 401) throw e
    const bootstrap = await fetch('/', {cache: 'no-store', credentials: 'same-origin'})
    if (!bootstrap.ok) throw new Error('配置页面无法重新连接，请通过启动器重新打开。')
    data = await request('session')
  }
  if (typeof data.config_id !== 'string' || !/^[a-f0-9]{64}$/.test(data.config_id))
    throw new Error('配置服务未提供可验证的配置身份，请重新启动当前候选服务。')
  if (configId && configId !== data.config_id)
    throw new Error('当前端口已打开另一份配置，请重新打开页面后核对配置位置；原输入和记录保留。')
  configId = data.config_id; csrf = data.csrf_token
  return data
}
