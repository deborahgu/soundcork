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

The Marge endpoints seem to be for account/device information.

On bose, these go to `https://streaming.bose.com/`

#### GET /marge

Callers:

- Called at power on, and returns a 404


#### POST /marge/streaming/account/{account_id}/device/{device_id}/recent

Callers:

- Called at switching to a station

Payload:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<recent>
  <!-- see definition of source for defintion of these fields -->
  <lastplayedat>2025-11-14T02:04:54+00:00</lastplayedat>
  <sourceid>{source_id}</sourceid>
  <name>{station name}</name>
  <location>{location}</location>
  <contentItemType>{as appropriate}</contentItemType>
</recent>
```

Response:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<recent id="2239532516">
  <contentItemType>stationurl</contentItemType>
  <createdOn>2018-10-19T18:45:44.000+00:00</createdOn>
  <lastplayedat>2025-11-14T02:04:54.000+00:00</lastplayedat>
  <!-- see definition of source for defintion of these fields -->
  <location>{location}</location>
  <name>{station name}</name>
  <source id="{source_id}" type="Audio">
    <createdOn>2017-07-19T14:48:47.000+00:00</createdOn>
    <credential type="token">{credential}</credential>
    <name></name>
    <sourceproviderid>{source_provider_id}</sourceproviderid>
    <sourcename></sourcename>
    <sourceSettings/>
    <updatedOn>2017-07-19T14:48:47.000+00:00</updatedOn>
    <username></username>
  </source>
  <sourceid>{source_id}</sourceid>
  <updatedOn>2025-11-14T02:04:57.695+00:00</updatedOn>
</recent>
```


#### GET /marge/streaming/sourceproviders

Callers:

- Called at power on

Comments:

Returns the configured source providers (TUNEIN, PANDORA, etc)

Response:

```
<sourceProviders>
    <sourceprovider id="1">
        <createdOn>2012-09-19T12:43:00.000+00:00</createdOn>
        <name>PANDORA</name>
        <updatedOn>2012-09-19T12:43:00.000+00:00</updatedOn>
    </sourceprovider>
    ...
</sourceProviders>
```

#### POST /marge/streaming/support/power_on

Callers:

- Called at power on

Comments:

This sends a payload with a lot basic device info, but it returns a 404.
Maybe it once worked, but it does seem fine with a 404.

The info it sends:

- `device_id`
- `device_serial_number`
- `product_serial_number`
- `firmware_version`
- `gateway_ip_address`
- `ip_address`
- `macaddresses`
- `network_connection_type`
- `product_code`
- `type`


#### POST /marge/streaming/support/power_on

This sends a payload with a lot basic device info, but it returns a 404.
Maybe it once worked, but it does seem fine with a 404.

The info it sends:

- `device_id`
- `device_serial_number`
- `product_serial_number`
- `firmware_version`
- `gateway_ip_address`
- `ip_address`
- `macaddresses`
- `network_connection_type`
- `product_code`
- `type`

#### GET /marge/streaming/account/{account_id}/full

Callers:

- Called at power on

Comments:

- most of these are nested responses you can get from other calls, so should be easier than it looks to build this (and if we keep this spec doc, should be easy to clean up).

Returns:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<account id="{account_id}">
    <accountStatus>OK</accountStatus>
    <devices>
        <device deviceid="{device_id}">
            <!-- your hardware model here -->
            <attachedProduct product_code="SoundTouch Portable">
                <!-- Some of our hardware devices have multiple components, as you can see here. Others just have an empty element, e.g.
                `<components />`
                 I'm not currently clear of the difference.
                -->
                <components>
                    <component type="LIGHTSWITCH">
                        <componentlabel>soundtouch_controller</componentlabel>
                        <firmware-version></firmware-version>
                        <serialnumber></serialnumber>
                    </component>
                    <component type="SMSC">
                        <firmware-version>{version number}</firmware-version>
                        <serialnumber>{smsc_component_serial_number}</serialnumber>
                    </component>
                </components>
                <!-- as appropriate for you -->
                <productlabel>soundtouch_portable</productlabel>
                <serialnumber>{product_serial_number}</serialnumber>
            </attachedProduct>
            <!-- as appropriate for you -->
            <createdOn>2015-07-07T22:30:59.000+00:00</createdOn>
            <!-- as appropriate for you -->
            <firmwareVersion>{version number}</firmwareVersion>
            <!-- as appropriate for you -->
            <ipaddress>10.0.0.123</ipaddress>
            <name>{your user-set human-readable device name}</name>
            <presets>
                <preset buttonNumber="1">
                    <!-- these will vary by what's on the preset. in this case it's tunein -->
                    <containerArt>
                        http://cdn-profiles.tunein.com/s30913/images/logog.jpg?t=637822205260000000</containerArt>
                    <contentItemType>stationurl</contentItemType>
                    <createdOn>2021-11-25T16:35:27.000+00:00</createdOn>
                    <!--
                    Location:
                        - a playlist on a DLNA server: the DLNA identifier, not the user-set human-readable name, eg `playlist-4`
                        - an iHeart radio station: is a URL encoded HTML element, eg.  `&lt;IHeartCILocation id="5279" locationType="LIVE_STATION" /&gt;`
                        - TuneIn radio station: an endpoint to hit, e.g.  `/v1/playback/station/s30913`
                        - Pandora, a 19-digit code, not sure where to find it, e.g.  `4437376399097798052`
                    -->
                    <location>/v1/playback/station/s30913</location>
                    <!--
                    name:
                        - DNLA server: the name of the playlist.  
                        - TuneIn: call letters.
                        - iHeart: a station name.
                    -->
                    <name>WKRP</name>
                    <!-- source id  seems to be per-service (eg DLNA server, TuneIn, Pandora, etc.) -->
                    <source id="{source_id}" type="Audio">
                        <createdOn>2017-07-19T14:48:47.000+00:00</createdOn>
                        <!-- credential:
                            - For DLNA we can ignore
                            - For TuneIn, this is a JWT for the BMX API, and we can ignore
                            - For iHeart, this is f"{a code from where?}-{your login username for the service}"
                            - for Pandora, <credential type="token">{account_id}_[pandora_account]</credential>
                        -->
                        <credential type="token">{authentication credentials}</credential>
                        <!--
                        name:
                            - for a DLNA playlist name is the UPNP GUID which you can get from your DLNA server
                            - for iHeart, it's a login username (email address)
                            - For Pandora, name of the station
                            - for TuneIn, empty
                        -->
                        <name></name>
                        <!-- sourceprovider ID returned by /marge/streaming/sourceproviders -->
                        <sourceproviderid>1</sourceproviderid>
                        <!--
                        sourcename:
                            - for iHeart, a login username (email address)
                        -->
                        <sourcename></sourcename>
                        <sourceSettings />
                        <!-- as appropriate for you -->
                        <updatedOn>2017-07-19T14:48:47.000+00:00</updatedOn>
                        <!-- username:
                            - for a DLNA: the playlist UPNP GUID which you can get from your DLNA server
                            - for iHeart, login username (email address)
                            -  for Pandora, Pandora account name (email address)
                        -->
                        <username></username>
                    </source>
                    <!-- as appropriate for you -->
                    <updatedOn>2024-12-30T16:01:07.000+00:00</updatedOn>
                    <!--
                    username:
                        - TuneIn: station call numbers
                    -->
                    <username>WKRP</username>
                </preset>
                <!-- this will repeat for each preset button -->
            </presets>
            <recents>
                <recent id="{recent_id}">
                    <contentItemType></contentItemType>
                    <!-- as appropriate for you -->
                    <createdOn>2025-10-28T04:00:33.000+00:00</createdOn>
                    <lastplayedat>2025-10-28T04:00:29.000+00:00</lastplayedat>
                    <!-- See note above about defining location. -->
                    <location></location>
                    <!-- See note above about defining name. -->
                    <name></name>
                    <!-- See note above about defining source_id . -->
                    <source id="" type="Audio">
                        <!-- See note above about defining these elements. -->
                        <createdOn>2015-07-13T04:23:12.000+00:00</createdOn>
                        <credential type="token"></credential>
                        <name></name>
                        <sourceproviderid></sourceproviderid>
                        <sourcename></sourcename>
                        <sourcesettings />
                        <updatedon>2015-07-13t04:23:12.000+00:00</updatedon>
                        <username></username>
                    </source>
                    <sourceid>{same as source id=""}</sourceid>
                    <updatedOn>2025-10-28T04:00:33.000+00:00</updatedOn>
                </recent>
                <!-- recents will repeat for a long list, however, they appear to repeat identically across all devices -->
            </recents>
            <serialNumber>{device serial number}</serialNumber>
            <!-- as appropriate for you -->
            <updatedOn>2025-08-15T23:08:50.000+00:00</updatedOn>
        </device>
    </devices>
    <mode>global</mode>
    <!-- as appropriate for you -->
    <preferredLanguage>en</preferredLanguage>
    <providerSettings>
        <providerSetting>
            <boseId>{account_id}</boseId>
            <keyName>ELIGIBLE_FOR_TRIAL</keyName>
            <value>true</value>
            <!-- Not sure about providerId -->
            <providerId>14</providerId>
        </providerSetting>
    </providerSettings>
    <sources>
        <!-- These sources are defined exactly the same way that they are in the <recents>  element. -->
    </sources>
</account>
```


#### GET /marge/streaming/account/{account_id}/provider_settings

Callers:

- Called at power on

Comments:

- most of these are nested responses you can get from other calls, so should be easier than it looks to build this (and if we keep this spec doc, should be easy to clean up).

Returns:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<providerSettings>
  <providerSetting>
    <boseId>{account_id}</boseId>
    <keyName>ELIGIBLE_FOR_TRIAL</keyName>
    <value>true</value>
    <providerId>14</providerId>
  </providerSetting>
</providerSettings>
```

#### GET /marge/streaming/software/update/account/{account_id}

Callers:

- Called at power on

Comments:

On first post-power on call, returns nothing. Later in same sequence, goes again and has a response.

Response:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<software_update>
  <softwareUpdateLocation></softwareUpdateLocation>
</software_update>
```

### Bmx

The BMX endpoints appear to be for streaming radio stations, possibly only for TuneIn.

On bose, these go to `https://content.api.bose.io/bmx/`

In various places in these docs, instead of writing "`[placeholder for real
station]`" or the like, I am using the specific placeholder of the radio station
`WKRP in Cincinnati`. This will vary by station.

#### GET /bmx

Possibly this is a fake call, need to verify.

Callers:

- Called at power on, and returns 
```json
{"fault":{"faultstring":"Unable to identify proxy for host: content and url: \/bmx\/","detail":{"errorcode":"messaging.adaptors.http.flow.ApplicationNotFound"}}}
```

#### GET /bmx/registry/v1/services


Callers:

- Called at power on

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

Callers:

- Called at switching to a station

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

Callers:

- Called at switching to a station

Comments:

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

Comment:

We think this might be analytics and we can ignore it.

Querystring:

`/bmx/tunein/v1/report?stream_id={id}&guide_id={id}&listen_id={id}&stream_type={type}`

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

other possibilities:

```json
{
  "eventType":"STOP",
  "reason":"USER_STOP"
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

other possibilities:

```json
{}
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

## Callers

### power on

1. /bmx/
1. /marge/streaming/support/power_on
1. /marge
1. /bmx/registry/v1/services
1. /marge/streaming/sourceproviders
1. /marge/streaming/account/3380435/full
1. /marge/streaming/software/update/account/3380435
1. /marge/streaming/account/3380435/provider_settings
1. /marge/streaming/software/update/account/3380435

### switch to a station

1. /bmx/tunein/v1/report
1. /bmx/tunein/v1/playback/station/s30913
1. /bmx/tunein/v1/token
1. /bmx/tunein/v1/playback/station/s30913
1. /marge/streaming/account/3380435/device/B0D5CC0391DB/recent
1. /bmx/tunein/v1/report