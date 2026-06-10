#!/usr/bin/env python3
"""Identifier Network Simulation – main entry point.

Usage:
    python scripts/run.py --config config/topology.yaml
    python scripts/run.py --config config/topology.yaml --duration 30
    python scripts/run.py --config config/topology.yaml --scenario http_demo
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@click.command()
@click.option(
    "--config", "-c",
    default="config/topology.yaml",
    type=click.Path(exists=True),
    help="Topology YAML configuration file",
)
@click.option(
    "--duration", "-d",
    default=0,
    type=float,
    help="Simulation duration in seconds (0 = run until Ctrl+C)",
)
@click.option(
    "--scenario", "-s",
    default="basic",
    type=click.Choice(["basic", "http_demo", "ftp_demo", "video_demo", "mobility"]),
    help="Scenario to run",
)
@click.option(
    "--log-level", "-l",
    default="INFO",
    type=click.Choice(["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Logging level",
)
@click.option(
    "--monitor/--no-monitor",
    default=True,
    help="Enable / disable real-time monitoring dashboard",
)
def main(config: str, duration: float, scenario: str, log_level: str, monitor: bool):
    """Launch the Identifier Network simulation."""

    from src.common.utils import setup_logging
    from src.simulation.topology import Topology
    from src.simulation.orchestrator import Orchestrator

    # Setup
    setup_logging(level=log_level)

    # Build topology
    config_path = Path(config)
    if not config_path.is_absolute():
        config_path = _PROJECT_ROOT / config_path

    click.echo(f"Loading topology from: {config_path}")
    topology = Topology.from_yaml(str(config_path))
    click.echo(topology.summary())

    # Create orchestrator
    orch = Orchestrator(topology)

    # Run
    async def _run() -> None:
        await orch.start()

        if scenario == "basic":
            # Basic: just let the network run, nodes exchange keep-alives
            pass
        elif scenario == "http_demo":
            from scenarios.http_demo import run_http_demo
            await run_http_demo(topology)
        elif scenario == "ftp_demo":
            from scenarios.ftp_demo import run_ftp_demo
            await run_ftp_demo(topology)
        elif scenario == "video_demo":
            from scenarios.video_demo import run_video_demo
            await run_video_demo(topology)
        elif scenario == "mobility":
            from scenarios.mobility_handover import run_mobility_demo
            await run_mobility_demo(topology)

        if duration > 0:
            await asyncio.sleep(duration)
        else:
            # Wait forever (user hits Ctrl+C)
            while True:
                await asyncio.sleep(1)

        await orch.stop()
        click.echo(orch.report())

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user")
        asyncio.run(orch.stop())
        click.echo(orch.report())


if __name__ == "__main__":
    main()
