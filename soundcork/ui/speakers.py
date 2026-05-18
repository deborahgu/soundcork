import logging
import xml.etree.ElementTree as ET

from bosesoundtouchapi.models import SimpleConfig  # type: ignore
from bosesoundtouchapi.soundtouchclient import (  # type: ignore
    ContentItem as BCContentItem,
    SoundTouchClient,
    SoundTouchDevice,
    SoundTouchNodes,
)
from bosesoundtouchapi.soundtouchdiscovery import SoundTouchDiscovery  # type: ignore
from pydantic import BaseModel

from soundcork.config import Settings
from soundcork.datastore import DataStore
from soundcork.model import ContentItem

logger = logging.getLogger(__name__)


class CombinedDevice(BaseModel):
    """Device: either detected, configured, or both

    A Device that's at least one of:
    - A physical SoundTouch speaker detected on the network
    - A configured DeviceInfo block stored in the datastore.

    Property:
    - id: Bose-issued unique speaker ID from DeviceInfo
    - ip: The speaker's IP address
    - name: Human-readable speaker name
    - online: Discoverable on the network as of last-update to this object. Not updated on disconnect.
    - account: Account ID
    - in_soundcork: In the soundcork datastore
    - marge_server: API this speaker uses for Marge: (ie. Bose, or this Soundcork instance)
    - reachable:  Has been configured (ie. with a USB key) to have shell-access available.
    - st_device: SoundTouchDevice instance as discovered by BoseSoundTouchApi
    """

    id: str
    ip: str
    name: str
    online: bool
    account: str | None
    in_soundcork: bool
    marge_server: str
    reachable: bool
    st_device: SoundTouchDevice | None
    language_code: str | None = None

    class Config:
        arbitrary_types_allowed = True


class Speakers:
    """
    This class contains methods used to interact with speakers, primarily through the
    bosesoundtouchapi package (https://github.com/thlucas1/bosesoundtouchapi)
    """

    def __init__(self, datastore: DataStore, settings: Settings) -> None:
        self._st_discovery = SoundTouchDiscovery(areDevicesVerified=True)
        self._st_discovery.DiscoverDevices(timeout=1)
        self._datastore = datastore
        self._settings = settings

    def soundtouch_devices(self) -> dict:
        return self._st_discovery.VerifiedDevices

    def clear_device(self, device_id: str):
        cd = self.all_devices().get(device_id)
        if cd:
            st = cd.st_device
            if st:
                self._st_discovery.VerifiedDevices.pop(f"{st.Host}:8090")
                self._st_discovery.DiscoveredDeviceNames.pop(f"{st.Host}:8090")

    def device_by_id(self, ip_port: str) -> SoundTouchDevice:
        logger.debug(f"Getting device by id: {ip_port}")
        return self._st_discovery.VerifiedDevices.get(ip_port)

    def all_devices(self) -> dict[str, CombinedDevice]:
        """
        Returns a combination of all devices seen on the network and
        all devices configured in soundcork as a dict with the device
        id as the key
        """
        combined_devices = {}
        account_ids = self._datastore.list_accounts()
        for account_id in account_ids:
            if account_id:
                for device_id in self._datastore.list_devices(account_id):
                    if device_id:
                        device_info = self._datastore.get_device_info(
                            account_id, device_id
                        )
                        cd = CombinedDevice(
                            # If the IP changes on a device reboot, it would have made a `/power_on`
                            # call to Soundcork, which will have already updated the datastore.
                            id=device_id,
                            ip=device_info.ip_address,
                            name=device_info.name,
                            online=False,
                            account=account_id,
                            in_soundcork=True,
                            marge_server="Unknown",
                            reachable=False,
                            st_device=None,
                        )
                        combined_devices[device_id] = cd
                        logger.debug(
                            f"cd for {device_id} = {combined_devices[device_id]}"
                        )

        verified = self.soundtouch_devices()
        for key in verified.keys():
            st_device = verified[key]
            id = st_device.DeviceId
            sc_device = combined_devices.get(id, None)

            if sc_device:
                sc_device.online = True
                sc_device.st_device = st_device
            else:
                new_cd = CombinedDevice(
                    id=id,
                    ip=st_device.Host,
                    name=st_device.DeviceName,
                    online=True,
                    account=st_device.StreamingAccountUUID,
                    in_soundcork=False,
                    marge_server=st_device.StreamingUrl,
                    reachable=False,
                    st_device=st_device,
                )
                combined_devices[id] = new_cd
                sc_device = new_cd
            if st_device.StreamingUrl == "https://streaming.bose.com":
                sc_device.marge_server = "Bose"
            elif st_device.StreamingUrl == f"{self._settings.base_url}/marge":
                sc_device.marge_server = "Soundcork"
            else:
                sc_device.marge_server = f"Unknown ({st_device.StreamingUrl})"

        return combined_devices

    def _content_item_to_soundtouchclient(self, ci: ContentItem) -> BCContentItem:
        """Maps our ContentItem to a SoundTouchClient ContentItem."""
        return BCContentItem(
            name=ci.name,
            source=ci.source,
            typeValue=ci.type,
            location=ci.location,
            sourceAccount=ci.source_account,
            isPresetable=ci.is_presetable,
        )

    def play_content_item(self, device_id: str, content_item_id: str) -> bool:
        """Play a content_item on a specific device.

        Args:
            device_id: The device ID to play on
            content_item: The content item ID to play

        Returns:
            True if successful, False otherwise
        """
        cd = self.all_devices().get(device_id)
        if not cd or not cd.st_device:
            logger.error(f"Device {device_id} not found or not online")
            return False

        if not cd.account:
            logger.error(f"Device {device_id} not associated with an account")
            return False

        content_item = self._datastore.get_content_item(
            account=cd.account,
            device_id=cd.id,
            ci_id=content_item_id,
        )
        if not content_item:
            logger.error(f"{content_item_id} is not a defined ContentItem")
            return False

        logger.info(
            f"Attempting playback of content item {content_item_id} on device {device_id}"
        )
        bose_content_item = self._content_item_to_soundtouchclient(content_item)
        client = SoundTouchClient(cd.st_device)
        client.PlayContentItem(bose_content_item)

        return True

    def stop_playback(self, device_id: str) -> bool:
        """Stop playback on a specific device.

        Args:
            device_id: The device ID to stop

        Returns:
            True if successful, False otherwise
        """
        cd = self.all_devices().get(device_id)
        if not cd or not cd.st_device:
            logger.error(f"Device {device_id} not found or not online")
            return False

        client = SoundTouchClient(cd.st_device)
        try:
            client.MediaStop()
            logger.info(f"Stopped playback on device {device_id}")
            return True
        except Exception as e:
            logger.error(f"Error stopping playback on device {device_id}: {e}")
            return False

    async def set_name(self, device_id: str, name: str) -> bool:
        """Sets the name of a device.

        Args:
            device_id: The device ID of the device
            name: the new name

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"setting name {device_id} to {name}")
        combined_device = self.all_devices().get(device_id)
        if combined_device:
            logger.info(f"found device {combined_device.id}")
            speaker = combined_device.st_device
            st_client = SoundTouchClient(speaker)
            logger.info("setting name")
            root = ET.Element("name")
            root.text = name
            payload = ET.tostring(root, "utf-8").decode()
            logger.info(f"sending set name payload {payload}")

            st_client.Put(SoundTouchNodes.name, payload)
            # st_client.SetName(name)
            logger.info("set name was successful")
            return True
        return False

    async def set_language(self, device_id: str, language: str) -> bool:
        """Sets the language for a device.

        Args:
            device_id: The device ID of the device
            language: the new language

        Returns:
            True if successful, False otherwise
        """
        combined_device = self.all_devices().get(device_id)
        if combined_device:
            speaker = combined_device.st_device
            st_client = SoundTouchClient(speaker)
            st_client.SetLanguage(language)
            return True
        return False

    def set_account(self, device_id: str, account_id: str) -> bool:
        """Sets the account for a device.

        Args:
            device_id: The device ID of the device
            account_id: The ID of the account

        Returns:
            True if successful, False otherwise
        """
        combined_device = self.all_devices().get(device_id)

        if combined_device:
            root = ET.Element("PairDeviceWithAccount")
            ET.SubElement(root, "accountId").text = account_id
            ET.SubElement(root, "userAuthToken").text = "dontcare"
            payload = ET.tostring(root, "utf-8").decode()
            logger.info(f"sending set account payload {payload}")
            speaker = combined_device.st_device
            st_client = SoundTouchClient(speaker)

            st_client.Put(SoundTouchNodes.setMargeAccount, payload)
            return True
        return False
