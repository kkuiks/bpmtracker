# Contract checks

These checks cover project references, map timing, persistence, Undo/Redo, click-level compatibility, short-bar declarations and consecutive analysis jobs. They use deterministic fixtures and require no recordings or model downloads. Use Node.js 24 and Python 3.12.

From the project root in Windows PowerShell:

```powershell
$fixture = Join-Path $env:TEMP "bpmtracker-map-fixtures.json"
node apps/daw/audit/project-contract.cjs
node apps/daw/audit/job-contract.cjs
node apps/daw/audit/tempo-map-contract.cjs --output $fixture
node apps/daw/audit/signature-contract.cjs
py -3.12 apps/daw/audit/analysis-map-export-contract.py $fixture
```

The Python check compares the worker's project and original-analysis geometry against independently integrated beat times. It also checks source placement after audio events have been removed. Native Windows playback and model inference are integration checks, separate from these contracts.
