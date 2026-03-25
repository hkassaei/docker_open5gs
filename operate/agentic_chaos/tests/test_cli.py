"""Tests for the CLI module — no Docker needed for most, no Gemini needed."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentic_chaos.cli import build_parser


class TestCLIParser:
    def test_list_scenarios_command(self):
        parser = build_parser()
        args = parser.parse_args(["list-scenarios"])
        assert args.command == "list-scenarios"

    def test_run_command(self):
        parser = build_parser()
        args = parser.parse_args(["run", "P-CSCF Latency"])
        assert args.command == "run"
        assert args.scenario == "P-CSCF Latency"

    def test_show_episode_command(self):
        parser = build_parser()
        args = parser.parse_args(["show-episode", "ep_20260318_test"])
        assert args.command == "show-episode"
        assert args.episode_id == "ep_20260318_test"

    def test_heal_all_command(self):
        parser = build_parser()
        args = parser.parse_args(["heal-all"])
        assert args.command == "heal-all"

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-v", "list-scenarios"])
        assert args.verbose is True

    def test_no_command_fails(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestCLIListScenarios:
    @pytest.mark.asyncio
    async def test_list_scenarios_runs(self, capsys):
        from agentic_chaos.cli import cmd_list_scenarios
        parser = build_parser()
        args = parser.parse_args(["list-scenarios"])
        rc = await cmd_list_scenarios(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert "P-CSCF Latency" in captured.out
        assert "gNB Radio Link Failure" in captured.out
        assert "10 scenarios available" in captured.out


class TestCLIListEpisodes:
    @pytest.mark.asyncio
    async def test_list_episodes_empty(self, capsys, tmp_path):
        """List episodes when no episodes exist."""
        from agentic_chaos import cli
        original_dir = cli.EPISODES_DIR
        cli.EPISODES_DIR = tmp_path / "empty_episodes"
        try:
            parser = build_parser()
            args = parser.parse_args(["list-episodes"])
            rc = await cli.cmd_list_episodes(args)
            assert rc == 0
            captured = capsys.readouterr()
            assert "No episodes recorded" in captured.out
        finally:
            cli.EPISODES_DIR = original_dir

    @pytest.mark.asyncio
    async def test_list_episodes_with_data(self, capsys, tmp_path):
        """List episodes when episodes exist."""
        from agentic_chaos import cli
        original_dir = cli.EPISODES_DIR

        # Create a fake episode
        ep_dir = tmp_path / "episodes"
        ep_dir.mkdir()
        ep = {
            "episode_id": "ep_test_001",
            "duration_seconds": 5.0,
            "faults": [{"verified": True}],
            "observations": [{"symptoms_detected": True}],
        }
        (ep_dir / "ep_test_001.json").write_text(json.dumps(ep))

        cli.EPISODES_DIR = ep_dir
        try:
            parser = build_parser()
            args = parser.parse_args(["list-episodes"])
            rc = await cli.cmd_list_episodes(args)
            assert rc == 0
            captured = capsys.readouterr()
            assert "ep_test_001" in captured.out
        finally:
            cli.EPISODES_DIR = original_dir


class TestCLIShowEpisode:
    @pytest.mark.asyncio
    async def test_show_episode_not_found(self, capsys, tmp_path):
        from agentic_chaos import cli
        original_dir = cli.EPISODES_DIR
        cli.EPISODES_DIR = tmp_path
        try:
            parser = build_parser()
            args = parser.parse_args(["show-episode", "nonexistent"])
            rc = await cli.cmd_show_episode(args)
            assert rc == 1
        finally:
            cli.EPISODES_DIR = original_dir

    @pytest.mark.asyncio
    async def test_show_episode_found(self, capsys, tmp_path):
        from agentic_chaos import cli
        original_dir = cli.EPISODES_DIR

        ep = {"episode_id": "ep_test_show", "schema_version": "1.0"}
        (tmp_path / "ep_test_show.json").write_text(json.dumps(ep))

        cli.EPISODES_DIR = tmp_path
        try:
            parser = build_parser()
            args = parser.parse_args(["show-episode", "ep_test_show"])
            rc = await cli.cmd_show_episode(args)
            assert rc == 0
            captured = capsys.readouterr()
            assert "ep_test_show" in captured.out
            assert "1.0" in captured.out
        finally:
            cli.EPISODES_DIR = original_dir
