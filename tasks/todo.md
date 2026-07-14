# Todo: Codebase-review fixes (see tasks/plan.md for details)

## Phase 1: Hardware-correctness fixes
- [x] Task 1: Resolve analog-LUT focal-power type code in `IccChannel.configure_analog_input`
      (manual + web search had no register codes; used 1 per SDK SetLUTtype docstring, flagged in README)
- [ ] Task 2: Raise `LensCommandError` on nonzero device error codes (breaking API change)
- [ ] Checkpoint 1: full test suite green, one commit per task

## Phase 2: API safety and numeric polish
- [ ] Task 3: `temp_limits` constructor parameter for `Lens.__init__`
- [ ] Task 4: `round()` instead of `int()` in raw conversions
- [ ] Checkpoint 2: suite green; example.py fails only with connection error

## Phase 3: Tests and docs polish
- [ ] Task 5: Tests for `Lens.get_current`/`get_diopter`; remove dead MockSerial branch
- [ ] Task 6: Docstring/README gaps + version bump to 0.2.0
- [ ] Checkpoint 3: suite green; README matches signatures; todo all checked
