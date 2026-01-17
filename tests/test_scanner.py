"""Tests for scanner module."""

from pathlib import Path

from git_repo_checker import scanner


class TestFindGitRepos:
    def test_finds_repos_in_directory(self, nested_repos):
        repos = list(
            scanner.find_git_repos(
                scan_paths=[nested_repos],
                exclude_patterns=[],
                exclude_paths=[],
            )
        )
        # Should find repo1, repo2, repo3 but not node_modules/some-package
        repo_names = [r.name for r in repos]
        assert "repo1" in repo_names
        assert "repo2" in repo_names
        assert "repo3" in repo_names

    def test_excludes_by_pattern(self, nested_repos):
        repos = list(
            scanner.find_git_repos(
                scan_paths=[nested_repos],
                exclude_patterns=["**/node_modules"],
                exclude_paths=[],
            )
        )
        for repo in repos:
            assert "node_modules" not in str(repo)

    def test_excludes_by_path(self, nested_repos):
        exclude_path = nested_repos / "repo1"
        repos = list(
            scanner.find_git_repos(
                scan_paths=[nested_repos],
                exclude_patterns=[],
                exclude_paths=[exclude_path],
            )
        )
        repo_names = [r.name for r in repos]
        assert "repo1" not in repo_names

    def test_handles_nonexistent_path(self, tmp_path):
        repos = list(
            scanner.find_git_repos(
                scan_paths=[tmp_path / "nonexistent"],
                exclude_patterns=[],
                exclude_paths=[],
            )
        )
        assert repos == []

    def test_handles_file_path(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        repos = list(
            scanner.find_git_repos(
                scan_paths=[file_path],
                exclude_patterns=[],
                exclude_paths=[],
            )
        )
        assert repos == []


class TestShouldExclude:
    def test_excludes_by_pattern(self, tmp_path):
        node_modules = tmp_path / "project" / "node_modules"
        node_modules.mkdir(parents=True)
        assert scanner.should_exclude(node_modules, ["**/node_modules"], set())

    def test_excludes_by_explicit_path(self, tmp_path):
        exclude_me = tmp_path / "exclude-me"
        exclude_me.mkdir()
        assert scanner.should_exclude(exclude_me, [], {exclude_me})

    def test_does_not_exclude_allowed_path(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        assert not scanner.should_exclude(allowed, ["**/node_modules"], set())


class TestMatchesAnyPattern:
    def test_matches_double_star_pattern(self, tmp_path):
        node_modules = tmp_path / "project" / "node_modules"
        node_modules.mkdir(parents=True)
        assert scanner.matches_any_pattern(node_modules, ["**/node_modules"])

    def test_matches_simple_pattern(self, tmp_path):
        venv = tmp_path / "venv"
        venv.mkdir()
        assert scanner.matches_any_pattern(venv, ["venv"])

    def test_no_match_returns_false(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        assert not scanner.matches_any_pattern(src, ["**/node_modules", "venv"])


class TestGetRelativePath:
    def test_relative_to_base(self, tmp_path):
        base = tmp_path / "code"
        repo = base / "project" / "repo"
        base.mkdir()
        repo.mkdir(parents=True)

        result = scanner.get_relative_path(repo, [base])
        assert result == "project/repo"

    def test_falls_back_to_home_relative(self, tmp_path):
        result = scanner.get_relative_path(Path.home() / "test", [tmp_path])
        assert result.startswith("~/")

    def test_falls_back_to_absolute(self):
        path = Path("/some/absolute/path")
        result = scanner.get_relative_path(path, [Path("/other/base")])
        assert result == "/some/absolute/path"


class TestScanDirectory:
    def test_finds_git_dir(self, temp_git_repo):
        repos = list(
            scanner.scan_directory(
                root=temp_git_repo.parent,
                exclude_patterns=[],
                exclude_paths=set(),
                visited=set(),
                depth=0,
            )
        )
        assert temp_git_repo in repos

    def test_respects_max_depth(self, tmp_path):
        deep_path = tmp_path
        for i in range(25):
            deep_path = deep_path / f"level{i}"
        deep_path.mkdir(parents=True)

        repos = list(
            scanner.scan_directory(
                root=tmp_path,
                exclude_patterns=[],
                exclude_paths=set(),
                visited=set(),
                depth=0,
            )
        )
        # Should not crash from infinite recursion
        assert isinstance(repos, list)

    def test_skips_hidden_directories(self, tmp_path, temp_git_repo):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        import subprocess
        subprocess.run(["git", "init"], cwd=hidden, capture_output=True, check=True)

        repos = list(
            scanner.scan_directory(
                root=tmp_path,
                exclude_patterns=[],
                exclude_paths=set(),
                visited=set(),
                depth=0,
            )
        )
        hidden_found = any(".hidden" in str(r) for r in repos)
        assert not hidden_found

    def test_skips_already_visited(self, temp_git_repo):
        visited = {temp_git_repo.stat().st_ino}
        repos = list(
            scanner.scan_directory(
                root=temp_git_repo,
                exclude_patterns=[],
                exclude_paths=set(),
                visited=visited,
                depth=0,
            )
        )
        assert repos == []

    def test_stops_at_max_depth(self, tmp_path):
        repos = list(
            scanner.scan_directory(
                root=tmp_path,
                exclude_patterns=[],
                exclude_paths=set(),
                visited=set(),
                depth=25,  # Over MAX_DEPTH
            )
        )
        assert repos == []
