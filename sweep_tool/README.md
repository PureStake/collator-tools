Sweep Tool
======================

Automate perodic sweeping of funds from one or multiple wallets (such as collator wallets) to another (such as a delegation wallet) in the Moonbeam networks.

The script will run every round (at around the half point of the round)

## Install

Make sure you install the required packages on whichever user will run the script, using the following command:

```bash
pip3 install -r requirements.txt
```

## Config

Set up a JSON config file with the following keys (see example .config.example):


* `proxy_mnemonic`. Mnemonic of the balance proxy (for the `from_addresses`)
* `from_addresses`. List of addresses from which the funds will be swept
* `to_address`. Address to which the funds will be sent to
* `endpoint`. Websocket RPC endpoint to connect to the Moonbeam network

## Usage

```bash
python3 sweep.py --help
usage: sweep.py [-h] [--config CONFIG] [--keep KEEP]

Balance sweeping tool for Moonbeam

optional arguments:
  -h, --help       show this help message and exit
  --config CONFIG  config file path (default: .config)
  --keep KEEP      how many tokens to keep in source accounts (default: 10)
```

Once the script is running, it will check every 10 minutes for the current block. If it is past the block scheduled for the next sweep (at the half-point of the round), it will run the sweep and send any available funds from the source addresses to the destination address.

## Setting up the script as a service

To ensure the tool is always running, you can set the script to run as a `systemd` service. Configure the following service file in `/etc/systemd/system/collator-sweep.service`:

```bash
[Unit]
Description=Collator Balance Sweep
After=multi-user.target

[Service]
Type=simple
Restart=always
Environment=PYTHONUNBUFFERED=1
ExecStart=<PYTHON SCRIPT PATH> \
        --config <CONFIG FILE PATH>

[Install]
WantedBy=multi-user.target
```
