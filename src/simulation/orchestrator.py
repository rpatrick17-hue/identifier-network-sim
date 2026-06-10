"""Simulation orchestrator – manages the lifecycle of all nodes.

Responsibilities:
    - Start / stop all nodes concurrently.
    - Advance the simulation clock.
    - Collect and report per-node statistics.
    - Provide a clean shutdown sequence.
"""

from __future__ import annotations

import asyncio
import signal
import time
from typing import Callable, Coroutine, List, Optional

from loguru import logger

from .topology import Topology


class Orchestrator:
    """Simulation orchestrator for the Identifier Network."""

    def __init__(self, topology: Topology):
        self.topology = topology
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._start_time: float = 0.0
        self._scenario_hooks: List[Callable[[], Coroutine]] = []

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def start(self) -> None:
        """Launch all nodes."""
        self._running = True
        self._start_time = time.time()

        logger.info(f"Starting simulation with {len(self.topology.nodes)} nodes")

        # Start each node in its own asyncio task
        for name, node in self.topology.nodes.items():
            task = asyncio.create_task(node.run(), name=f"node-{name}")
            self._tasks.append(task)
            logger.debug(f"  launched: {name}")

        # Give nodes a moment to initialise
        await asyncio.sleep(0.1)

        # Set up signal handlers for graceful shutdown
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

        logger.info(f"Simulation running ({len(self._tasks)} tasks)")

    async def stop(self) -> None:
        """Gracefully shut down all nodes."""
        if not self._running:
            return
        self._running = False

        elapsed = time.time() - self._start_time
        logger.info(f"Stopping simulation (elapsed={elapsed:.1f}s)")

        # Signal all nodes to stop
        for node in self.topology.nodes.values():
            node.stop()

        # Wait for all tasks
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        logger.info("All nodes stopped")

    # ==================================================================
    #  Scenario support
    # ==================================================================

    def add_scenario(self, coro_factory: Callable[[], Coroutine]) -> None:
        """Register a scenario function to run after nodes start."""
        self._scenario_hooks.append(coro_factory)

    async def run_scenario(self, scenario_coro: Coroutine, duration: float = 0) -> None:
        """Run a scenario coroutine concurrently with the simulation.

        Args:
            scenario_coro: The scenario coroutine to execute.
            duration: If > 0, auto-stop after this many seconds.
        """
        await self.start()

        scenario_task = asyncio.create_task(scenario_coro, name="scenario")
        self._tasks.append(scenario_task)

        if duration > 0:
            await asyncio.sleep(duration)
            await self.stop()
        else:
            # Wait for scenario to finish
            try:
                await scenario_task
            except asyncio.CancelledError:
                pass
            await self.stop()

    # ==================================================================
    #  Statistics
    # ==================================================================

    def report(self) -> str:
        """Generate a per-node statistics report."""
        lines = [
            "=" * 70,
            f"  Simulation Report  (elapsed={time.time() - self._start_time:.1f}s)",
            "=" * 70,
        ]
        for name, node in self.topology.nodes.items():
            lines.append(f"\n--- {name} ---")
            if hasattr(node, "summary"):
                lines.append(node.summary())
            m = node.metrics.summary()
            lines.append(
                f"  sent={m['sent_packets']} pkts / {m['sent_bytes']} B | "
                f"recv={m['recv_packets']} pkts / {m['recv_bytes']} B"
            )
            if m["avg_rtt_ms"] > 0:
                lines.append(
                    f"  RTT avg={m['avg_rtt_ms']}ms  jitter={m['jitter_ms']}ms  "
                    f"throughput={m['throughput_mbps']}Mbps"
                )
        return "\n".join(lines)
