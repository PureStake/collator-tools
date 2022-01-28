from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.exceptions import SubstrateRequestException
from substrateinterface.base import KeypairType
import json
import schedule, time
import argparse
import logging, sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

next_sweep = 0

def run_sweep():
    global next_sweep
    # Start substrate inteface
    substrate = SubstrateInterface(
        url=config["endpoint"]
    )
    # Get unit and decimals from system_properties
    unit_name = substrate.properties["tokenSymbol"]
    decimals = 10**(substrate.properties["tokenDecimals"])

    # Get current block
    current_block = substrate.get_block()
    current_block_number = current_block["header"]["number"]
    if current_block_number >= next_sweep:
        # Time to sweep tokens
        logging.info(f"Current block is {current_block_number}, next sweep is on block {next_sweep}")
        for from_address in config['from_addresses']:
            logging.info(f"  Sweeping funds from {from_address} to {config['to_address']}")
            # Retrieve free balance from chain, subtract balance we want to keep
            from_balance = substrate.query(module='System',storage_function='Account',params=[from_address])
            to_sweep = from_balance.value["data"]["free"] - leave_free*decimals
            if to_sweep <= 0:
                logging.info("    No funds to sweep")
            else:
                logging.info(f"    Sweepable funds: {round(to_sweep/decimals, 2)} {unit_name}")
                # Compose the transfer call
                transfer_extrinsic = substrate.compose_call(
                    call_module='Balances',
                    call_function='transfer',
                    call_params={
                        'dest': config["to_address"],
                        'value': to_sweep
                    }
                )
                # Send it via proxy
                proxy_call(transfer_extrinsic, from_address, substrate)
        # Schedule next sweep, in the middle of the next round
        current_round = substrate.query(module='ParachainStaking',storage_function='Round')
        round_length = current_round.value["length"]
        next_sweep = current_round.value["first"] + current_round.value["length"] + int(round_length/2)
        logging.info(f"  Next sweep scheduled for block {next_sweep}")


def proxy_call(call, real, substrate):
    ''' This is the function executes the transfer extrinsic, using a proxy '''
    # Load the keypair from the mnemonic in the config
    proxy_keypair = Keypair.create_from_mnemonic(config["proxy_mnemonic"], crypto_type=KeypairType.ECDSA)
    # Compose the proxy call
    proxy_call = substrate.compose_call(
        call_module='Proxy',
        call_function='proxy',
        call_params={
            'real': real,
            'force_proxy_type': None,
            'call': substrate.create_unsigned_extrinsic(call).serialize()
        }
    )
    # Sign the call
    extrinsic = substrate.create_signed_extrinsic(call=proxy_call, keypair=proxy_keypair)
    try:
        # Send the call
        receipt = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
        for event in receipt.triggered_events:
            # Search for Err in the extrinsic which executed the proxy
            if event.value["event_id"] == "ProxyExecuted":
                if "Err" in event.value["attributes"]:
                    logging.error("    Proxy call failed")
                    return False
        else:
            logging.info("    Extrinsic '{}' sent and included in block '{}'".format(receipt.extrinsic_hash, receipt.block_hash))
            return True

    except SubstrateRequestException as e:
        logging.error("    Proxy call failed: {}".format(e))
        return False

parser = argparse.ArgumentParser(description='Balance sweeping tool for Moonbeam')
parser.add_argument('--config', help='config file path (default: .config)', default=".config")
parser.add_argument('--keep', help='how many tokens to keep in source accounts (default: 10)', default=10)
args = parser.parse_args()

# Load config as a dict
with open(args.config) as f:
    config = json.loads(f.read())

leave_free = args.keep

# Schedule the sweep for every 10 minutes, but only actualy does anything if we're at (or past) the correct block
schedule.every(10).minutes.do(run_sweep)
# Run an initial sweep as well
run_sweep()

while True:
    schedule.run_pending()
    time.sleep(1)