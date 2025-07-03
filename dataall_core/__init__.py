"""Init Dataall Core."""

import logging
import os
import sys

root_logger = logging.getLogger("dataall_core")
root_logger.setLevel(os.environ.get("dataall_core_loglevel", "INFO").upper())

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
root_logger.addHandler(handler)
