const { contextBridge, ipcRenderer } = require('electron');

if (process.isMainFrame && location.protocol === 'http:') {
  contextBridge.exposeInMainWorld('julingShotPreview', {
    initialSize: ipcRenderer.sendSync('shot-preview-size:get'),
    saveSize: size => ipcRenderer.send('shot-preview-size:set', size),
  });
}
