# Repository status and static audit

Use the status command to locate the selected baseline, app and next objective:

```bash
python3 tools/repository/status.py
```

It reads the canonical root `project-state.json` and app package version. It
does not run inference, tests, servers, Git writes or data changes.

For an explicitly requested repository audit:

```bash
python3 tools/repository/audit.py --output data/storage/<new-audit>/final
```

The audit records complete checkout file metadata without following external
symlinks, checks owned source syntax/import paths and maintained Markdown links,
and compares recorded baseline source hashes. It does not decode or hash media,
execute algorithm imports/models, run runtime tests, change old freezes, stage
source, or delete files. `--exclude` can omit the audit's own parent receipt
when comparing a task's before/after inventories.

Source organization is documented in [CODE_MAP.md](../../docs/CODE_MAP.md).
The current cleanup's full evidence is local at
`data/storage/20261013-repository-organization-v1/`.

## Private data checkpoints

The owner-authorized private repository `kkuiks/joljak-data` is connected at
the existing checkout-local `data/` path. Source Git continues to ignore it.
Compact maps/drafts/reports use an exact metadata allowlist; big frozen evidence
uses private release attachments. Original songs, audio distribution archives,
credentials and dependency/playback caches are excluded.

For an explicitly requested backup, use an explicitly requested durability
inventory and a new checkpoint ID:

```bash
python3 tools/repository/private_data.py prepare --audit <inventory-and-proposal.json> --checkpoint <new-id>
python3 tools/repository/private_data.py package --checkpoint <new-id>
python3 tools/repository/private_data.py git-paths --checkpoint <new-id>
```

Review `selection.json`, `coverage.json` and the exact `git-paths.bin` before
publication. These commands prepare bytes and paths only: they do not create
repositories, upload, stage/commit source, schedule backups or infer new results.
Existing checkpoint archives are immutable. Credential-bearing acquisition
records get clearly marked sanitized backup copies; original local records
and frozen scientific outputs remain untouched.

Publish only reviewed child-repository paths on `main` and verify private
visibility, the remote commit and each release asset digest. Always assert
`git -C data rev-parse --show-toplevel` equals this checkout's `data/` before
Git mutations. See `data/README.md` for authenticated download and restoration;
the default restore never replaces a differing existing file.
