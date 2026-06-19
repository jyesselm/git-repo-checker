# Implementation Plan: auto-track, auto-sync schedule, refactor

This plan is self-contained. Implement it exactly. The project is `git-repo-checker`
(console scripts `grc` and `git-repo-checker` -> `git_repo_checker.cli:app`). Stack:
typer / rich / pydantic v2 / pyyaml. Python 3.11+. Layered modules live in
`src/git_repo_checker/`. Tests in `tests/`.

## Critical constraints (restated — do not violate)
- Toolchain MUST pass: `ruff check --fix .`, `ruff format .`, `mypy src/`,
  `pytest --cov-fail-under=90`. Ruff rules include pydocstyle **google** convention and
  **mccabe max-complexity = 10**. Every function needs full type hints + a google-style
  docstring (Args/Returns/Raises as applicable). Keep cyclomatic complexity <= 10 and
  nesting depth <= 3; prefer <= 4 params (group into a dataclass/model otherwise).
- Preserve EVERY existing feature: CI status via `gh` (`--ci`), `--json` output,
  `--status` filtering, `--dry-run` sync, per-machine `--path-prefix` overrides and
  `local.yml`, `--merge` behavior, parallel workers (`-j/--workers`), URL fetch
  (`--repos-url`), `--init` for repos file.
- Follow the existing layered structure; do NOT collapse modules. New schedule logic goes
  in a NEW module `schedule.py`, not crammed into cli.py or sync.py.
- macOS / launchd only (platform is darwin). Use a LaunchAgent plist in
  `~/Library/LaunchAgents` and `launchctl` for load/unload.

---

## Decisions (final — implement these, do not re-open)

1. **Auto-track default = ON.** `scan` automatically appends newly-discovered repos that
   have a remote into the tracked repos.yml. Disable per-invocation with a new
   `--no-track` flag. Disable globally via config (`auto_track.enabled: false`).
2. **`--export-repos` is KEPT as an explicit override flag**, not removed. When given, it
   targets that specific file path (back-compat). When NOT given, auto-track writes to the
   resolved default repos.yml. Rationale: removing it would break existing scripts/docs;
   it now simply means "track into THIS file" and is otherwise redundant with the new
   automatic behavior. (No `--merge`-required friction for auto-track: auto-track always
   merges safely and never raises FileExistsError; `--export-repos` keeps its current
   merge semantics for back-compat.)
3. **scan_errors: WIRE IT UP** (do not delete). It is already plumbed through `models`,
   `analyzer`, `cli` JSON output, and `_filter_by_status`. The only gap is that
   `scanner.scan_directory` silently swallows `PermissionError`/`OSError`. Capture those as
   human-readable strings and surface them in JSON and the reporter. This is less code
   churn than ripping the field out of 3 layers and is a real feature.
4. **Rename for clarity (refactor a):** rename `sync.clone_repo` ->
   `sync.clone_tracked_repo`. Keep `git_ops.clone_repo` as-is (it is the low-level
   primitive; the sync-layer wrapper is the one that needs disambiguation). Update all
   call sites and tests.
5. **Schedule CLI surface:** a new Typer sub-app `schedule` with three subcommands:
   `grc schedule install`, `grc schedule uninstall`, `grc schedule status`.

---

## Backward-compatibility notes (call out in PR description)
- `grc scan` now WRITES to repos.yml by default (auto-track). This is a behavior change.
  Mitigations: it only ever ADDS new entries, never edits/removes existing ones; skips
  repos without a remote; never overwrites the file destructively; `--no-track` and
  `auto_track.enabled: false` disable it. Document this in README.
- `--export-repos` still works but is now an explicit-target alias of auto-track.
- `sync.clone_repo` is renamed; any external importer must update. Internal only here.

---

## File-by-file changes

### 1. `src/git_repo_checker/models.py`  (edit)
Add an `AutoTrackConfig` model and wire it into `Config`. Keep models small.

- Add:
  ```python
  class AutoTrackConfig(BaseModel):
      """Configuration for automatic repo tracking during scan."""

      enabled: bool = True
      repos_file: str | None = None   # explicit default target; None -> resolve normally
      path_prefix: str = "~"
  ```
- Add field to `Config`:
  ```python
  auto_track: AutoTrackConfig = Field(default_factory=AutoTrackConfig)
  ```
- Keep `ScanResult.scan_errors` exactly as-is (already present).
- No change to `TrackedRepo`, `SyncResult`, etc.

### 2. `src/git_repo_checker/config.py`  (edit)
- Import `AutoTrackConfig`.
- In `DEFAULT_CONFIG_TEMPLATE`, add a commented block after `auto_pull`:
  ```yaml
  # Auto-track: append newly-found repos (with a remote) to repos.yml during scan
  auto_track:
    enabled: true
    # repos_file: ~/.config/git-repo-checker/repos.yml  # optional explicit target
    path_prefix: ~
  ```
- In `parse_raw_config`: read `auto_track_raw = raw.get("auto_track", {})` and pass
  `auto_track=AutoTrackConfig(**auto_track_raw)` to `Config(...)`.
- In `expand_paths`: carry `auto_track=config.auto_track` through (it has no Path fields, so
  just forward it). Keep function complexity low — it is a flat constructor call.

### 3. `src/git_repo_checker/scanner.py`  (edit — wire up scan_errors)
Change the scan to collect permission/OS errors instead of silently swallowing them, while
preserving the existing `find_git_repos` Iterator API for any other caller.

- Add a small result container at top of module (use a dataclass, not pydantic, to keep the
  scanner dependency-free):
  ```python
  from dataclasses import dataclass, field

  @dataclass
  class ScanWalkResult:
      """Repos found plus directories that could not be scanned."""

      repos: list[Path] = field(default_factory=list)
      errors: list[str] = field(default_factory=list)
  ```
- Add a NEW top-level function `walk_git_repos(...)` that returns `ScanWalkResult` and is
  the error-collecting variant. Signature mirrors `find_git_repos`:
  ```python
  def walk_git_repos(
      scan_paths: list[Path],
      exclude_patterns: list[str],
      exclude_paths: list[Path],
  ) -> ScanWalkResult:
  ```
  It walks the same way but records a string like
  `f"Permission denied: {path}"` (or `f"Cannot scan {path}: {exc}"`) whenever a
  `PermissionError`/`OSError` is hit on `stat()` or `iterdir()`.
- Refactor the recursion so error capture lives in ONE place. Implement an internal helper
  `_walk(root, ctx, depth, result)` where `ctx` is a small dataclass bundling
  `exclude_patterns`, `exclude_paths`, `visited` (group params to stay <= 4 and keep
  complexity <= 10). Suggested:
  ```python
  @dataclass
  class _WalkContext:
      exclude_patterns: list[str]
      exclude_paths: set[Path]
      visited: set[int]
  ```
  - On `stat()` failure: append error, return.
  - On `iterdir()` failure: append error, return.
  - Found `.git`: append to `result.repos`, return (do not descend).
  Keep the depth/symlink-loop guards (`MAX_DEPTH`, visited inodes) intact.
- KEEP the existing `find_git_repos` and `scan_directory` working. Simplest approach that
  avoids duplication: reimplement `find_git_repos` as a thin generator that calls
  `walk_git_repos` and yields `result.repos` (drops errors), so the analyzer can switch to
  `walk_git_repos` and other callers stay valid. If reusing is awkward under the complexity
  cap, you may instead delete `scan_directory`/`find_git_repos` and update the one caller
  (`analyzer.scan_and_analyze`) — grep shows the only internal callers are the analyzer and
  tests. Decision: PREFER to keep `find_git_repos` as a thin wrapper around
  `walk_git_repos` to minimize test churn; only remove it if it would otherwise duplicate
  logic. Whatever you choose, `tests/test_scanner.py` must still pass (adjust if you remove
  a function).
- `should_exclude`, `matches_any_pattern`, `get_relative_path` unchanged.

### 4. `src/git_repo_checker/analyzer.py`  (edit)
- In `scan_and_analyze`, replace the `find_git_repos(...)` call + `repo_paths` list with
  `walk = scanner.walk_git_repos(...)`; use `walk.repos` for the executor map and set
  `scan_errors = walk.errors`.
- Pass `scan_errors=scan_errors` into the returned `ScanResult` (already does — just feed
  the real list now).
- No signature change to `scan_and_analyze`. Keep complexity <= 10 (it is already near the
  limit due to the auto-pull loop; do not add branches — just swap the data source).

### 5. `src/git_repo_checker/sync.py`  (edit — rename + auto-track helper + `.grcignore` opt-out)
- **Rename** `clone_repo` -> `clone_tracked_repo`. Update the internal call site in
  `sync_repo` (`return clone_tracked_repo(repo)`). The two `git_ops.clone_repo(...)` calls
  INSIDE it stay as `git_ops.clone_repo` (low-level primitive — unchanged).
- Add a **module-level constant** near the top of `sync.py` (alongside
  `DEFAULT_REPOS_LOCATIONS`):
  ```python
  IGNORE_MARKER = ".grcignore"  # presence in a repo root opts it out of auto-track
  ```
  Do NOT inline the literal string anywhere — always reference `IGNORE_MARKER`.
- **`repo_to_export_entry` — add the `.grcignore` opt-out** (this is the ONLY change to it;
  otherwise leave it intact). At the very top of the function body, before the
  `git_ops.get_remote_url(...)` call, add the skip check so a marked repo is never tracked:
  ```python
  if (repo.path / IGNORE_MARKER).exists():
      return None
  ```
  Rationale (final decision — do not re-open): `repo_to_export_entry` is the single
  choke-point used by BOTH `export_repos_to_file` and (transitively) `auto_track_repos`.
  Returning `None` here makes the existing `skipped += 1` path in `export_repos_to_file`
  (the same branch already used for the no-remote case) count the ignored repo toward
  `skipped` — exactly the desired behavior — with zero changes to any caller. Keep this
  check FIRST (before the remote lookup) so we skip the (slower) `get_remote_url` git call
  for ignored repos. Function stays well under complexity 10 (one extra guard clause).
- `export_repos_to_file` is otherwise **unchanged**; it already increments `skipped` when
  `repo_to_export_entry` returns `None`.
- **scan/display is unaffected**: the marker only short-circuits tracking. Scanning and the
  reporter never call `repo_to_export_entry`, so an ignored repo still shows up normally in
  `grc scan` output. **sync is also unaffected** — sync reads repos.yml, and an ignored repo
  simply never gets written there, so no sync-side code is needed.
- Add a NEW high-level convenience function for auto-track that resolves the default repos
  file target and always merges safely (never raises FileExistsError):
  ```python
  def auto_track_repos(
      repos: list[RepoInfo],
      target: Path,
      path_prefix: str = "~",
  ) -> tuple[int, int, list[tuple[str, str, str]]]:
      """Append newly-found repos to a repos.yml, merging safely.

      Creates the file if missing; merges (never overwrites) if present.
      Skips repos without a remote and those already tracked.

      Args:
          repos: Scanned repos to consider for tracking.
          target: repos.yml path to update.
          path_prefix: Prefix used to relativize repo paths.

      Returns:
          (added, skipped, collisions) — same shape as export_repos_to_file.
      """
      return export_repos_to_file(repos, target, path_prefix, merge=True)
  ```
  (Using `merge=True` unconditionally means it appends to an existing file and creates a new
  one when absent — `export_repos_to_file` already handles the not-exists path by writing
  fresh. Verify: when `output_path` does not exist, `export_repos_to_file` skips the
  FileExistsError branch and writes the default `existing_data`. This is the desired
  "create if missing" behavior. Keep it.)
- Add a resolver for the default auto-track target so cli stays thin:
  ```python
  def default_repos_target(config_target: str | None) -> Path:
      """Resolve where auto-track should write repos.yml.

      Priority: explicit config target -> first existing default repos file ->
      ~/.config/git-repo-checker/repos.yml (created on write).

      Args:
          config_target: Explicit path from AutoTrackConfig.repos_file, or None.

      Returns:
          Absolute path to the repos.yml to update.
      """
      if config_target:
          return Path(config_target).expanduser().resolve()
      found = find_repos_file()
      if found is not None:
          return found
      return (Path.home() / ".config" / "git-repo-checker" / "repos.yml").resolve()
  ```

### 6. `src/git_repo_checker/schedule.py`  (NEW module, ~150-200 lines)
Pure launchd logic, no Typer/Rich imports (keep it testable and layered). Reuse
`subprocess` like `git_ops`/`github_ops` do.

Constants:
```python
LAUNCH_AGENT_LABEL = "com.git-repo-checker.sync"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
```

Add a dataclass for status to avoid a many-field return:
```python
@dataclass
class ScheduleStatus:
    """Current state of the installed sync LaunchAgent."""

    installed: bool
    loaded: bool
    interval_seconds: int | None
    plist_path: Path
    program_args: list[str] = field(default_factory=list)
```

Functions (each with full docstrings, complexity <= 10):

- `def find_grc_executable() -> str:` — resolve the absolute path to the installed `grc`
  entrypoint. Use `shutil.which("grc")`; if None, fall back to
  `f"{sys.executable} -m git_repo_checker"` returned as a single program string is NOT
  allowed for launchd (it needs argv). Decision: return the path string from `which`; if
  not found, raise `RuntimeError("grc executable not found on PATH; install the package")`.
  The plist `ProgramArguments` will be `[grc_path, "sync", "--quiet"]`.

- `def build_plist(interval_seconds: int, program_args: list[str]) -> str:` — return a plist
  XML string with keys: `Label` (LAUNCH_AGENT_LABEL), `ProgramArguments` (program_args),
  `StartInterval` (interval_seconds), `RunAtLoad` (false), and `StandardErrorPath` /
  `StandardOutPath` pointing at
  `~/Library/Logs/git-repo-checker-sync.{err,out}.log` (expanded absolute). Build the XML
  with `plistlib.dumps(plist_dict).decode()` — do NOT hand-roll XML. `plistlib` is stdlib.

- `def install(interval_seconds: int, extra_args: list[str] | None = None) -> Path:` —
  writes the plist and loads it.
  1. Validate `interval_seconds >= 1` else `raise ValueError`.
  2. `program_args = [find_grc_executable(), "sync", "--quiet", *(extra_args or [])]`.
  3. `LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)`; ensure log dir exists.
  4. If already loaded, unload first (call `_launchctl_unload(PLIST_PATH)` ignoring
     failure) so re-install with a new interval works.
  5. Write plist text to `PLIST_PATH`.
  6. `_launchctl_load(PLIST_PATH)`; on failure raise `RuntimeError` with launchctl stderr.
  7. Return `PLIST_PATH`.

- `def uninstall() -> bool:` — unload via launchctl (ignore "not loaded" errors), delete the
  plist if it exists. Return True if a plist was removed, False if nothing was installed.

- `def get_status() -> ScheduleStatus:` — read `PLIST_PATH` if present
  (`plistlib.load`), pull `StartInterval` and `ProgramArguments`; determine `loaded` via
  `_launchctl_list_contains(LAUNCH_AGENT_LABEL)`. Return populated `ScheduleStatus`.

- Private launchctl helpers (each returns `subprocess.CompletedProcess` or bool):
  - `def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:` —
    `subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False,
    timeout=30)`; wrap OSError/TimeoutExpired and raise `RuntimeError`.
  - `def _launchctl_load(plist: Path) -> None:` — `launchctl load -w <plist>`; raise
    `RuntimeError(result.stderr)` on nonzero returncode.
  - `def _launchctl_unload(plist: Path) -> None:` — `launchctl unload -w <plist>`; do not
    raise on nonzero (unload of an unloaded job is fine).
  - `def _launchctl_list_contains(label: str) -> bool:` — run `launchctl list`, return
    `label in result.stdout`.

Note: keep `install` under complexity 10 by extracting the "reload if present" and the
"ensure dirs" steps into tiny helpers if needed.

### 7. `src/git_repo_checker/cli.py`  (edit)
Three areas.

(a) **Auto-track in `scan`**
- Add CLI options to `scan`:
  - `no_track: Annotated[bool, typer.Option("--no-track", help="Disable auto-tracking found repos into repos.yml")] = False`
  Keep existing `export_repos`, `merge`, `path_prefix` options.
- After CI/status-filter processing and BEFORE the `--export-repos` / json / reporter
  output, run auto-track. Order of precedence:
  1. If `export_repos` is given -> keep EXACTLY the current `--export-repos` block
     (explicit target, honors `--merge`, can raise FileExistsError -> exit 1). Then return
     as it does today.
  2. Else if auto-track is enabled (`config.auto_track.enabled and not no_track`) AND not
     `json_output`-only-silent: resolve target via
     `sync_module.default_repos_target(config.auto_track.repos_file)`, choose prefix =
     `path_prefix` if user passed it else `config.auto_track.path_prefix`, then call
     `sync_module.auto_track_repos(result.repos, target, prefix)` and print a concise
     report ONLY when something was added (and always under non-quiet). Do NOT return —
     fall through to normal display so scan still reports status.
- Extract the auto-track reporting into a helper to keep `scan` complexity <= 10:
  ```python
  def _auto_track(result: ScanResult, target: Path, path_prefix: str, quiet: bool) -> None:
      """Append newly-found repos to repos.yml and report additions."""
  ```
  It calls `sync_module.auto_track_repos`, then prints e.g.
  `f"[green]Tracked {added} new repo(s) in[/] {target}"` when `added` and not quiet, plus
  the same collision rendering used by `--export-repos`. Reuse a shared collision-printing
  helper `_print_collisions(collisions)` extracted from the existing export block so both
  paths share it (DRY).
- When `json_output` is set: still perform auto-track silently (no console prints), then
  emit JSON. Keep JSON schema unchanged but it already includes `scan_errors` which will now
  be populated.
- Guard: auto-track should be skipped when `paths`/scan produced zero repos (nothing to do).

(b) **Surface scan_errors**
- In `_output_json` the `scan_errors` key already exists — no change needed (now populated).
- In the non-JSON path, after `reporter.display_results(...)`, print scan errors if any:
  add a helper `_print_scan_errors(result)` that, when `result.scan_errors` and not quiet,
  prints `"[yellow]Scan warnings:[/]"` followed by each error line. Call it in `scan` and
  in the default `main` callback path too (so the default scan surfaces them). Keep it
  trivial.

(c) **`schedule` sub-app**
- Add near the top after `app = typer.Typer(...)`:
  ```python
  schedule_app = typer.Typer(help="Manage the background sync schedule (macOS launchd)")
  app.add_typer(schedule_app, name="schedule")
  ```
- Import the new module: `from git_repo_checker import schedule as schedule_module`.
- Commands:
  ```python
  @schedule_app.command("install")
  def schedule_install(
      interval: Annotated[int, typer.Option("--interval", "-i",
          help="Run interval")] = 60,
      unit: Annotated[str, typer.Option("--unit",
          help="Interval unit: minutes or seconds")] = "minutes",
      repos_path: Annotated[Path | None, typer.Option("-r", "--repos",
          help="repos.yml to pass to sync")] = None,
  ) -> None:
  ```
  - Convert to seconds: `minutes` -> `interval * 60`, `seconds` -> `interval`; reject other
    units with a clear error + exit 1; reject interval < 1.
  - `extra_args = ["--repos", str(repos_path)]` if `repos_path` else `[]`.
  - Call `schedule_module.install(seconds, extra_args)`; print
    `f"[green]Installed sync schedule[/] (every {interval} {unit}) -> {plist}"`.
  - Wrap `RuntimeError`/`ValueError` -> print `[red]Error:[/]` and `raise typer.Exit(1)`.

  ```python
  @schedule_app.command("uninstall")
  def schedule_uninstall() -> None:
  ```
  - Call `schedule_module.uninstall()`; print removed vs "nothing installed".
  - Wrap RuntimeError -> exit 1.

  ```python
  @schedule_app.command("status")
  def schedule_status() -> None:
  ```
  - Call `schedule_module.get_status()`; print installed / loaded / interval / plist path /
    program args in a small rich layout. If not installed, print a hint to run
    `grc schedule install`.

- Keep each command function under complexity 10; push unit->seconds conversion into a tiny
  helper `def _interval_to_seconds(interval: int, unit: str) -> int:` in cli.py (raises
  `typer.BadParameter` or returns seconds).

---

## Test plan (add/adjust — coverage must stay >= 90%)

### `tests/test_scanner.py` (edit)
- Add `TestWalkGitRepos`:
  - `test_finds_repos_returns_walkresult` — using `nested_repos` fixture, assert
    `walk.repos` contains repo1/2/3 and `walk.errors == []`.
  - `test_records_permission_error` — create a dir, monkeypatch `Path.iterdir` (or use a
    real `chmod(0o000)` dir, then restore) so a child raises `PermissionError`; assert an
    error string is recorded and scanning still returns other repos. Prefer monkeypatching
    `pathlib.Path.stat`/`iterdir` on a target path to avoid CI chmod flakiness.
- If you kept `find_git_repos` as a wrapper: keep existing tests. If you removed it: delete
  the now-invalid tests and rely on the new ones.

### `tests/test_analyzer.py` (edit)
- Ensure existing `scan_and_analyze` tests still pass after switching to `walk_git_repos`.
- Add `test_scan_errors_propagated` — monkeypatch `scanner.walk_git_repos` to return a
  `ScanWalkResult(repos=[], errors=["Permission denied: /x"])`; assert
  `result.scan_errors == ["Permission denied: /x"]`.

### `tests/test_sync.py` (edit)
- Rename references: `TestCloneRepo` now patches/calls `sync.clone_tracked_repo`. Update
  `TestSyncRepo.test_clones_missing_repo` to `patch.object(sync, "clone_tracked_repo")`.
- Add `TestAutoTrackRepos`:
  - `test_creates_file_when_missing` — target path under tmp_path that doesn't exist; pass a
    `RepoInfo` whose path has a stubbed remote (patch `git_ops.get_remote_url` to return a
    URL); assert file created, `added == 1`.
  - `test_merges_into_existing` — pre-write a repos.yml with one entry; assert a second new
    repo is added and the original preserved; `added == 1`.
  - `test_skips_repo_without_remote` — patch `git_ops.get_remote_url` -> None; assert
    `added == 0`, `skipped == 1`.
  - `test_grcignore_marker_skips_repo` — create a tmp repo dir containing an (empty)
    `.grcignore` file (e.g. `(repo_dir / sync.IGNORE_MARKER).touch()`); patch
    `git_ops.get_remote_url` to return a real URL (proving the skip is due to the marker,
    not a missing remote); pass that repo to `auto_track_repos` (or directly assert
    `sync.repo_to_export_entry(repo, prefix) is None`). Assert the repo is skipped:
    `added == 0` and `skipped == 1`. (May live under `TestAutoTrackRepos` or a small
    `TestRepoToExportEntry` class — either is fine.)
  - `test_never_raises_on_existing_file` — file exists, no merge flag needed; assert no
    FileExistsError.
- Add `TestDefaultReposTarget`:
  - `test_uses_explicit_config_target`
  - `test_falls_back_to_found_file` (monkeypatch `find_repos_file`)
  - `test_falls_back_to_config_dir` (monkeypatch `find_repos_file` -> None)

### `tests/test_schedule.py` (NEW)
Mock `subprocess.run` / `launchctl` everywhere — never touch the real LaunchAgents dir.
Use `monkeypatch.setattr` on `schedule.LAUNCH_AGENTS_DIR`/`PLIST_PATH` to point under
`tmp_path`.
- `TestBuildPlist`:
  - `test_contains_label_and_interval` — parse with `plistlib.loads`, assert keys.
  - `test_program_args_round_trip`.
- `TestFindGrcExecutable`:
  - `test_returns_which_path` (monkeypatch `shutil.which` -> "/usr/bin/grc").
  - `test_raises_when_missing` (which -> None) expects RuntimeError.
- `TestInstall`:
  - `test_writes_plist_and_loads` — monkeypatch dir/plist to tmp_path, patch
    `_launchctl_load`/`_launchctl_unload`/`find_grc_executable`; assert plist file exists and
    parses, `StartInterval` correct, `ProgramArguments[1] == "sync"`.
  - `test_rejects_nonpositive_interval` -> ValueError.
  - `test_reload_when_already_present` — pre-create plist; assert unload called before load.
  - `test_raises_when_load_fails` — `_launchctl_load` raises RuntimeError; assert propagates.
- `TestUninstall`:
  - `test_removes_existing_plist` -> returns True, file gone.
  - `test_returns_false_when_absent` -> returns False.
- `TestGetStatus`:
  - `test_reports_installed_and_loaded` — pre-write plist, patch
    `_launchctl_list_contains` -> True; assert fields.
  - `test_reports_not_installed` -> installed False, interval None.

### `tests/test_cli.py` (edit)
- `TestScanCommand`: existing tests mock `scan_and_analyze`; auto-track must NOT explode
  when result has repos. Add patches: where a test returns repos and does not want file
  writes, also `patch("git_repo_checker.cli.sync_module.auto_track_repos")` returning
  `(0, 0, [])`. Update the existing `test_scan_*` that return empty results — empty repos
  means auto-track is skipped, so they stay green; verify.
- Add `TestScanAutoTrack`:
  - `test_auto_track_runs_by_default` — mock `scan_and_analyze` to return 1 repo; patch
    `sync_module.auto_track_repos` -> `(1, 0, [])`; assert it was called and stdout mentions
    "Tracked".
  - `test_no_track_flag_disables` — with `--no-track`, assert `auto_track_repos` NOT called.
  - `test_export_repos_still_works` — with `--export-repos <path>`, assert the explicit
    export path is used (patch `sync_module.export_repos_to_file`) and `auto_track_repos`
    NOT called.
  - `test_auto_track_silent_in_json` — with `--json`, assert valid JSON on stdout and no
    "Tracked" human text mixed in (auto-track still called, but no prints).
- Add `TestScanErrorsOutput`:
  - `test_json_includes_scan_errors` — mock `scan_and_analyze` to return
    `ScanResult(repos=[...], scan_errors=["Permission denied: /x"], total_scanned=1)`; assert
    parsed JSON `data["scan_errors"] == ["Permission denied: /x"]`.
  - `test_human_output_shows_scan_warnings` — non-json; assert "Scan warnings" in stdout.
- Add `TestScheduleCommand` (patch `git_repo_checker.cli.schedule_module`):
  - `test_install_minutes` — patch `schedule_module.install` -> a Path; invoke
    `["schedule", "install", "--interval", "30", "--unit", "minutes"]`; assert exit 0 and
    install called with `1800` seconds.
  - `test_install_seconds`.
  - `test_install_rejects_bad_unit` -> exit code != 0.
  - `test_uninstall_reports_removed` — `schedule_module.uninstall` -> True.
  - `test_uninstall_reports_absent` -> False.
  - `test_status_installed` — `schedule_module.get_status` -> a `ScheduleStatus(...)`;
    assert interval/plist printed.

### `tests/test_config.py` (edit)
- Add `test_loads_auto_track_defaults` — config without `auto_track` -> `enabled is True`.
- Add `test_parses_auto_track_disabled` — yaml with `auto_track: {enabled: false}` ->
  `config.auto_track.enabled is False`.

### `tests/test_models.py` (edit)
- Add `test_auto_track_config_defaults`.

---

## Step-by-step order (each step ends with a green toolchain run)

1. [ ] models.py: add `AutoTrackConfig` + `Config.auto_track`. Add test_models cases.
   - Verify: `mypy src/`, `pytest tests/test_models.py`.
2. [ ] config.py: parse + template + expand. Add test_config cases.
   - Verify: `pytest tests/test_config.py`.
3. [ ] scanner.py: add `ScanWalkResult`, `_WalkContext`, `walk_git_repos`, keep
   `find_git_repos` as wrapper. Update test_scanner.
   - Verify: ruff complexity on `walk_git_repos`/`_walk` <= 10; `pytest tests/test_scanner.py`.
4. [ ] analyzer.py: switch to `walk_git_repos`, feed real `scan_errors`. Update/adjust
   test_analyzer; add propagation test.
   - Verify: `pytest tests/test_analyzer.py`.
5. [ ] sync.py: rename `clone_repo` -> `clone_tracked_repo`; add `IGNORE_MARKER` constant
   + the `.grcignore` guard in `repo_to_export_entry`; add `auto_track_repos` +
   `default_repos_target`. Update test_sync (rename + new classes +
   `test_grcignore_marker_skips_repo`).
   - Verify: `grep -rn "sync.clone_repo\b"` shows no stale refs; `pytest tests/test_sync.py`.
6. [ ] schedule.py: implement module. Add tests/test_schedule.py.
   - Verify: `mypy src/`; `pytest tests/test_schedule.py`; complexity of `install` <= 10.
7. [ ] cli.py: add `--no-track`, `_auto_track`, `_print_collisions`, `_print_scan_errors`,
   wire auto-track + export precedence; add `schedule` sub-app + `_interval_to_seconds`.
   Update/adjust test_cli; add new test classes.
   - Verify: `pytest tests/test_cli.py`.
8. [ ] Full toolchain gate:
   - `ruff check --fix . && ruff format . && mypy src/ && pytest --cov-fail-under=90`.
   - Confirm coverage >= 90% (new schedule.py and auto-track paths are the risk areas —
     ensure their tests exercise success + error branches).
9. [ ] README: document auto-track default-on + `--no-track` + `auto_track` config, the
   `.grcignore` per-repo opt-out marker (place an empty `.grcignore` file in a repo root to
   keep it out of repos.yml; it still appears in scan output), and the new
   `grc schedule install/uninstall/status` command. (Docs only; keep concise.)

---

## Risks / watch-outs
- **Complexity creep** in `scan` (cli) and `install` (schedule). Both are the most likely to
  exceed mccabe 10 — extract the helpers named above BEFORE the final ruff run.
- **Existing cli tests** that return repos from `scan_and_analyze` will now trigger
  auto-track and may attempt file writes. Patch `sync_module.auto_track_repos` in those
  tests (or rely on tmp targets). Audit every `TestScanCommand`/`TestScanJsonOutput`/
  `TestScanStatusFilter`/`TestScanCiFlag` test: those returning non-empty repos need the
  patch; empty-repo ones are skipped by the zero-repos guard.
- **launchd `find_grc_executable`**: in the test/CI environment `grc` may not be on PATH;
  always patch `find_grc_executable` in install tests. Real `launchctl` must never run in
  tests — patch the `_launchctl_*` helpers.
- **`export_repos_to_file` create-if-missing**: confirm the not-exists branch writes a fresh
  file (it does today). `auto_track_repos` depends on this; add the
  `test_creates_file_when_missing` test to lock it.
- **scan_errors determinism**: error strings include paths; in tests assert on a substring
  ("Permission denied") not the full string, to avoid path-format flakiness.
