import { createReadStream } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'

const root = join(process.cwd(), 'e2e', 'fixtures')
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8' }

createServer((request, response) => {
  const requested = decodeURIComponent(new URL(request.url ?? '/', 'http://127.0.0.1').pathname)
  const relative = normalize(requested).replace(/^([/\\])+/, '')
  const file = join(root, relative || 'embed-host-basic.html')
  if (!file.startsWith(root)) {
    response.writeHead(403).end()
    return
  }
  response.setHeader('Content-Type', types[extname(file)] ?? 'application/octet-stream')
  const stream = createReadStream(file)
  stream.on('error', () => response.writeHead(404).end())
  stream.pipe(response)
}).listen(4174, '127.0.0.1')
