import { SoundTouchHandler, loadSpeakers } from "./soundtouch_websocket.js";

export class MiniAppHandler extends SoundTouchHandler {
    connected(speakerId) {
        console.log("connected!")
    }
    updateNowPlaying(speakerId, track, artist, album, imageUrl, status) {
        $("#" + speakerId + "-info").find("div.np-info").html(track + " - " + artist)
        const sidebarDiv = $("#sidebar-" + speakerId)
        if (sidebarDiv.length > 0) {
            sidebarDiv.find("span.now_playing").html(track)
            sidebarDiv.find("img").attr("src", imageUrl)
        }
    }
    updateVolume(speakerId, actualVolume, targetVolume) {
        $("#" + speakerId + "-info").find("div.volume").html("Volume: " + actualVolume)
        const sidebarDiv = $("#sidebar-" + speakerId)
        if (sidebarDiv.length > 0) {
            console.log("in sidebar")
            sidebarDiv.find("input.slider")[0].value = actualVolume
        }
    }
}

const accountIdCookie = await window.cookieStore.get("soundcork_account_id")
const accountId = accountIdCookie.value

const handler = new MiniAppHandler()
loadSpeakers(accountId, handler)

