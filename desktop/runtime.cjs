const http = require('node:http');
const { spawn } = require('node:child_process');
const { createReadStream, promises: fs } = require('node:fs');
const path = require('node:path');

function waitFor(url, cancelled = () => false, timeout = 60000) {
  const deadline = Date.now() + timeout;
  return new Promise((resolve, reject) => {
    function attempt() {
      if (cancelled()) return reject(new Error('启动已取消。'));
      if (Date.now() >= deadline) return reject(new Error(`启动超时：${url}`));
      const request = http.get(url, response => {
        response.resume();
        if (response.statusCode === 200) resolve();
        else setTimeout(attempt, 200);
      });
      request.on('error', () => setTimeout(attempt, 200));
      request.setTimeout(1000, () => request.destroy());
    }
    attempt();
  });
}

function stopChild(child, timeout = 15000) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise(resolve => {
    const timer = setTimeout(() => {
      if (process.platform === 'win32') {
        const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
        killer.on('error', () => child.kill());
      } else child.kill('SIGKILL');
    }, timeout);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
    if (child.stdin && !child.stdin.destroyed) {
      child.stdin.on('error', () => {});
      child.stdin.end();
    } else child.kill();
  });
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.woff': 'font/woff', '.woff2': 'font/woff2',
};

async function serveFrontend(directory, pathname, request, response) {
  if (!['GET', 'HEAD'].includes(request.method)) return response.writeHead(405).end();
  const local = path.resolve(directory, pathname === '/' ? './index.html' : '.' + pathname);
  if (/[:\\\0]/.test(pathname) || !local.startsWith(directory + path.sep)) return response.writeHead(404).end();
  let file = await fs.realpath(local).catch(error => {
    if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error;
    return null;
  });
  if (file && !file.startsWith(directory + path.sep)) return response.writeHead(404).end();
  if (!file || !(await fs.stat(file)).isFile()) {
    if (!/^\/(?:$|login$|app(?:\/|$))/.test(pathname)) return response.writeHead(404).end();
    // The build's index is the only fallback. Static assets must never return HTML.
    file = path.join(directory, 'index.html');
  }
  response.writeHead(200, {
    'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
    'Cache-Control': pathname.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  if (request.method === 'HEAD') return response.end();
  const stream = createReadStream(file);
  response.once('close', () => stream.destroy());
  stream.on('error', error => response.destroy(error)).pipe(response);
}

function forward(backend, request, response) {
  const upstream = http.request(backend, { path: request.url, method: request.method, headers: {
    ...request.headers, connection: 'close',
  } }, message => {
    response.writeHead(message.statusCode, message.headers);
    message.on('error', error => response.destroy(error)).pipe(response);
  });
  response.once('close', () => upstream.destroy());
  upstream.on('error', () => {
    if (response.destroyed) return;
    if (response.headersSent) response.destroy();
    else response.writeHead(502).end();
  });
  request.pipe(upstream);
}

// Serve the actual project lobby before Python finishes importing and migrating data.
async function startDesktopGateway(directory, ready, devOrigin) {
  const dist = devOrigin ? null : await fs.realpath(directory);
  let backend;
  ready.then(url => { backend = url; }, () => {});
  const server = http.createServer(async (request, response) => {
    if (request.headers.host !== address.host || (request.headers.origin &&
      request.headers.origin !== address.origin && request.headers.origin !== devOrigin)) {
      return response.writeHead(403).end();
    }
    if (!request.url?.startsWith('/') || request.url.startsWith('//')) return response.writeHead(400).end();
    try {
      const pathname = decodeURIComponent(new URL(request.url, address).pathname);
      if (!backend && pathname === '/api/v1/auth/status' && request.method === 'GET') {
        // server.desktop forces authentication off for its private loopback server.
        return response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
          .end('{"enabled":false}');
      }
      if (!backend && dist && !/^\/(?:api|mcp)(?:\/|$)/.test(pathname)) {
        return await serveFrontend(dist, pathname, request, response);
      }
      const target = backend ?? await ready;
      if (!response.destroyed) forward(target, request, response);
    } catch (error) {
      if (response.destroyed) return;
      if (response.headersSent) response.destroy();
      else response.writeHead(error instanceof URIError ? 400 : 503).end();
    }
  });
  const address = await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(new URL(`http://127.0.0.1:${server.address().port}`)));
  });
  return { url: address.origin, close() { server.close(); server.closeAllConnections(); } };
}

module.exports = { waitFor, stopChild, startDesktopGateway };
