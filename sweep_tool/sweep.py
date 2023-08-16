#!/usr/bin/env python3

from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.exceptions import SubstrateRequestException
from substrateinterface.base import KeypairType
from hashlib import blake2b
import json, schedule, time, argparse, logging, sys, os

def run_sweep():
  global next_sweep
  # Start substrate inteface
  substrate = SubstrateInterface(url = config["endpoint"])

  # Get unit and decimals from system_properties
  unit_name = substrate.properties["tokenSymbol"]
  decimals = 10**(substrate.properties["tokenDecimals"])

  # Get current block
  current_block = substrate.get_block()
  current_block_number = current_block["header"]["number"]

  if current_block_number >= next_sweep:
    # Time to sweep tokens
    logging.info(f"Current block is {current_block_number}, next sweep is on block {next_sweep}")

    # Get any pending announcements
    announcements = get_announcements(substrate)
    announce_block = None
    set_new_next = False

    for from_address in config["from_addresses"]:
      from_address = from_address.lower()
      logging.info(f"\tSweeping funds from {from_address} to {config['to_address']}")

      # Retrieve free balance from chain, subtract balance we want to keep
      from_balance = substrate.query(module="System",storage_function="Account",params=[from_address]).value
      to_sweep = from_balance["data"]["free"] + from_balance["data"]["reserved"] - config["leave_free"]*decimals

      if to_sweep <= 0:
        logging.info("\t\tNo funds to sweep")
        continue

      logging.info(f"\t\tSweepable funds: {round(to_sweep/decimals, 2)} {unit_name}")

      # Check if there is a pending announce
      if (config["proxy_delay"] > 0):
        if (from_address in announcements):
          if (len(announcements[from_address]) > 1):
            logging.warning(f"\t\tWarning, there are multiple proxy announcements for {from_address}")
          skip_account = False
          for announcement in announcements[from_address]:
            amount = announcement[1]
            when_executable = announcement[0]
            logging.info(f"\t\tExecuting announcement for a sweep of {round(amount/decimals, 2)} {unit_name}")
            if (amount > to_sweep):
              logging.error(f"\t\tWARNING! The announcement would put the account below desired balance. Skipping")
              #skip_account = True
              #break
              continue
            elif (when_executable > current_block_number):
              logging.warning(f"\t\tThe announcement is not ready yet. Waiting until it is ready (block {when_executable})")
              skip_account = True
              next_sweep = when_executable
              set_new_next = True
              break
            else:
              execute_success = execute_announcement(from_address, amount, substrate)
              if (not execute_success):
                #skip_account = True
                #break
                continue
              else:
                to_sweep -= amount
          if skip_account:
            logging.error(f"\t\tFailed to execute an announcement, skipping account {from_address}")
            continue

      # Retrieve free balance from chain, subtract balance we want to keep
      from_balance = substrate.query(module="System",storage_function="Account",params=[from_address]).value
      to_sweep = from_balance["data"]["free"] + from_balance["data"]["reserved"] - config["leave_free"]*decimals

      if to_sweep <= 0:
        logging.info("\t\tNo funds to sweep")
        continue

      # Compose the transfer call
      transfer_extrinsic = substrate.compose_call(
        call_module   = "Balances",
        call_function = "transfer_keep_alive",
        call_params   = {
          "dest":  config["to_address"],
          "value": to_sweep,
        }
      )

      if config["proxy_delay"] == 0:
        # Send it via proxy
        proxy_call(transfer_extrinsic, from_address, substrate)
      
      else: # If we are using proxy with delay
        # Get the encoded hash of the call, to use with the proxy announcement
        encoded_call_hash = "0x" + blake2b(transfer_extrinsic.data.get_next_bytes(1000), digest_size=32).hexdigest()
        # Compose the announcement call
        announce_extrinsic = substrate.compose_call(
          call_module   = "Proxy",
          call_function = "announce",
          call_params   = {
            "real":  from_address,
            "call_hash": encoded_call_hash,
          }
        )
        # Execute the call
        logging.info(f"\t\tScheduling announcement for sweep of {round(to_sweep/decimals, 2)} {unit_name} ({to_sweep})")
        announce_block = announce_call(announce_extrinsic, substrate)

    if not set_new_next:
      if (config["proxy_delay"] == 0):
        # Schedule next sweep, in the middle of the next round
        current_round = substrate.query(module="ParachainStaking",storage_function="Round")
        round_length = current_round.value["length"]
        next_sweep = current_round.value["first"] + int(0.5 * round_length) + int(config["round_frequency"] * round_length)
      else:
        # Schedule next sweep for when the announcement is ready
        if (announce_block):
          next_sweep = announce_block + config["proxy_delay"]
        else:
          # if there was an error announcing or no funds to sweep, try again in 100 blocks (does this eat fees? what else to do?)
          next_sweep = current_block_number + 100

    logging.info(f"\tNext sweep scheduled for block {next_sweep}")


def proxy_call(call, address_behind_proxy, substrate):
  """
  This is the function executes the transfer extrinsic, using a proxy
  """

  # Load the keypair from the mnemonic in the config
  proxy_keypair = Keypair.create_from_mnemonic(config["proxy_mnemonic"], crypto_type=KeypairType.ECDSA)
  # Compose the proxy call
  proxy_call = substrate.compose_call(
    call_module   = "Proxy",
    call_function = "proxy",
    call_params   = {
      "real":             address_behind_proxy,
      "force_proxy_type": None,
      "call":             substrate.create_unsigned_extrinsic(call).serialize()
    }
  )
  # Sign the call
  extrinsic = substrate.create_signed_extrinsic(call=proxy_call, keypair=proxy_keypair)

  try:
    # Send the call
    receipt = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)

    for event in receipt.triggered_events:
        if event.value["event_id"] == "ExtrinsicFailed":
            logging.error(f"\t\tProxy call failed. Extrinsic: {receipt.extrinsic_hash}")
            return False
        if event.value["event_id"] == "ProxyExecuted":
            if "Err" in event.value["attributes"]["result"]:
                logging.error(f"\t\tProxy call failed. Extrinsic: {receipt.extrinsic_hash}")
                return False
    else:
      logging.info("\t\tExtrinsic '{}' sent and included in block '{}'".format(receipt.extrinsic_hash, receipt.block_hash))
      return True

  except SubstrateRequestException as e:
    logging.error("\t\tProxy call failed: {}".format(e))
    return False

def announce_call(call, substrate):
  """
  This is the function executes the announce extrinsic, using the proxy
  """

  # Load the keypair from the mnemonic in the config
  proxy_keypair = Keypair.create_from_mnemonic(config["proxy_mnemonic"], crypto_type=KeypairType.ECDSA)

  # Sign the call
  extrinsic = substrate.create_signed_extrinsic(call=call, keypair=proxy_keypair)

  try:
    # Send the call
    receipt = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
    logging.info("\t\tAnnouncement '{}' sent and included in block '{}'".format(receipt.extrinsic_hash, receipt.block_hash))
    return substrate.get_block(block_hash=receipt.block_hash)["header"]["number"]

  except SubstrateRequestException as e:
    logging.error("\t\tAnnounce call failed: {}".format(e))
    return False

def execute_announcement(real, amount, substrate):
  # Load the keypair from the mnemonic in the config
  proxy_keypair = Keypair.create_from_mnemonic(config["proxy_mnemonic"], crypto_type=KeypairType.ECDSA)

  # Compose the transfer call
  transfer_extrinsic = substrate.compose_call(
    call_module   = "Balances",
    call_function = "transfer_keep_alive",
    call_params   = {
      "dest":  config["to_address"],
      "value": amount,
    }
  )

  # Compose the proxyAnnounced call
  proxy_call = substrate.compose_call(
    call_module   = "Proxy",
    call_function = "proxy_announced",
    call_params   = {
      "delegate":         config["proxy_address"],
      "real":             real,
      "force_proxy_type": None,
      "call":             substrate.create_unsigned_extrinsic(transfer_extrinsic).serialize()
    }
  )

  # Sign the call
  extrinsic = substrate.create_signed_extrinsic(call=proxy_call, keypair=proxy_keypair)

  try:
    # Send the call
    receipt = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)

    for event in receipt.triggered_events:
      # Search for ExtrinsicFailed event. Not sure why this doesnt trigger an exception
      if event.value["event_id"] == "ExtrinsicFailed":
          logging.error("\t\tProxyAnnounced extrinsic FAILED! Extrinsic '{}' included in block '{}'".format(receipt.extrinsic_hash, receipt.block_hash))
          return False
    
    logging.info("\t\tProxyAnnounced '{}' sent and included in block '{}'".format(receipt.extrinsic_hash, receipt.block_hash))
    return True

  except SubstrateRequestException as e:
    logging.error("\t\tProxyAnnounced call failed: {}".format(e))
    return False


def get_announcements(substrate):
  ''' Returns a dict of announcement, with the real account as key and (when executable, expected balance transfer) as values '''
  # How many tokens to keep
  decimals = 10**(substrate.properties["tokenDecimals"])
  to_keep = config["leave_free"] * decimals

  announcements = {}
  announcement_query = substrate.query(module="Proxy",storage_function="Announcements",params=[config["proxy_address"]])
  for announcement in announcement_query.value[0]:
      height = announcement["height"]
      at_hash = substrate.get_block_hash(height)
      # Get the balance of the account when the announcement was made
      balance_query = substrate.query(module="System",storage_function="Account",params=[announcement["real"]], block_hash=at_hash).value
      balance = balance_query["data"]["free"] + balance_query["data"]["reserved"]
      if announcement["real"] not in announcements:
         # this is the expected value of the balance transfer call
          announcements[announcement["real"]] = [(height+config["proxy_delay"], balance-to_keep)]
      else:
          announcements[announcement["real"]] += [(height+config["proxy_delay"], balance-to_keep)]
  return announcements


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Balance sweeping tool for Moonbeam')
  parser.add_argument('-c', '--config',
    help  = 'config file path (default: .config.json)',
  )
  args = parser.parse_args()

  # Set logging level
  logging.basicConfig(stream=sys.stdout, level=logging.INFO)
  # Block number for when the next balance sweep will happen
  next_sweep = 0

  config = {}
  # Load config from config file
  if args.config:
    with open(args.config) as f:
      config = json.loads(f.read())

  # Load config from ENV
  if "SWEEP_PROXY_MNEMONIC" in os.environ:
    config["proxy_mnemonic"] = os.environ["SWEEP_PROXY_MNEMONIC"]
  if "SWEEP_TO_ADDRESS" in os.environ:
    config["to_address"] = os.environ["SWEEP_TO_ADDRESS"]
  if "SWEEP_ENDPOINT" in os.environ:
    config["endpoint"] = os.environ["SWEEP_ENDPOINT"]
  if "SWEEP_FROM_ADDRESSES" in os.environ:
    config["from_addresses"] = os.environ["SWEEP_FROM_ADDRESSES"].split(",")
  if "SWEEP_ROUND_FREQUENCY" in os.environ:
    config["round_frequency"] = int(os.environ["SWEEP_ROUND_FREQUENCY"])
  if "SWEEP_PROXY_DELAY" in os.environ:
    config["proxy_delay"] = int(os.environ["SWEEP_PROXY_DELAY"])
  if "SWEEP_LEAVE_FREE" in os.environ:
    config["leave_free"] = int(os.environ["SWEEP_LEAVE_FREE"])

  # Load up the mnemonic to get the address of the proxy
  config["proxy_address"] = Keypair.create_from_mnemonic(config["proxy_mnemonic"], crypto_type=KeypairType.ECDSA).ss58_address

  # Schedule the sweep for every 10 minutes, but only actualy does anything if we're at (or past) the correct block
  schedule.every(10).minutes.do(run_sweep)
  # Run an initial sweep as well
  run_sweep()

  while True:
    # Try to run any pending sweep every 5 minutes
    schedule.run_pending()
    time.sleep(5 * 60)