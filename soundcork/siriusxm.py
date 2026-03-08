import logging

from sxm import SXMClient, run_http_server

# pyright: reportOptionalMemberAccess=false

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class SxmServer:
    def __init__(self) -> None:
        logger.info("Initiating Sxm")
        self.sxm = SXMClient("allen_sxm@suberic.net", "H3my8r8gmgy9FG")
        logger.info(f"sxm initialized; sxm={self.sxm}")

    async def startup(self):
        logger.info("starting up sxm")

        logger.info(f"self.sxm={self.sxm}")
        if self.sxm.authenticate():
            logger.info("sxm authenticated")
            # logger.info("sxm started; runing on port 9000")
            # runs proxy server on http://0.0.0.0:9000
            # run_http_server(self.sxm, 9000, ip="0.0.0.0")

    def channel_name(self, name) -> str:
        return self.sxm.get_channel(name).getattr("name", "test name")

    def now_playing(self, station_id):
        logger.info(f"getting now playing for {station_id}")
        channel = self.sxm.get_channel(station_id)
        np = self.sxm.get_now_playing(channel)
        return np
