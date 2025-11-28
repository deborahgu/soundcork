# soundcork
Intercept API for Bose SoundTouch after they turn off the servers

## Status

This project is pre-alpha. We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for more information, and the project [milestones](https://github.com/deborahgu/soundcork/milestones?sort=title&direction=asc) for our goals.

## Background
[Bose has announced that they are shutting down the servers for the SoundTouch system in February, 2026. ](https://www.bose.com/soundtouch-end-of-life) When those servers go away, certain network-based functionality currently available to SoundTouch devices will stop working.

This is an attempt to reverse-engineer those servers so that users can continue to use the full set of SoundTouch functionality after Bose shuts the official servers down.

### Context

[As described here](https://flarn2006.blogspot.com/2014/09/hacking-bose-soundtouch-and-its-linux.html), it is possible to access the underlying server by creating a USB stick with an empty file called **remote_services** and then booting the SoundTouch with the USB stick plugged in to the USB port in the back. From there we can then telnet (or ssh, but the ssh server running is fairly old) over and log in as root (no password).

### Pointing the Bose Speaker to a Local Server

Once logged into the speaker, you can go to `/opt/Bose/etc` and look at the file `SoundTouchSdkPrivateCfg.xml`:

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

Assumingly all four servers listed there will be shut down. From testing, the `marge` server is necessary for basic network functionality, and the `bmx` server seems to be required for TuneIn radio.

To point your system to another server, simple enter into read-write mode, edit the file (vi is available) and replace the URLs with your local URLs, and then reboot

	root@spotty:etc# rw                            
	root@spotty:etc# vi SoundTouchSdkPrivateCfg.xml
	root@spotty:etc# reboot

## Running, testing, and installing

### Installing

This has been written and tested with Python 3.12. Eventually it will be bundled as an installable app but for now you'll want a virtualenv.

1. Install virtualenv-wrapper if you don't already have it. This assumes bash;
modify as necessary.
	```sh
	sudo apt-install python3-pip
	pip install --user virtualenvwrapper
	mkdir -p $WORKON_HOME
	cat <<EOT >> ~/.bashrc
	export WORKON_HOME=${HOME}/.virtualenvs
	export PIP_VIRTUALENV_BASE=${HOME}/.virtualenvs
	export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
	source ~/.local/bin/virtualenvwrapper.sh
	EOT
	source ~/.bashrc
	```
1. Make a virtualenv for soundcork
	```bash
	mkvirtualenv -p3.12 soundcork
	workon soundcork
	```
1. Install the pre-requisites
	```bash
	pip install requirements.txt
	```

### Running

- To run in test
	```sh
	fastapi dev main.py
	# server is on http://127.0.0.1:8000
	```
- To run a prod server
	```sh
	fastapi run main.py
	```
- To run as a daemon
	```sh
	#Allen could you strip out paths
	#and copy in here our /etc/systemd/system/soundcork.service
	#and say how to
	sudo systemctl enable soundcork
	sudo systemctl start soundcork
	#i mean eventually
	#not now
	#ouch
	```
