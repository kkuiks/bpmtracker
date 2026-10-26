# Recorded app checks and design references

The maintained application is in `../src`, `../electron`, `../backend` and
`../scripts`. Start at the [app guide](../README.md) and
[current code map](../../../docs/CODE_MAP.md).

| Area | Role |
| --- | --- |
| [audits](audits/README.md) | Recorded integration/UI checks and their fixtures; command paths were updated after relocation |
| [design-review.html](design-review.html) and [design-review](design-review/) | Workspace presentation reference, already implemented in the app |
| [remote-preview installer](remote-preview/install_remote_preview.ps1) | Earlier remote installer; current ordinary workspacesflow uses Start BPMTracker.cmd locally |
| [validation history](VALIDATION_HISTORY.md) | Dated implementation/verification claims formerly mixed into the root overview |

The source reference page is available from a manually started Vite server at
`/reference/design-review.html`. It is not a second application or an alternative editing implementation. Native map checks still used for research exports remain in
[`../audit`](../audit/README.md). Existing `.daw-state`, runtimes, installed app
caches and saved projects are preserved. No recorded test runs start from a build
or documentation read.
