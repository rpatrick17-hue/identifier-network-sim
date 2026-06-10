"""Mobility handover demo scenario.

Simulates a user (Host-1) moving from AP-1 to AP-2.
"""
import asyncio
from loguru import logger


async def run_mobility_demo(topology) -> None:
    logger.info("=== Mobility Handover Demo ===")

    host1 = topology.hosts.get("Host-1")
    ap1 = topology.access_points.get("AP-1")
    ap2 = topology.access_points.get("AP-2")
    ts = topology.test_server

    if not all([host1, ap1, ap2, ts]):
        logger.error("Required nodes not found")
        return

    await ts.start_http_server()
    await host1.authenticate()

    # Phase 1: Host-1 on AP-1
    logger.info("Phase 1: Host-1 on AP-1")
    await host1.http_get("/test", ts.aid)
    await asyncio.sleep(1.0)

    # Phase 2: Simulate handover AP-1 → AP-2
    logger.info("Phase 2: Host-1 moves AP-1 → AP-2")
    # In simulation: update AP's user status
    cr1 = topology.core_routers.get("CR-1")
    cr2 = topology.core_routers.get("CR-2")
    if cr1 and cr2:
        from src.common.constants import UserStatus
        # Mark user as moved away on old CR
        cr1.set_user_status(
            host1.aid, ap1.aid,
            UserStatus.MOVED_AWAY,
        )
        # Activate user on new CR
        cr2.set_user_status(
            host1.aid, ap2.aid,
            UserStatus.ONLINE,
        )

    # Phase 3: Host-1 sends data from new location
    logger.info("Phase 3: Host-1 sends from new AP-2")
    await host1.http_get("/after_move", ts.aid)
    await asyncio.sleep(1.0)

    logger.info("Mobility demo complete")
