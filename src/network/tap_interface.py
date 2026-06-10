"""TAP interface — user-space Ethernet device for bridge injection.

Unlike AF_PACKET, frames written to a TAP are processed by the kernel
network stack exactly like frames arriving on a real Ethernet port.
Bridges forward TAP frames correctly — this is the standard mechanism
for user-space network simulation (used by QEMU, OpenVPN, etc.).
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import struct
from typing import Optional

from loguru import logger

# ioctl constants
TUNSETIFF = 0x400454CA
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000
MTU = 2048


class TapDevice:
    """A TAP Ethernet interface managed by user-space Python code.

    Usage::

        tap = TapDevice("tap-cr1")
        tap.open()                # creates / attaches to TAP device
        tap.write(ethernet_frame) # inject frame into kernel (→ bridge)
        frame = tap.read()        # receive frame from kernel (← bridge)
        tap.close()
    """

    def __init__(self, name: str):
        self.name = name
        self._fd: int = -1
        self.tx_pkts = 0
        self.rx_pkts = 0
        self.tx_bytes = 0
        self.rx_bytes = 0

    # ------------------------------------------------------------------
    def open(self) -> None:
        """Open /dev/net/tun and attach to TAP interface *name*."""
        self._fd = os.open("/dev/net/tun", os.O_RDWR)
        ifr = struct.pack("16sH", self.name.encode("utf-8"), IFF_TAP | IFF_NO_PI)
        # Retry on EBUSY (old process might still be releasing the TAP)
        for attempt in range(5):
            try:
                fcntl.ioctl(self._fd, TUNSETIFF, ifr)
                break
            except OSError as e:
                if e.errno == 16 and attempt < 4:  # EBUSY
                    import time; time.sleep(0.3)
                    continue
                raise
        os.set_blocking(self._fd, False)
        logger.opt(depth=1).info(f"[{self.name}] TAP opened (fd={self._fd})")

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    # ------------------------------------------------------------------
    def write(self, frame: bytes) -> bool:
        """Inject an Ethernet frame into the kernel via the TAP."""
        try:
            n = os.write(self._fd, frame)
            self.tx_pkts += 1
            self.tx_bytes += n
            return n > 0
        except (OSError, BlockingIOError):
            return False

    def read(self) -> Optional[bytes]:
        """Read an Ethernet frame from the kernel (non-blocking)."""
        try:
            data = os.read(self._fd, MTU)
            if data:
                self.rx_pkts += 1
                self.rx_bytes += len(data)
                return data
        except (OSError, BlockingIOError):
            pass
        return None

    # ------------------------------------------------------------------
    @property
    def fileno(self) -> int:
        return self._fd

    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "tx_pkts": self.tx_pkts,
            "rx_pkts": self.rx_pkts,
            "tx_bytes": self.tx_bytes,
            "rx_bytes": self.rx_bytes,
        }
