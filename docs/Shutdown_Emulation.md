# Emulating Bose Server shutdown

On the assumption that the servers listed in ```/opt/Bose/etc/``` are the ones being shut down:

	<?xml version="1.0" encoding="utf-8"?>
	<SoundTouchSdkPrivateCfg>
  	<margeServerUrl>https://streaming.bose.com</margeServerUrl>
  	<statsServerUrl>https://events.api.bosecm.com</statsServerUrl>
  	<swUpdateUrl>https://worldwide.bose.com/updates/soundtouch</swUpdateUrl>
  	<usePandoraProductionServer>true</usePandoraProductionServer>
  	<isZeroconfEnabled>true</isZeroconfEnabled>
  	<saveMargeCustomerReport>false</saveMargeCustomerReport>
  	<bmxRegistryUrl>https://content.api.bose.io/bmx/registry/v1/services</bmxRegistryUrl>
	</SoundTouchSdkPrivateCfg>
	
Then we should be able to test out what the results of the server shutdown will be by setting all of the entries to non-existent servers and restarting.

Doing so and trying to play the following sources results:

* DLNA server: works, but throws some errors.
* TuneIn radio: fails.
* IHeart Radio: works.
* Pandora: works.
* SiriusXM: fails

Adding additional speakers to a group also seems to work.

