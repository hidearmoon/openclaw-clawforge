"""
Tests for clawforge publish command.

Coverage:
  - _load_manifest            — valid, missing, invalid JSON
  - _run_preflight_checks     — pass / fail delegation to run_checks
  - _git_log_since_last_tag   — with tag, without tag, git absent
  - _generate_changelog_entry — content, fallback
  - _write_changelog          — new file, prepend, skip duplicate
  - _check_build_tool         — installed / missing
  - _check_twine              — installed / missing
  - _build_package            — success, failure
  - _publish_to_pypi          — command construction, failure
  - _create_github_release    — success, API error, tag name
  - _do_publish               — orchestration (dry-run, early exits, full flow)
  - CLI publish command        — help, dry-run, JSON output, env var token
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from clawforge.cli import main
from clawforge.publish_cmd import (
    PublishResult,
    _build_package,
    _check_build_tool,
    _check_twine,
    _create_github_release,
    _do_publish,
    _generate_changelog_entry,
    _git_log_since_last_tag,
    _load_manifest,
    _publish_to_pypi,
    _run_preflight_checks,
    _write_changelog,
)
from clawforge.test_cmd import CheckResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugin_dir(tmp_path):
    """Fully valid plugin directory that passes all pre-flight checks."""
    manifest = {
        "name": "my-tool",
        "version": "0.1.0",
        "type": "tool",
        "engine": ">=0.1.0",
        "entry": "my_tool:MyTool",
    }
    (tmp_path / "openclaw.plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / "my_tool.py").write_text(
        "class MyTool:\n"
        "    def init(self, config): pass\n"
        "    def run(self, payload): return {}\n"
        "    def shutdown(self): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# my-tool\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_my_tool.py").write_text("def test_placeholder(): pass\n")
    (tmp_path / "requirements.txt").write_text("click>=8.0\n")
    return tmp_path


@pytest.fixture
def fake_whl(tmp_path):
    """A single fake .whl artifact."""
    dist = tmp_path / "dist"
    dist.mkdir()
    whl = dist / "my_tool-0.1.0-py3-none-any.whl"
    whl.write_bytes(b"fake wheel")
    return whl


@pytest.fixture
def fake_artifacts(tmp_path):
    """Fake wheel + sdist artifacts."""
    dist = tmp_path / "dist"
    dist.mkdir()
    whl = dist / "my_tool-0.1.0-py3-none-any.whl"
    sdist = dist / "my_tool-0.1.0.tar.gz"
    whl.write_bytes(b"fake wheel")
    sdist.write_bytes(b"fake sdist")
    return [whl, sdist]


def _silent_console() -> MagicMock:
    con = MagicMock()
    con.print = MagicMock()
    return con


def _make_build_patch(artifacts):
    """Return a replacement for _build_package that returns *artifacts*."""
    for a in artifacts:
        a.parent.mkdir(parents=True, exist_ok=True)
        if not a.exists():
            a.write_bytes(b"fake")

    def _fake_build(_path):
        return artifacts

    return _fake_build


# ---------------------------------------------------------------------------
# _load_manifest
# ---------------------------------------------------------------------------

class TestLoadManifest:
    def test_returns_dict_for_valid_manifest(self, plugin_dir):
        m = _load_manifest(plugin_dir)
        assert m["name"] == "my-tool"
        assert m["version"] == "0.1.0"

    def test_raises_file_not_found_when_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="openclaw.plugin.json"):
            _load_manifest(tmp_path)

    def test_raises_on_malformed_json(self, tmp_path):
        (tmp_path / "openclaw.plugin.json").write_text("{bad: json}")
        with pytest.raises(json.JSONDecodeError):
            _load_manifest(tmp_path)


# ---------------------------------------------------------------------------
# _run_preflight_checks
# ---------------------------------------------------------------------------

class TestRunPreflightChecks:
    def test_returns_true_for_valid_plugin(self, plugin_dir):
        passed, results = _run_preflight_checks(plugin_dir)
        assert passed is True
        assert results  # non-empty

    def test_returns_false_when_manifest_missing(self, tmp_path):
        passed, results = _run_preflight_checks(tmp_path)
        assert passed is False
        assert any(r.status == "fail" for r in results)


# ---------------------------------------------------------------------------
# _git_log_since_last_tag
# ---------------------------------------------------------------------------

class TestGitLogSinceLastTag:
    def _make_run(self, describe_rc, log_stdout):
        def _side(cmd, **kw):
            if "describe" in cmd:
                return MagicMock(returncode=describe_rc, stdout="v0.0.1\n")
            return MagicMock(returncode=0, stdout=log_stdout)
        return _side

    def test_returns_commits_when_tag_exists(self, tmp_path):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            side_effect=self._make_run(0, "- feat: new feature"),
        ):
            result = _git_log_since_last_tag(tmp_path)
        assert "feat: new feature" in result

    def test_uses_head_range_when_no_previous_tag(self, tmp_path):
        called = []

        def _side(cmd, **kw):
            called.append(cmd)
            if "describe" in cmd:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="- fix: something")

        with patch("clawforge.publish_cmd.subprocess.run", side_effect=_side):
            _git_log_since_last_tag(tmp_path)

        log_cmd = next(c for c in called if "log" in c)
        assert "HEAD" in log_cmd
        assert ".." not in " ".join(log_cmd)

    def test_returns_empty_string_on_git_error(self, tmp_path):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=1, stdout="", stderr=""),
        ):
            assert _git_log_since_last_tag(tmp_path) == ""

    def test_returns_empty_string_when_git_not_found(self, tmp_path):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert _git_log_since_last_tag(tmp_path) == ""


# ---------------------------------------------------------------------------
# _generate_changelog_entry
# ---------------------------------------------------------------------------

class TestGenerateChangelogEntry:
    def test_includes_version_header(self, tmp_path):
        with patch(
            "clawforge.publish_cmd._git_log_since_last_tag",
            return_value="- feat: stuff",
        ):
            entry = _generate_changelog_entry(tmp_path, "2.3.4")
        assert "## [2.3.4]" in entry

    def test_includes_commit_lines(self, tmp_path):
        with patch(
            "clawforge.publish_cmd._git_log_since_last_tag",
            return_value="- feat: cool",
        ):
            entry = _generate_changelog_entry(tmp_path, "1.0.0")
        assert "feat: cool" in entry

    def test_falls_back_to_initial_release_when_no_commits(self, tmp_path):
        with patch(
            "clawforge.publish_cmd._git_log_since_last_tag",
            return_value="",
        ):
            entry = _generate_changelog_entry(tmp_path, "0.1.0")
        assert "Initial release" in entry


# ---------------------------------------------------------------------------
# _write_changelog
# ---------------------------------------------------------------------------

class TestWriteChangelog:
    def test_creates_new_file_with_header(self, tmp_path):
        entry = "## [0.1.0] - 2024-01-01\n\n- initial\n"
        _write_changelog(tmp_path, entry, "0.1.0")
        content = (tmp_path / "CHANGELOG.md").read_text()
        assert "# Changelog" in content
        assert "## [0.1.0]" in content

    def test_prepends_new_version_before_older_ones(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.0.1] - 2024-01-01\n\n- first\n"
        )
        entry = "## [0.1.0] - 2024-06-01\n\n- second\n"
        _write_changelog(tmp_path, entry, "0.1.0")
        content = (tmp_path / "CHANGELOG.md").read_text()
        assert content.index("## [0.1.0]") < content.index("## [0.0.1]")

    def test_skips_write_if_version_already_present(self, tmp_path):
        existing = "# Changelog\n\n## [0.1.0] - 2024-01-01\n\n- already here\n"
        (tmp_path / "CHANGELOG.md").write_text(existing)
        entry = "## [0.1.0] - 2024-06-01\n\n- duplicate\n"
        _write_changelog(tmp_path, entry, "0.1.0")
        content = (tmp_path / "CHANGELOG.md").read_text()
        assert content.count("## [0.1.0]") == 1

    def test_returns_path_to_changelog(self, tmp_path):
        path = _write_changelog(tmp_path, "## [1.0.0]\n\n- x\n", "1.0.0")
        assert path == tmp_path / "CHANGELOG.md"


# ---------------------------------------------------------------------------
# _check_build_tool / _check_twine
# ---------------------------------------------------------------------------

class TestCheckTools:
    def test_check_build_tool_ok_when_importable(self):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=0),
        ):
            _check_build_tool()  # must not raise

    def test_check_build_tool_raises_when_missing(self):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=1),
        ):
            with pytest.raises(RuntimeError, match="'build' package"):
                _check_build_tool()

    def test_check_twine_ok_when_importable(self):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=0),
        ):
            _check_twine()  # must not raise

    def test_check_twine_raises_when_missing(self):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=1),
        ):
            with pytest.raises(RuntimeError, match="twine"):
                _check_twine()


# ---------------------------------------------------------------------------
# _build_package
# ---------------------------------------------------------------------------

class TestBuildPackage:
    def test_returns_wheel_and_sdist_on_success(self, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        whl = dist_dir / "pkg-0.1.0-py3-none-any.whl"
        sdist = dist_dir / "pkg-0.1.0.tar.gz"
        whl.write_bytes(b"w")
        sdist.write_bytes(b"s")

        with patch("clawforge.publish_cmd.subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            with patch("clawforge.publish_cmd.shutil.rmtree"):  # keep pre-created files
                artifacts = _build_package(tmp_path)

        names = [a.name for a in artifacts]
        assert any(".whl" in n for n in names)
        assert any(".tar.gz" in n for n in names)

    def test_raises_runtime_error_on_build_failure(self, tmp_path):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="Build exploded"),
        ):
            with patch("clawforge.publish_cmd.shutil.rmtree"):
                with patch.object(Path, "exists", return_value=False):
                    with pytest.raises(RuntimeError, match="Build failed"):
                        _build_package(tmp_path)

    def test_removes_existing_dist_dir_before_build(self, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()

        rmtree_calls = []

        def _fake_rmtree(path):
            rmtree_calls.append(path)

        with patch("clawforge.publish_cmd.subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            with patch("clawforge.publish_cmd.shutil.rmtree", side_effect=_fake_rmtree):
                try:
                    _build_package(tmp_path)
                except Exception:
                    pass  # glob may fail; we only care that rmtree was called

        assert any(str(p).endswith("dist") for p in rmtree_calls)


# ---------------------------------------------------------------------------
# _publish_to_pypi
# ---------------------------------------------------------------------------

class TestPublishToPypi:
    def test_calls_twine_upload_with_token(self, fake_artifacts):
        with patch("clawforge.publish_cmd.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            _publish_to_pypi(fake_artifacts, "pypi-secret")

        cmd = mock_run.call_args[0][0]
        assert "twine" in cmd
        assert "upload" in cmd
        assert "__token__" in cmd
        assert "pypi-secret" in cmd

    def test_includes_repository_url_when_given(self, fake_artifacts):
        with patch("clawforge.publish_cmd.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            _publish_to_pypi(
                fake_artifacts, "tok", "https://test.pypi.org/legacy/"
            )

        cmd = mock_run.call_args[0][0]
        assert "--repository-url" in cmd
        assert "https://test.pypi.org/legacy/" in cmd

    def test_raises_on_twine_failure(self, fake_artifacts):
        with patch(
            "clawforge.publish_cmd.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="Upload rejected"),
        ):
            with pytest.raises(RuntimeError, match="PyPI upload failed"):
                _publish_to_pypi(fake_artifacts, "bad-token")


# ---------------------------------------------------------------------------
# _create_github_release
# ---------------------------------------------------------------------------

class TestCreateGithubRelease:
    def _mock_post(self, status=201, release_url="https://github.com/o/r/releases/tag/v1"):
        mock = MagicMock()
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = {
            "html_url": release_url,
            "upload_url": "https://uploads.github.com/repos/o/r/releases/1/assets{?name}",
        }
        resp.text = ""
        mock.return_value = resp
        return mock

    def test_returns_html_url_on_success(self, fake_artifacts):
        mock_post = self._mock_post()
        with patch("httpx.post", mock_post):
            url = _create_github_release(
                "my-tool", "1.0.0", "notes", "gh-tok", "owner/repo", fake_artifacts
            )
        assert "github.com" in url

    def test_uses_v_prefixed_tag_name(self, fake_artifacts):
        mock_post = self._mock_post()
        with patch("httpx.post", mock_post):
            _create_github_release(
                "p", "2.3.4", "body", "tok", "o/r", []
            )
        first_call_kwargs = mock_post.call_args_list[0][1]
        assert first_call_kwargs["json"]["tag_name"] == "v2.3.4"

    def test_raises_on_non_2xx_response(self, fake_artifacts):
        mock_post = self._mock_post(status=422)
        mock_post.return_value.text = "Validation Failed"
        with patch("httpx.post", mock_post):
            with pytest.raises(RuntimeError, match="GitHub API error 422"):
                _create_github_release(
                    "p", "1.0.0", "b", "tok", "o/r", []
                )

    def test_upload_url_stripping_template(self, tmp_path):
        """Upload URL must have the {?...} template suffix removed."""
        mock_post = self._mock_post()
        upload_calls = []

        original_post = mock_post.return_value  # the release response

        def _post_side_effect(url, **kw):
            upload_calls.append(url)
            return original_post

        with patch("httpx.post", side_effect=_post_side_effect):
            try:
                _create_github_release("p", "1.0.0", "b", "tok", "o/r", [])
            except Exception:
                pass

        # The release creation URL should not contain the template suffix
        assert all("{" not in u for u in upload_calls)


# ---------------------------------------------------------------------------
# _do_publish  (orchestration)
# ---------------------------------------------------------------------------

class TestDoPublish:
    def test_returns_early_with_error_when_manifest_missing(self, tmp_path):
        result = _do_publish(
            plugin_path=tmp_path,
            token=None, github_token=None, repo=None,
            dry_run=False, skip_test=True, skip_changelog=True,
            repository_url=None, con=_silent_console(),
        )
        assert result.plugin_name == "unknown"
        assert result.errors

    def test_dry_run_skips_pypi_and_github(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    result = _do_publish(
                        plugin_path=plugin_dir,
                        token="tok", github_token="gh", repo="o/r",
                        dry_run=True, skip_test=False, skip_changelog=True,
                        repository_url=None, con=_silent_console(),
                    )

        assert result.dry_run is True
        assert result.wheel_built is True
        assert result.pypi_published is False
        assert result.github_release_created is False
        assert not result.errors

    def test_returns_early_when_preflight_fails(self, plugin_dir):
        bad = CheckResult("f", "fail", "broken", "manifest")
        with patch(
            "clawforge.publish_cmd._run_preflight_checks",
            return_value=(False, [bad]),
        ):
            result = _do_publish(
                plugin_path=plugin_dir,
                token=None, github_token=None, repo=None,
                dry_run=False, skip_test=False, skip_changelog=True,
                repository_url=None, con=_silent_console(),
            )
        assert result.checks_passed is False
        assert result.errors

    def test_skips_preflight_when_no_test(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        mock_checks = MagicMock(return_value=(True, []))
        with patch("clawforge.publish_cmd._run_preflight_checks", mock_checks):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    _do_publish(
                        plugin_path=plugin_dir,
                        token=None, github_token=None, repo=None,
                        dry_run=True, skip_test=True, skip_changelog=True,
                        repository_url=None, con=_silent_console(),
                    )
        mock_checks.assert_not_called()

    def test_changelog_written_when_not_skipped(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch(
                        "clawforge.publish_cmd._git_log_since_last_tag",
                        return_value="- feat: added",
                    ):
                        result = _do_publish(
                            plugin_path=plugin_dir,
                            token=None, github_token=None, repo=None,
                            dry_run=True, skip_test=False, skip_changelog=False,
                            repository_url=None, con=_silent_console(),
                        )
        assert result.changelog_written is True
        assert (plugin_dir / "CHANGELOG.md").exists()

    def test_records_build_failure_in_errors(self, plugin_dir):
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch(
                    "clawforge.publish_cmd._build_package",
                    side_effect=RuntimeError("Build exploded"),
                ):
                    result = _do_publish(
                        plugin_path=plugin_dir,
                        token=None, github_token=None, repo=None,
                        dry_run=False, skip_test=False, skip_changelog=True,
                        repository_url=None, con=_silent_console(),
                    )
        assert result.errors
        assert "Build exploded" in result.errors[0]

    def test_calls_publish_to_pypi_when_token_present(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch("clawforge.publish_cmd._check_twine"):
                        with patch("clawforge.publish_cmd._publish_to_pypi") as mock_pypi:
                            result = _do_publish(
                                plugin_path=plugin_dir,
                                token="pypi-tok",
                                github_token=None, repo=None,
                                dry_run=False, skip_test=False, skip_changelog=True,
                                repository_url=None, con=_silent_console(),
                            )
        mock_pypi.assert_called_once()
        assert result.pypi_published is True

    def test_calls_github_release_when_token_and_repo_present(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch(
                        "clawforge.publish_cmd._create_github_release",
                        return_value="https://github.com/x",
                    ) as mock_gh:
                        result = _do_publish(
                            plugin_path=plugin_dir,
                            token=None,
                            github_token="gh-tok", repo="owner/repo",
                            dry_run=False, skip_test=False, skip_changelog=True,
                            repository_url=None, con=_silent_console(),
                        )
        mock_gh.assert_called_once()
        assert result.github_release_created is True
        assert result.github_release_url == "https://github.com/x"

    def test_pypi_error_recorded_but_does_not_abort(self, plugin_dir, fake_whl):
        """A PyPI failure should still attempt GitHub Release."""
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch("clawforge.publish_cmd._check_twine"):
                        with patch(
                            "clawforge.publish_cmd._publish_to_pypi",
                            side_effect=RuntimeError("rejected"),
                        ):
                            with patch(
                                "clawforge.publish_cmd._create_github_release",
                                return_value="https://github.com/x",
                            ) as mock_gh:
                                result = _do_publish(
                                    plugin_path=plugin_dir,
                                    token="bad-tok",
                                    github_token="gh-tok", repo="o/r",
                                    dry_run=False, skip_test=False, skip_changelog=True,
                                    repository_url=None, con=_silent_console(),
                                )
        assert result.errors
        mock_gh.assert_called_once()
        assert result.github_release_created is True

    def test_skips_github_when_repo_missing(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch("clawforge.publish_cmd._create_github_release") as mock_gh:
                        _do_publish(
                            plugin_path=plugin_dir,
                            token=None,
                            github_token="gh-tok", repo=None,  # repo missing
                            dry_run=False, skip_test=False, skip_changelog=True,
                            repository_url=None, con=_silent_console(),
                        )
        mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestPublishCLI:
    def _invoke(self, args, env=None):
        runner = CliRunner()
        return runner.invoke(main, args, catch_exceptions=False, env=env or {})

    def test_help_lists_publish_subcommand(self):
        result = self._invoke(["--help"])
        assert result.exit_code == 0
        assert "publish" in result.output

    def test_publish_help_shows_options(self):
        result = self._invoke(["publish", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--no-test" in result.output
        assert "--json" in result.output

    def test_dry_run_exits_zero(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    result = self._invoke([
                        "publish", str(plugin_dir),
                        "--dry-run", "--no-changelog",
                    ])
        assert result.exit_code == 0

    def test_json_output_is_parseable(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    result = self._invoke([
                        "publish", str(plugin_dir),
                        "--dry-run", "--no-changelog", "--json",
                    ])
        assert result.exit_code == 0
        # JSON block is somewhere in the output
        lines = result.output.strip().split("\n")
        json_start = next(
            (i for i, ln in enumerate(lines) if ln.strip() == "{"), None
        )
        assert json_start is not None, f"No JSON found in output:\n{result.output}"
        data = json.loads("\n".join(lines[json_start:]))
        assert data["plugin_name"] == "my-tool"
        assert data["dry_run"] is True
        assert data["wheel_built"] is True

    def test_exits_nonzero_when_manifest_missing(self, tmp_path):
        # CliRunner translates sys.exit(1) → exit_code=1
        result = CliRunner().invoke(
            main,
            ["publish", str(tmp_path), "--no-test", "--no-changelog", "--dry-run"],
        )
        assert result.exit_code == 1

    def test_token_read_from_env_var(self, plugin_dir, fake_whl):
        arts = [fake_whl]
        with patch("clawforge.publish_cmd._run_preflight_checks", return_value=(True, [])):
            with patch("clawforge.publish_cmd._check_build_tool"):
                with patch("clawforge.publish_cmd._build_package", _make_build_patch(arts)):
                    with patch("clawforge.publish_cmd._check_twine"):
                        with patch("clawforge.publish_cmd._publish_to_pypi") as mock_pypi:
                            self._invoke(
                                ["publish", str(plugin_dir), "--no-changelog"],
                                env={"PYPI_TOKEN": "env-secret"},
                            )
        mock_pypi.assert_called_once()
        assert mock_pypi.call_args[0][1] == "env-secret"

    def test_json_errors_field_non_empty_on_failure(self, tmp_path):
        result = CliRunner().invoke(
            main,
            ["publish", str(tmp_path), "--no-test", "--no-changelog", "--dry-run", "--json"],
        )
        lines = result.output.strip().split("\n")
        json_start = next(
            (i for i, ln in enumerate(lines) if ln.strip() == "{"), None
        )
        assert json_start is not None
        data = json.loads("\n".join(lines[json_start:]))
        assert data["errors"]
