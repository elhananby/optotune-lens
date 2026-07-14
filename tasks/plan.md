# Implementation Plan: Fix Codebase-Review Findings in optotune-lens

## Context

A full codebase review (this session) found no critical bugs but six issues worth fixing, ranging
from a likely-wrong hardware constant to missing tests. The user approved fixing all of them,
including the breaking API change for error handling ("raise everywhere"). The ICC-1C datasheet
(`~/Downloads/OptotuneICC-1Cdatasheet.pdf`) was checked: it confirms analog input maps to Current
or Focal power but defers register codes to the separate ICC-1C software manual, so finding 1
still needs an online check during implementation.

Findings being fixed, most → least critical:
1. `configure_analog_input` maps `'focal_power'` to LUT type `3`, but the vendored SDK docstring
   (`optoKummenberg/registers/InputStage.py:257`) says `0 = current, 1 = focal power`.
2. Device error codes handled inconsistently — returned by `set_temperature_limits`/`eeprom_write_byte`,
   only warned about in `to_focal_power_mode`; never raised.
3. `Lens.__init__` silently writes temperature limits (20–40 °C) to the device on connect.
4. `int()` truncation in raw conversions loses one LSB for ~3% of diopter values.
5. Missing tests for `Lens.get_current` / `Lens.get_diopter`; dead branch in `MockSerial.write`.
6. Doc gaps: `IccChannel.set_current` generic-range caveat, `IccLens.connect` auto-discovery
   limitation (hwid `0483:A31E`), pip-vs-uv packaging note.

## Decisions (already made with user)

- **Error policy**: nonzero device error code → raise `LensCommandError`, uniformly.
  Breaking changes accepted: `set_temperature_limits` returns `(min_diopter, max_diopter)`;
  `eeprom_write_byte` returns `None`. Bump version to 0.2.0.
- **LUT type**: web-search Optotune ICC manual/example code first; if inconclusive, trust the
  vendor docstring (use `1`) and document the source + residual uncertainty in code and README.
- Init temperature limits become a constructor parameter with the current values as default
  (behavior-preserving).
- Workflow per user's global rules: `uv run pytest` for verification, one commit per task,
  clear messages, no Co-Authored-By.

## Task List

First step after approval: save this plan to `tasks/plan.md` and the checklist to `tasks/todo.md`
(requested by the /plan command), and commit them with the first task.

### Phase 1: Hardware-correctness fixes (most critical)

#### Task 1: Resolve the analog-LUT focal-power type code (finding 1)
**Description:** Determine the correct `LUTinputType` value for focal power and fix
`IccChannel.configure_analog_input`.
**Steps:** Web-search Optotune ICC-4C/ICC-1C manual + public example code for `SetLUTtype`.
If inconclusive, use `1` per the vendor docstring. Add a code comment citing the source; extend
the README hardware note to say the value should be confirmed when ICC hardware is available.
**Acceptance criteria:**
- [ ] `lut_types` mapping in `src/optotune_lens/icc.py` reflects the best available source, with a comment naming that source
- [ ] `tests/test_icc.py::test_configure_analog_input` pins the new value
- [ ] README hardware note mentions the outstanding hardware verification
**Verification:** `uv run pytest` green.
**Dependencies:** None. **Files:** `icc.py`, `tests/test_icc.py`, `README.md`. **Size:** S

#### Task 2: Uniform error policy — raise `LensCommandError` on nonzero device codes (finding 2)
**Description:** In `src/optotune_lens/lens.py`, make `set_temperature_limits`,
`to_focal_power_mode`, and `eeprom_write_byte` raise `LensCommandError` when the device reports a
nonzero error code. New signatures: `set_temperature_limits -> Tuple[float, float]` (min, max);
`eeprom_write_byte -> None`. Update all callers: `example.py`, README quick start + API docs,
and `__init__` docstring (a nonzero code during init now surfaces as `LensCommandError`).
**Acceptance criteria:**
- [ ] All three methods raise `LensCommandError` on nonzero error code, message includes the code
- [ ] Existing tests updated to new return shapes; new tests cover the nonzero-error path for each of the three methods (via `MockSerial` responses with nonzero error bytes)
- [ ] `example.py` and README show the new signatures
**Verification:** `uv run pytest` green.
**Dependencies:** None. **Files:** `lens.py`, `tests/test_lens.py`, `example.py`, `README.md`. **Size:** M

**Checkpoint 1:** `uv run pytest` fully green; both tasks committed separately.

### Phase 2: API safety and numeric polish

#### Task 3: Make init temperature limits an explicit constructor parameter (finding 3)
**Description:** Add `temp_limits: Tuple[float, float] = (20.0, 40.0)` to `Lens.__init__`; pass it
to the existing `set_temperature_limits` call. Document in the class and `__init__` docstrings
that connecting writes these limits to the device (required to learn diopter bounds).
**Acceptance criteria:**
- [ ] `Lens(port, temp_limits=(20.0, 45.0))` sends the custom limits (test via `MockSerial`, which already has a 20/45 response registered)
- [ ] Default behavior unchanged (existing tests pass untouched)
- [ ] Side effect documented in docstrings and README
**Verification:** `uv run pytest` green.
**Dependencies:** Task 2 (touches the same method's call site). **Files:** `lens.py`, `tests/test_lens.py`, `README.md`. **Size:** S

#### Task 4: Replace `int()` truncation with `round()` in raw conversions (finding 4)
**Description:** Use `round()` in `_diopter_to_raw` (lens.py:332), `set_current` raw computation
(lens.py:358), and the temperature packing in `set_temperature_limits` (lens.py:314).
**Acceptance criteria:**
- [ ] Regression test: on a connected mock lens (firmware type 'A'), `lens._diopter_to_raw(-4.995) == 1` (truncation gave 0)
- [ ] Existing conversion-dependent tests still pass
**Verification:** `uv run pytest` green.
**Dependencies:** Task 2 (same file/method). **Files:** `lens.py`, `tests/test_lens.py`. **Size:** XS

**Checkpoint 2:** `uv run pytest` green; `uv run python example.py` fails only with a
connection error (no hardware), not a TypeError/AttributeError.

### Phase 3: Test coverage and documentation polish (least critical)

#### Task 5: Add missing `Lens.get_current` / `get_diopter` tests; remove dead mock branch (finding 5)
**Description:** Register `b'Ar\x00\x00'` and `b'PrDA\x00\x00\x00\x00'` responses in `MockSerial`
with known raw values; assert the scaled results (current: `raw * max_current / 4095`; diopter:
type-'A' `raw/200 - 5`). Delete the unreachable `payload == b"Start"` branch at
`tests/test_lens.py:129`.
**Acceptance criteria:**
- [ ] New tests exercise both getters' scaling arithmetic
- [ ] Dead branch removed; suite still green
**Verification:** `uv run pytest` green.
**Dependencies:** None. **Files:** `tests/test_lens.py`. **Size:** S

#### Task 6: Documentation gaps + version bump (finding 6)
**Description:** (a) `IccChannel.set_current` docstring: note validation is against the generic
±2 A register range, not lens- or board-specific limits (ICC-1C hardware caps at ±500 mA per
datasheet). (b) `IccLens.connect` docstring: auto-discovery matches USB hwid `0483:A31E`
(ICC-4C id, same as vendor SDK); recommend explicit `port=` for other boards. (c) README:
note that installation requires uv (vendored wheels resolve via `[tool.uv.sources]`; plain
`pip install .` won't find `optoicc`/`optokummenberg`). (d) Bump version to 0.2.0 in
`pyproject.toml` and `src/optotune_lens/__init__.py` (breaking change from Task 2).
**Acceptance criteria:**
- [ ] All four items present; version strings agree
**Verification:** `uv run pytest` green; `uv sync --extra dev` still resolves.
**Dependencies:** Task 2 (version bump rationale). **Files:** `icc.py`, `README.md`, `pyproject.toml`, `__init__.py`. **Size:** S

**Checkpoint 3 (final):** full suite green; README examples match actual signatures;
`git log` shows one clear commit per task; `tasks/todo.md` all checked off.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LUT type still unverifiable online | Med | Cite source in code; README flags it for first hardware test; value `1` comes from the SDK's own docs |
| Breaking API change surprises future scripts | Low | Version bump to 0.2.0; README + example.py updated in the same commits |
| MockSerial changes ripple into unrelated tests | Low | Run full suite after every task; one commit per task makes bisecting trivial |

## Verification (end-to-end)

- `uv run pytest` after every task (all 31 existing + new tests).
- `uv run python example.py` and `uv run python examples/icc1c_example.py` must fail only with
  connection errors (no hardware attached), proving no import/signature breakage.
- Hardware smoke test on the available Lens Driver 4 (`/dev/optotune_ld`) is possible for the
  `Lens` changes if the user wants it; ICC path remains fake-board-only until hardware arrives.
