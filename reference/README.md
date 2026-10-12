# Previous studies and completed operations

This is the readable reference area for completed studies that are not the
current variable development entry. The current standard is
[`algorithms/variable`](../algorithms/README.md), with status in
[`project-state.json`](../project-state.json).

| Study | Purpose and limitation |
| --- | --- |
| [variable_tempo_step0](variable_tempo_step0/README.md) | Earlier candidate survival/localization investigation; its old recursion gate is historical |
| [bpm_continuity_v1](bpm_continuity_v1/README.md) | Initial fixed-clock continuity study |
| [bpm_initialization_v1](bpm_initialization_v1/README.md) | Initial-map ablations under earlier assumptions |
| [metrical_clock_roles_v1](metrical_clock_roles_v1/README.md) | Joint pulse/meter role interpretation study |
| [audio_metrical_discriminator_v1](audio_metrical_discriminator_v1/README.md) | Conditional original-audio metrical discrimination; not the selected L2 model |
| [octave_fold_confirmation_v1](octave_fold_confirmation_v1/README.md) | Earlier half/double correction checks |
| [clock_continuation_repair_v1](clock_continuation_repair_v1/README.md) | Click preservation under disconnected segment clocks, before the continuous-map redesign |
| [bpm_experiment_listening](bpm_experiment_listening/README.md) | Recorded browser listening artifacts/launcher; ordinary native `.joljak` audition is current |
| [sample_operations](sample_operations/README.md) | Completed dated confirmation, enrollment and offset-audit scripts |

All seven study packages moved at the same directory depth, preserving their
workspace-root calculations and original Python source. `experiments.__path__`
explicitly exposes them for historical imports used by retained scripts. This
is a Python import bridge; the source has one physical home.

Recorded protocols, original source hashes and results are immutable. A
historical hash guard can still reject a relocated live source tree: use that
run's original `code-snapshot` or the preserved source-before snapshot in
`data/storage/20261013-repository-organization-v1/`. Do not change a frozen hash
or reference to bypass this boundary. These old drivers are reference material,
not commands to automatically rerun.

The [relocation catalog](catalog.json) gives exact old/new source paths. Raw
predictions, recordings, accepted maps, native project geometry, runtimes and
owner edits were not moved or deleted. Application UI checks and design material
have their own [reference area](../apps/daw/reference/README.md).
