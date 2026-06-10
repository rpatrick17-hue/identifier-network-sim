"""FTP download demo scenario."""
import asyncio
from loguru import logger


async def run_ftp_demo(topology) -> None:
    logger.info("=== FTP Demo ===")
    ts = topology.test_server
    host1 = topology.hosts.get("Host-1")
    if not ts or not host1:
        return

    await ts.start_ftp_server(file_count=5, file_size=50_000)
    await host1.authenticate()

    for i in range(3):
        await host1.ftp_download(f"file_{i}.bin", ts.aid)
        await asyncio.sleep(0.3)

    logger.info("FTP demo complete")
