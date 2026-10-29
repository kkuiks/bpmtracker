const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');

// Exercise the real worker controller and analyze IPC handler with a worker
// whose output finishes before its operating-system process exits.
const main = fs.readFileSync(process.argv[2] || path.join(__dirname, '../electron/main.cjs'), 'utf8');
const workerSource = main.slice(main.indexOf('async function startJob('), main.indexOf('\napp.whenReady()'));
const ipcStart = main.indexOf('ipcMain.handle(\n  "bpmtracker:analyze",');
const analyzeSource = main.slice(ipcStart, main.indexOf('ipcMain.handle("bpmtracker:cancel"', ipcStart));

(async () => {
  const jobs = new Map(), workers = [], handlers = new Map();
  let serial = 0, atResult;
  const context = {
    fs: { access: async () => {} }, path,
    python: 'python', worker: 'worker', analysisRoot: 'analysis',
    dataRoot: 'isolated', checkpoint: 'model', quitting: false,
    process: { env: {} }, randomUUID: () => `job-${++serial}`,
    atomicJson: async () => {},
    requireAsset: () => ({ id: 'song', duration: 10 }),
    spawn: () => {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      workers.push(child);
      return child;
    },
    jobs, imports: new Map(), assets: new Map(),
    readline: require('node:readline'),
    send: (_name, message) => {
      if (['complete', 'failed'].includes(message.stage)) atResult?.();
    },
    finishImport: async () => {}, scheduleCacheCleanup: () => {},
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
  };
  vm.runInNewContext(workerSource + '\n' + analyzeSource, context);
  const analyze = () => handlers.get('bpmtracker:analyze')({}, 'song', 0, 10, 120, 'event');
  const first = await analyze();
  await assert.rejects(analyze(), /One analysis can run at a time/);

  let nextRequest;
  atResult = () => { nextRequest = analyze(); };
  workers[0].stdout.write(JSON.stringify({ stage: 'complete', result: { status: 'needs_initial_unit' } }) + '\n');
  const second = await nextRequest;
  assert.notEqual(second, first);
  assert.ok(jobs.has(first), 'Completed processes remain tracked until exit');
  workers[0].emit('close', 0);
  assert.ok(!jobs.has(first) && jobs.has(second));

  workers[1].stdout.write(JSON.stringify({ stage: 'failed', error: 'Unusable source' }) + '\n');
  const retry = await nextRequest;
  assert.notEqual(retry, second);
  workers[1].emit('close', 1);
  assert.ok(!jobs.has(second) && jobs.has(retry));
  await assert.rejects(analyze(), /One analysis can run at a time/);
  atResult = null;
  workers[2].emit('close', 1);
  assert.equal(jobs.size, 0);
  console.log('Worker handoff: active exclusion, immediate confirm, immediate retry and exit cleanup passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
