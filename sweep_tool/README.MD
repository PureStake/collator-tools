Sweep Tool
======================

Tool to automate perodic sweeping of funds from one or multiple wallets (such as collator wallets) to another (such as a delegation wallet) in Moonbeam networks.
The script will run every round (at around the half point of the round)

## Install

Make sure you install the required packages on whichever user will run the script, using the following command
```
pip3 install -r requirements.txt
```

## Config

Set up a JSON config file with the following keys (see example .config.example):
```
proxy_mnemonic: Balance proxy (for the from_addresses) mnemonic
from_addresses: List of addresses from which the funds will be swept
to_address: Address to which the funds will be sent to
endpoint: Websocket RPC endpoint
```

## Usage

```
python3 sweep.py --help
usage: sweep.py [-h] [--config CONFIG] [--keep KEEP]

Balance sweeping tool for Moonbeam

optional arguments:
  -h, --help       show this help message and exit
  --config CONFIG  config file path (default: .config)
  --keep KEEP      how many tokens to keep in source accounts (default: 10)
```

Once the script is running, it will check every 10 minutes for the current block, and if it is past the block scheduled for the next sweep (at the half-point of the round) it will run the sweep and send any available funds from the source addresses to the destination address.

## Setting up as a service

To ensure the tool is always running, you can set the script to run as a systemd service, by configuring the following service file in **/etc/systemd/system/collator-sweep.service**:
```
[Unit]
Description=Collator Balance Sweep
After=multi-user.target

[Service]
Type=simple
Restart=always
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 <PYTHON SCRIPT PATH> \
        --config <CONFIG FILE PATH>

[Install]
WantedBy=multi-user.target
```
