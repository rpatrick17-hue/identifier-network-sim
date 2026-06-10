"""HTTP browsing demo scenario.

Simulates Host-1 sending HTTP requests to the Test Server through the
Identifier Network (AID → RID encapsulation → AID decapsulation).
"""

from __future__ import annotations

import asyncio

from loguru import logger


async def run_http_demo(topology) -> None:
    """Run the HTTP demo scenario."""
    host1 = topology.hosts.get("Host-1")
    ts = topology.test_server

    if not host1 or not ts:
        logger.error("Host-1 or Test Server not found in topology")
        return

    logger.info("=== HTTP Demo: Host-1 → Test Server ===")

    # Initialise test server with synthetic HTTP pages
    await ts.start_http_server(page_size=2048, num_pages=3)

    # Authenticate host
    await host1.authenticate()

    # Send HTTP GET requests
    for i in range(5):
        await host1.http_get(f"/page_{i % 3}.html", ts.aid)
        await asyncio.sleep(0.5)

    logger.info("HTTP demo complete")
