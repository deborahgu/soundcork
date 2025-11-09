# API specification

This specification is not documented anywhere we can find, by Bose. All the
identified calls in this spec were identified by proxying (as described at
[the README](../README.md#Context))  and identifying the calls and responses
made between our speakers and the Bose servers.

If you have different services defined on your speakers, it's possible that
we've missed some calls and responses that are relevant for you.

Implemented endpoints will always be documented in the generated open API specification.

## Spec

The speaker will send headers, which includes IP addresses, server hostname,
user agent, API key, etc. Unless otherwise specified, we are not parsing any of
these headers,  so they are not documented here.

### Marge


### Bmx

The BMX endpoints appear to be for streaming radio stations.

In various places in these docs, instead of writing "`[placeholder for real
station]`" or the like, I am using the specific placeholder of the radio station
`WKRP in Cincinnati`. This will vary by station.

#### GET /bmx/registry/v1/services

Response:

Comments:
-  We don't yet know what `askAgainAfter` indicates, or if it matters.  It possible that it's  milliseconds (the numbers do work out to be about 20 minutes in milliseconds, plus or minus a certain amount of randomized jitter)
- The return services are Internet radio services (e.g. TuneIn)
- ID values, types of stream, etc., will vary by the particular service.

```json
{
  "_links": {
    "bmx_services_availability": {
      "href": "../servicesAvailability"
    }
  },
  "askAgainAfter": 1277728,
  "bmx_services": [
    {
      "_links": {
        "bmx_navigate": {
          "href": "/v1/navigate"
        },
        "bmx_token": {
          "href": "/v1/token"
        },
        "self": {
          "href": "/"
        }
      },
      "askAdapter": false,
      "assets": {
        "color": "#000000",
        "description": "A string here with copy about the particular service."
        "icons": {
          "defaultAlbumArt": "https://.host.of.your.soundcork.api/path.to.image",
          "largeSvg": "https://.host.of.your.soundcork.api/path.to.image",
          "monochromePng": "https://.host.of.your.soundcork.api/path.to.image",
          "monochromeSvg": "https://.host.of.your.soundcork.api/path.to.image",
          "smallSvg": "https://.host.of.your.soundcork.api/path.to.image"
        },
        "name": "Name of the service"
      },
      "authenticationModel": {
        "anonymousAccount": {
          "autoCreate": true,
          "enabled": true
        }
      },
      "baseUrl": "https://host.of.your.soundcork.api/bmx/URL_of_the_service",
      "id": {
        "name": " name of the service",
        "value": 1
      },
      "streamTypes": [
        "liveRadio",
        "onDemand"
      ]
    }
  ]
}
```
#### GET /bmx/{name of service}/v1/playback/station/{station ID}

Response:

```json
{
  "_links": {
    "bmx_favorite": {
      "href": "/v1/favorite/{station ID}"
    },
    "bmx_nowplaying": {
      "href": "/v1/now-playing/station/{station ID}",
      "useInternalClient": "ALWAYS"
    },
    "bmx_reporting": {
      "href": "/v1/report?stream_id=[an ID]&guide_id={station ID}&listen_id=[an ID]&stream_type=[a stream type]"
    }
  },
  "audio": {
    "hasPlaylist": true,
    "isRealtime": true,
    "maxTimeout": 60,
    "streamUrl": "https://nebcoradio.com:8443/WKRP/"
    "streams": [
      {
        "_links": {
          "bmx_reporting": {
            "href": "/v1/report?stream_id=[an ID]&guide_id={station ID}&listen_id=[an ID]&stream_type=[a stream type]"
          }
        },
        "bufferingTimeout": 20,
        "connectingTimeout": 10,
        "hasPlaylist": true,
        "isRealtime": true,
        "streamUrl": "https://nebcoradio.com:8443/WKRP/"
      }
    ]
  },
  "imageUrl": "http://the.streaming.services.URL/{station ID}/images/logog.png?t=[a  numeric value]",
  "isFavorite": false,
  "name": "WKRP/WKRP in Cincinnati",
  "streamType": "[a stream type]"
}
```

####  TuneIn specific

These might be specific to TuneIn, or they might be valid for any service, not sure yet.

##### POST /bmx/tunein/v1/token

Request payload:

```json
{
  "grant_type": "refresh_token",
  "refresh_token": "your refresh jwt"
}
```

Response:
```json
{
  "access_token": "an access jwt"
}
```

#####  POST /bmx/tunein/v1/report
Payload:

Sample payload included here. Not sure yet what all of these are used for.

```json
{
  "timeStamp": "2025-10-31T05:38:55+0000",
  "eventType": "START",
  "reason": "USER_SELECT_PLAYABLE",
  "timeIntoTrack": 0,
  "playbackDelay": 6664
}
```

Response:


```json
{
  "_links": {
    "self": {
      "href": "/v1/report?stream_id=[an ID]&guide_id={station ID}&listen_id=[an ID]&last_titt=0&duration_balance=0&stream_type=liveRadio"
    }
  },
  "nextReportIn": 1800
}
```

##### GET /bmx/tunein/v1/playback/station/{station ID}


Response:

```json
{
  "_links": {
    "bmx_favorite": {
      "href": "/v1/favorite/{station ID}"
    },
    "bmx_nowplaying": {
      "href": "/v1/now-playing/station/{station ID}",
      "useInternalClient": "ALWAYS"
    },
    "bmx_reporting": {
      "href": "/v1/report?stream_id=[an ID]&guide_id={station ID}&listen_id=[an ID]&stream_type=liveRadio"
    }
  },
  "audio": {
    "hasPlaylist": true,
    "isRealtime": true,
    "maxTimeout": 60,
    "streamUrl": "https://nebcoradio.com:8443/WKRP",
    "streams": [
      {
        "_links": {
          "bmx_reporting": {
            "href": "/v1/report?stream_id=[an ID]&guide_id={station ID}&listen_id=[an ID]&stream_type=liveRadio"
          }
        },
        "bufferingTimeout": 20,
        "connectingTimeout": 10,
        "hasPlaylist": true,
        "isRealtime": true,
        "streamUrl": "https://nebcoradio.com:8443/WKRP"
      }
    ]
  },
  "imageUrl": "http://cdn-profiles.tunein.com/{station ID}/images/logog.png?t=636602555323000000",
  "isFavorite": false,
  "name": "WKRP/WKRP  in Cincinnati",
  "streamType": "liveRadio"
}
```
