const { app, BrowserWindow, dialog, shell } = require('electron');
const { execFile, spawn } = require('node:child_process');
const { existsSync, mkdirSync, createWriteStream, readFileSync, writeFileSync, renameSync, readdirSync } = require('node:fs');
const { createInterface } = require('node:readline');
const path = require('node:path');
const { promisify } = require('node:util');
const { waitFor, stopChild, startDesktopGateway } = require('./runtime.cjs');

const root = path.resolve(__dirname, '..');
const dev = process.argv.includes('--dev');
const started = performance.now();
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const children = [];
let window, log, gateway, vite, quitting = false, stopped = false;

app.setName('剧灵');
const appData = app.getPath('appData');
const profile = path.join(appData, '剧灵');
const legacyProfileName = readdirSync(appData, { withFileTypes: true })
  .find(entry => entry.isDirectory() && entry.name.startsWith('legacy-profile-'))?.name;
const legacyProfile = legacyProfileName ? path.join(appData, legacyProfileName) : null;
app.setPath('userData', !existsSync(profile) && legacyProfile ? legacyProfile : profile);

app.whenReady().then(start).catch(fail);

function launch(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], ...options,
  });
  children.push(child);
  child.stdout.pipe(log, { end: false });
  child.stderr.pipe(log, { end: false });
  child.on('error', fail);
  child.on('exit', (code, signal) => {
    if (!quitting) fail(new Error(`本地服务已退出（${code ?? signal}）。请查看 projects/runtime/desktop.log。`));
  });
  return child;
}

async function start() {
  const logDir = path.join(root, 'projects', 'runtime');
  mkdirSync(logDir, { recursive: true });
  log = createWriteStream(path.join(logDir, 'desktop.log'), { flags: 'a' });
  log.on('error', fail);
  if (!existsSync(python)) throw new Error('缺少 Python 运行环境。请运行 desktop/build.ps1。');
  const dist = path.join(root, 'frontend', 'dist');
  if (!dev && !existsSync(path.join(dist, 'index.html'))) {
    throw new Error('缺少前端构建产物。请运行 desktop/build.ps1。');
  }
  if (process.platform === 'win32') {
    const checkStarted = performance.now();
    const { stdout } = await promisify(execFile)(python, [path.join(__dirname, 'preflight.py'), String(process.pid)], {
      cwd: root, timeout: 950, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    log.write('JULING_DESKTOP_PREFLIGHT ' + stdout.trim() + ' total_ms=' + Math.round(performance.now() - checkStarted) + '\n');
  }
  if (quitting) return;
  if (!app.requestSingleInstanceLock()) return app.quit();

  window = new BrowserWindow({
    title: '剧灵', width: 1100, height: 720, minWidth: 640, minHeight: 420,
    icon: path.join(root, 'frontend', 'public', 'favicon.ico'),
    webPreferences: {
      nodeIntegration: false, contextIsolation: true, sandbox: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });
  window.removeMenu();
  const backend = launch(python, ['-u', '-X', 'juling_root=' + root, '-m', 'server.desktop'], {
    env: {
      ...process.env,
      PYTHONPATH: [path.join(root, 'backend'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      PYTHONIOENCODING: 'utf-8',
    },
  });
  const ready = new Promise((resolve, reject) => {
    const lines = createInterface({ input: backend.stdout });
    const timer = setTimeout(() => finish(new Error('本地服务启动超时。请查看 projects/runtime/desktop.log。')), 120000);
    function finish(error, url) {
      clearTimeout(timer);
      lines.close();
      backend.removeListener('error', onError);
      backend.removeListener('exit', onExit);
      error ? reject(error) : resolve(url);
    }
    const onError = error => finish(error);
    const onExit = code => finish(new Error(`本地服务启动失败（${code}）。请查看 projects/runtime/desktop.log。`));
    backend.once('error', onError);
    backend.once('exit', onExit);
    lines.on('line', line => {
      const match = /^JULING_DESKTOP_READY (http:\/\/127\.0\.0\.1:\d+)$/.exec(line);
      if (match) finish(null, match[1]);
    });
  });
  ready.then(() => {
    if (quitting) return;
    log.write('JULING_DESKTOP_BACKEND ms=' + Math.round(performance.now() - started) + '\n');
  }, fail);
  const devUrl = dev ? 'http://127.0.0.1:5173' : undefined;
  const bridge = await startDesktopGateway(dist, ready, devUrl);
  if (quitting) return bridge.close();
  gateway = bridge;
  let url = `${gateway.url}/app/projects`;
  if (devUrl) {
    vite = launch(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
      '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
      cwd: path.join(root, 'frontend'),
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', JULING_BACKEND_URL: gateway.url },
    });
    url = `${devUrl}/app/projects`;
    await window.loadFile(path.join(__dirname, 'loading.html'));
    await waitFor(devUrl, () => quitting);
  }
  if (quitting) return;
  const origin = new URL(url).origin;
  const contents = window.webContents;
  // The loopback origin changes at each launch, so renderer storage cannot restore this setting.
  const previewSizeFile = path.join(app.getPath('userData'), 'shot-preview-size');
  const validSize = size => Number.isFinite(size) && size > 0 && size < 100;
  let previewSize;
  try {
    const size = Number(readFileSync(previewSizeFile, 'utf8'));
    if (validSize(size)) previewSize = size;
  } catch (error) {
    if (error.code !== 'ENOENT') log.write(`Failed to read shot preview size: ${error.message}\n`);
  }
  const isAppFrame = event => event.senderFrame === contents.mainFrame &&
    event.senderFrame?.url.startsWith(`${origin}/`);
  contents.ipc.on('shot-preview-size:get', event => {
    event.returnValue = isAppFrame(event) ? previewSize : undefined;
  });
  contents.ipc.on('shot-preview-size:set', (event, size) => {
    if (!isAppFrame(event) || !validSize(size) || size === previewSize) return;
    try {
      const temp = `${previewSizeFile}.tmp`;
      writeFileSync(temp, String(size));
      renameSync(temp, previewSizeFile);
      previewSize = size;
    } catch (error) {
      log.write(`Failed to save shot preview size: ${error.message}\n`);
    }
  });
  window.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/.test(target)) shell.openExternal(target).catch(fail);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, target) => {
    if (new URL(target).origin !== origin) event.preventDefault();
  });
  await window.loadURL(url);
  log.write(`JULING_DESKTOP_WINDOW_READY ${url}\n`);
  log.write('JULING_DESKTOP_STARTUP ms=' + Math.round(performance.now() - started) + '\n');
}

function fail(error) {
  if (quitting) return;
  log?.write(`${error.stack || error}\n`);
  dialog.showErrorBox('剧灵 启动或运行失败', error.message);
  app.quit();
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (stopped) return;
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  gateway?.close();
  Promise.all(children.map(child => stopChild(child, child === vite ? 0 : undefined))).finally(() => {
    stopped = true;
    log?.end();
    app.quit();
  });
});
