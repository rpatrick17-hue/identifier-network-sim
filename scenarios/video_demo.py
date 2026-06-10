"""Video streaming demo scenario."""
import asyncio
from loguru import logger


async def run_video_demo(topology) -> None:
    logger.info("=== Video Streaming Demo ===")
    ts = topology.test_server
    host2 = topology.hosts.get("Host-2")
    if not ts or not host2:
        return

    await ts.start_video_server(chunk_count=20, chunk_size=40_000)
    await host2.authenticate()

    await host2.video_stream(ts.aid, duration_s=5.0)
    await asyncio.sleep(3.0)

    logger.info("Video demo complete")
