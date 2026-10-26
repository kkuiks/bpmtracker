# Frozen BPM initialization listening pack

**Historical browser preview.** Current audition uses separate native reference/current `.bpmtracker` projects. See [current development](../../docs/DEVELOPMENT.md). This retained tool does not start a server unless explicitly invoked.

Prepare local, offline listening material from the **completed and frozen**
initialization experiment. This tool renders saved accepted quarter events;
it does not run a model, fit a new clock, fill unknown spans, modify a reference,
or replace experiment predictions or scores.

The five excerpts deliberately illustrate recovery, retained output gaps,
phase error and delayed initialization. They are an explanatory selection,
not another scored cohort. Every method receives the same excerpt, music gain
and click tone/gain. Reference clicks come from the experiment's own frozen
reference snapshots, not potentially newer catalog maps. All method inputs are
the already identical `proxy_unit_zero` result, not new human taps.

Run from the checkout with `.venv-metronome-v1/bin/python`:

```sh
python -m reference.bpm_experiment_listening.prepare \
  --run data/research/runs/bpm_initialization_v1/20261010T100132Z-v1
```

Outputs go to a new directory under `data/research/listening/`. `listen.html`
embeds the manifest and uses relative WAVs with a native audio element. No
HTTP server, network call, service installation or inference is started.
`Open Listening.cmd` opens the local page on Windows. Individual mixed WAVs
also play directly; `music.wav` and the method click stems can be imported
into any current DAW at a common zero. Turn the DAW project metronome off and
keep only music plus one method stem audible.

The Nocturne stereo diagnostic places reference quarters left and saved
whole-input method quarters right using the same click pulse and actual
timestamps. It contains no music, phase correction or exaggerated delay.
This is an audible comparison, not an independent producer-clock certificate.

Native-rate excerpt cuts and click placement use nearest source sample frames.
This audio-sample rounding does not change saved predictions, and its maximum
time error is recorded. No full source audio is copied or aliased. The pack
retains source locators and event lists for inspection.
