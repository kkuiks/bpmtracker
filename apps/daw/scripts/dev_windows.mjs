// Launch the real Windows app against Vite; no Linux Electron/Windows Node is required.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const powershell='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
const convert=spawn('wslpath',['-w',path.join(app,'scripts/start_windows.ps1')]);
let script='';convert.stdout.on('data',chunk=>script+=chunk);
const exit=await new Promise(resolve=>convert.on('exit',resolve));
if(exit!==0)throw new Error('Run dev:windows from this WSL checkout.');
const prepare=spawn(powershell,['-NoProfile','-ExecutionPolicy','Bypass','-File',script.trim(),'-PrepareOnly'],{stdio:'inherit'});
if(await new Promise(resolve=>prepare.on('exit',resolve))!==0)process.exit(1);
const vite=spawn(process.execPath,[path.join(app,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1'],{cwd:app,stdio:'inherit'});
let shuttingDown=false;
function shutdown(){if(shuttingDown)return;shuttingDown=true;vite.kill();}
process.on('SIGINT',shutdown);process.on('SIGTERM',shutdown);process.on('exit',shutdown);
try{
  for(let tries=0;tries<100;tries++){
    try{const response=await fetch('http://127.0.0.1:8998');if(response.ok)break;}catch{}
    if(tries===99)throw new Error('The Vite development server did not start.');
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  const desktop=spawn(powershell,['-NoProfile','-ExecutionPolicy','Bypass','-File',script.trim(),'-Source','-DevUrl','http://127.0.0.1:8998'],{stdio:'inherit'});
  if(await new Promise(resolve=>desktop.on('exit',resolve))!==0)throw new Error('Windows launch failed.');
  console.log('React/CSS changes reload in the Windows app. Restart dev:windows after Electron/Python adapter changes. Ctrl+C stops Vite.');
  await new Promise(resolve=>vite.on('exit',resolve));
}finally{shutdown();}
