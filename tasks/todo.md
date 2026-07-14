# Todo: Codebase-review fixes (see tasks/plan.md for details)

## Phase 1: Hardware-correctness fixes
- [x] Task 1: Resolve analog-LUT focal-power type code in `IccChannel.configure_analog_input`
      (manual + web search had no register codes; used 1 per SDK SetLUTtype docstring, flagged in README)
- [x] Task 2: Raise `LensCommandError` on nonzero device error codes (breaking API change)
- [x] Checkpoint 1: full test suite green (34 passed), one commit per task

## Phase 2: API safety and numeric polish
- [x] Task 3: `temp_limits` constructor parameter for `Lens.__init__`
- [x] Task 4: `round()` instead of `int()` in raw conversions
- [x] Checkpoint 2: suite green (36 passed); both example scripts fail only with connection errors

## Phase 3: Tests and docs polish
- [x] Task 5: Tests for `Lens.get_current`/`get_diopter`; remove dead MockSerial branch
- [x] Task 6: Docstring/README gaps + version bump to 0.2.0
- [x] Checkpoint 3: suite green (38 passed); README matches signatures; todo all checked

## Outstanding (needs hardware)
- Verify analog-input LUT type code 1 for focal power on a real ICC controller
  (see README hardware note) — first time `configure_analog_input(unit='focal_power')` is used.
