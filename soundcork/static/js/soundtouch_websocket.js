export class SoundTouchHandler {
    connected(speakerId) {
    }
    updateNowPlaying(speakerId, track, artist, album, imageUrl, status) {
    }
    updateVolume(speakerId, actualVolume, targetVolume) {
    }
}

export async function loadSpeakers(accountId, handler) {
    $.ajax("/marge/streaming/account/" + accountId + "/devices")
    .done(function(xml) {
        const devices = xml.getElementsByTagName("device")
        for (let device of devices) {
            const deviceId = device.getAttribute("deviceid")
            const ipAddr = device.getElementsByTagName("ipaddress")[0].innerHTML
            const name = device.getElementsByTagName("name")[0].innerHTML
            connectWebsocket(deviceId, ipAddr, name, handler)
        }

    })
}

export function connectWebsocket(speakerId, ipAddr, name, handler) {
    const websocket = new WebSocket("ws://" + ipAddr + ":8080", "gabbo");
    websocket.addEventListener("open", () => {
        console.log("websocket connected to " + ipAddr);
        handler.connected(speakerId)
    });
    websocket.addEventListener("message", (e) => {
        const xmlDoc = $.parseXML(e.data);
        const updates = xmlDoc.getElementsByTagName("updates")
        if (updates.length > 0) {
            if (updates[0].getAttribute("deviceID") == speakerId) {
                const nowPlaying = updates[0].getElementsByTagName("nowPlaying")
                if (nowPlaying.length > 0) {
                    parseNowPlayingMessage(nowPlaying[0], speakerId, handler)
                    return;
                }
                const volume = updates[0].getElementsByTagName("volumeUpdated")
                if (volume.length > 0) {
                    parseVolumeMessage(volume[0], speakerId, handler)
                }
            }
        }
        // not yet handled: zones
    });
}

function parseNowPlayingMessage(nowPlaying, speakerId, handler) {

    const trackElems = nowPlaying.getElementsByTagName("track")
    const track = trackElems.length > 0 ? trackElems[0].innerHTML : ""

    const artistElems = nowPlaying.getElementsByTagName("artist")
    const artist = artistElems.length > 0 ? artistElems[0].innerHTML : ""


    const albumElems = nowPlaying.getElementsByTagName("album")
    const album = albumElems.length > 0 ?  albumElems[0].innerHTML : ""

    const statusElems = nowPlaying.getElementsByTagName("playStatus")
    const status = statusElems.length > 0 ? statusElems[0].innerHTML : ""

    const imageElems = nowPlaying.getElementsByTagName("art")
    const image =  imageElems.length > 0 ? imageElems[0].innerHTML : ""
    const imageDecoded = new DOMParser().parseFromString(image, "text/html").documentElement.textContent;

    handler.updateNowPlaying(speakerId, track, artist, album, imageDecoded, status)

}

function parseVolumeMessage(volume, speakerId, handler) {
    const targetElem = volume.getElementsByTagName("targetvolume")
    const targetVolume = targetElem.length > 0 ? targetElem[0].innerHTML : ""

    const actualElem = volume.getElementsByTagName("actualvolume")
    const actualVolume = actualElem.length > 0 ? actualElem[0].innerHTML : ""

    handler.updateVolume(speakerId, actualVolume, targetVolume)
}