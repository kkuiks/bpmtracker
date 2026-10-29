/* Render the vector app mark with Electron and write Windows icon sizes. */
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const folder = path.resolve(__dirname, '../public');
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.whenReady().then(async () => {
  const window = new BrowserWindow({ width: 256, height: 256, show: false, frame: false,
    transparent: true, webPreferences: { contextIsolation: true, sandbox: true, offscreen: true, backgroundThrottling: false } });
  const vector = fs.readFileSync(path.join(folder, 'app-icon.svg'), 'utf8');
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
    '<style>html,body{margin:0;width:100%;height:100%;overflow:hidden}svg{width:100%;height:100%;display:block}</style>'+vector));
  const sizes = [16, 24, 32, 48, 64, 128, 256], images = [];
  for (const size of sizes) {
    window.setContentSize(size, size);
    await new Promise(resolve => setTimeout(resolve, 60));
    const image = await window.webContents.capturePage({ x: 0, y: 0, width: size, height: size });
    const data = image.toPNG();
    if (size === 256) fs.writeFileSync(path.join(folder, 'app-icon.png'), data);
    images.push({ size, data });
  }
  const header = Buffer.alloc(6 + images.length * 16);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, index) => {
    const at = 6 + index * 16;
    header[at] = header[at + 1] = size === 256 ? 0 : size;
    header.writeUInt16LE(1, at + 4); header.writeUInt16LE(32, at + 6);
    header.writeUInt32LE(data.length, at + 8); header.writeUInt32LE(offset, at + 12); offset += data.length;
  });
  fs.writeFileSync(path.join(folder, 'app-icon.ico'), Buffer.concat([header, ...images.map(image => image.data)]));
  app.quit();
}).catch(error => { console.error(error); app.exit(1); });
