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


## Config - AWS Secrets Manager
### in the AWS Console
create secrets in secrets manager `my_secret_name`
* `proxy_mnemonic`. Mnemonic of the balance proxy (for the `from_addresses`)
* `from_addresses`. List of addresses from which the funds will be swept
* `to_address`. Address to which the funds will be sent to
* `endpoint`. Websocket RPC endpoint to connect to the Moonbeam network

create iam policy to read secrets for only the specific secrets it needs (by arn)  `my_secret_name-my_service_account-read` 
* use the arn of the secret you created above

create `my_service_account` iam user 
* by access key only (no console access)
* with that `my_secret_name-my_service_account-read` policy only

### on the linux machine
create linux user `my_service_account`, switch to that user 
#### setup python virtual env (recommended) 
inside the sweep_tool directory
```
python3 -m venv venv
source ./venv/bin/activate
python -m pip install -r requirements.txt

```
install awscli2 via pip
https://pypi.org/project/awscliv2/

```
python -m pip install awscliv2
awsv2 --install
```
add alias for aws 
```
vim ~/.bashrc
# alias aws='awsv2'
source ~/.bashrc 
```

run `aws configure` on the `my_service_account` user to apply aws creds 


#### test access to secret
from the linux machine, `my_service_account` account
```
aws secretsmanager get-secret-value --secret-id "MY_ARN_GOES_HERE"
```


## Usage

```bash
$> python3 sweep.py --help

usage: sweep.py [-h] [-c CONFIG] [-l LEAVE_FREE]

Balance sweeping tool for Moonbeam

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        config file path (default: .config.json)
  -l LEAVE_FREE, --leave_free LEAVE_FREE
                        how many tokens to keep in source accounts (default: 10)
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
