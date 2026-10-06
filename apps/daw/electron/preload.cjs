const { contextBridge, ipcRenderer, webUtils } = require("electron");
const invoke = (name, ...args) => ipcRenderer.invoke(`joljak:${name}`, ...args);
const subscribe = (name, callback) => {
  const listener = (_event, data) => callback(data);
  ipcRenderer.on(`joljak:${name}`, listener);
  return () => ipcRenderer.removeListener(`joljak:${name}`, listener);
};
contextBridge.exposeInMainWorld("joljak", {
  kind: "electron",
  chooseAudio: () => invoke("choose-audio"),
  decode: (paths, copy, id) => invoke("decode", paths, copy, id),
  finishImport: (id, keep) => invoke("finish-import", id, keep),
  peaks: (asset) => invoke("peaks", asset.id),
  chunk: (id, index) => invoke("chunk", id, index),
  registerAssets: (assets) => invoke("register-assets", assets),
  save: (project, path, copy) => invoke("save", project, path, copy),
  open: () => invoke("open"),
  autosave: (project) => invoke("autosave", project),
  closingProject: (project) =>
    ipcRenderer.sendSync("joljak:closing-project", project),
  recovery: () => invoke("recovery"),
  analyze: (asset, start, end, tap, clipId) =>
    invoke("analyze", asset.id, start, end, tap, clipId),
  cancel: (id) => invoke("cancel", id),
  exportProject: (project, options) => invoke("export", project, options),
  onJob: (callback) => subscribe("job", callback),
  onCommand: (callback) => subscribe("command", callback),
  pathForFile: (file) => webUtils.getPathForFile(file),
  reveal: (path) => invoke("reveal", path),
  window: (action) => ipcRenderer.send("joljak:window", action),
});
