#!/usr/bin/env python3
"""
Solana Trading Bot Prototype (Version 6)

This bot scrapes Dexscreener’s API for token profiles, categorizes tokens based on
predefined filters (e.g., minimum market cap, liquidity, pair age, transaction counts),
and only processes tokens that pass these filters. For tokens that qualify, it simulates
a buy order and monitors the token's price to trigger a sell when either a profit target
or stop-loss condition is met.

It supports both simulation and real transaction modes.
  
**WARNING:** Real transactions affect real funds. Test thoroughly on devnet before using mainnet.
"""

# ---------------------------
# Imports
# ---------------------------
import json
import time
import threading
import requests

# Low-level operations from solders
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey

# High-level RPC client for Solana
from solana.rpc.api import Client as SolanaClient
from solana.rpc.types import TxOpts

# ---------------------------
# CONFIGURATION
# ---------------------------
DEXSCEENER_API_URL = "https://api.dexscreener.com/token-profiles/latest/v1"

RISK_AMOUNT = 10                 # Risk amount per trade (simulation value)
PROFIT_TARGET_MULTIPLIER = 1.4    # E.g., sell when price doubles
STOP_LOSS_RATIO = 0.8             # E.g., sell if price falls to 80% of buy price

# Scoring threshold: only tokens with a score >= this value are considered.
MIN_SCORE_THRESHOLD = 2.0         

# Real transaction settings
REAL_TRANSACTIONS = True         # Set to True to execute real transactions
TEST_RECIPIENT = "RecipientPublicKeyHere"  # Replace with an actual recipient address for real trades
TRANSFER_LAMPORTS = 10_000_000    # For example, 0.01 SOL = 10,000,000 lamports

POLL_INTERVAL = 60              # Seconds between token fetches
POSITION_POLL_INTERVAL = 30     # Seconds between position monitoring

# ---------------------------
# WALLET & RPC CLIENT SETUP
# ---------------------------
def load_keypair(filepath="phantom-keypair.json"):
    """Load a keypair from a JSON file (expects a JSON array of numbers)."""
    with open(filepath, "r") as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

wallet = load_keypair("phantom-keypair.json")

rpc_url = "https://api.devnet.solana.com" if not REAL_TRANSACTIONS else "https://api.mainnet-beta.solana.com"
solana_client = SolanaClient(rpc_url)

# ---------------------------
# REAL TRANSACTION FUNCTION
# ---------------------------
def send_sol_transfer(recipient_address: str, lamports: int):
    """
    Send a SOL transfer transaction.
    
    Parameters:
      recipient_address (str): Recipient's public key (base58 string).
      lamports (int): Amount in lamports.
      
    Returns:
      The transaction response.
    """
    instr = transfer(TransferParams(
        from_pubkey=wallet.pubkey(),
        to_pubkey=Pubkey(recipient_address),
        lamports=lamports
    ))
    txn = Transaction()
    txn.add(instr)
    print("[INFO] Sending SOL transfer transaction...")
    response = solana_client.send_transaction(txn, wallet, opts=TxOpts(skip_preflight=False))
    print("[INFO] Transaction response:", response)
    return response

# ---------------------------
# ADDITIONAL FILTER FUNCTIONS
# ---------------------------
def verify_volume(token):
    """Simulate volume verification (replace with real logic if needed)."""
    volume = float(token.get("volumeUsd24Hr", 0))
    return volume > 0

def check_rug_status(token_address):
    """Simulate a Rugcheck.xyz API call (always returns True for simulation)."""
    return True

def check_supply(token):
    """Simulate checking if the token's supply is bundled (assume it's not bundled)."""
    return not token.get("supplyBundled", False)

def coin_in_blacklist(token):
    """Check if token is in coin blacklist from config."""
    coin_blacklist = load_config().get("coin_blacklist", [])
    token_address = token.get("tokenAddress", "").lower()
    return token_address in [x.lower() for x in coin_blacklist]

def dev_in_blacklist(token):
    """Check if token's developer is in dev blacklist from config."""
    dev_blacklist = load_config().get("dev_blacklist", [])
    dev_address = token.get("devAddress", "").lower()
    return dev_address in [x.lower() for x in dev_blacklist]

def load_config(filepath="config.json"):
    """Load configuration from a JSON file."""
    with open(filepath, "r") as f:
        return json.load(f)

# ---------------------------
# CATEGORIZATION FUNCTION
# ---------------------------
def categorize_token(token):
    """
    Categorize a token based on predefined filters.
    Returns a category string if it meets one of the criteria; otherwise, returns None.
    """
    try:
        liquidity = float(token.get("liquidityUsd", 0))
        fdv = token.get("fdvUsd", token.get("marketCapUsd", 0))
        fdv = float(fdv) if fdv else 0
        pair_age = float(token.get("pairAgeHours", 0))
        txns1h = float(token.get("txns1h", 0))
        txns24h = float(token.get("txns24h", 0))
        volume24h = float(token.get("volumeUsd24Hr", 0))
        volume6h = float(token.get("volumeUsd6h", 0))
        
        # Check blacklists and supply
        if coin_in_blacklist(token) or dev_in_blacklist(token) or not check_supply(token):
            return None
        if not verify_volume(token) or not check_rug_status(token.get("tokenAddress", "")):
            return None
        
        # Very Degen
        if (liquidity >= 10000 and fdv >= 100000 and 0 <= pair_age <= 48 and txns1h >= 30):
            return "Very Degen"
        # Degen
        if (liquidity >= 15000 and fdv >= 100000 and 1 <= pair_age <= 72 and txns1h >= 100):
            return "Degen"
        # Mid-Caps
        if (liquidity >= 100000 and fdv >= 1000000 and volume24h >= 1200000 and txns24h >= 30):
            return "Mid-Caps"
        # Old Mid-Caps
        if (liquidity >= 100000 and fdv >= 200000 and fdv <= 100000000 and 720 <= pair_age <= 2800 and volume24h >= 200000 and txns24h >= 2000):
            return "Old Mid-Caps"
        # Larger Mid Caps
        if (liquidity >= 200000 and fdv >= 1000000 and volume6h >= 150000):
            return "Larger Mid Caps"
        return None
    except Exception as e:
        print(f"[ERROR] Categorizing token: {e}")
        return None

# ---------------------------
# SCORING & FILTERING FUNCTIONS
# ---------------------------
def score_token(token):
    """
    Optionally calculate a score for the token.
    """
    try:
        market_cap = float(token.get("marketCapUsd", token.get("fdvUsd", 0)) or 0)
        liquidity = float(token.get("liquidityUsd", 0))
        volume24h = float(token.get("volumeUsd24Hr", 0))
        score = (market_cap / 100000) + (liquidity / 50000) + (volume24h / 1000000)
        return score
    except Exception as e:
        print(f"[ERROR] Scoring token: {e}")
        return 0

def filter_tokens(tokens, min_score=MIN_SCORE_THRESHOLD):
    """
    Filter tokens based on a minimum score.
    """
    filtered = []
    for token in tokens:
        s = score_token(token)
        if s >= min_score:
            token["score"] = s
            filtered.append(token)
    return filtered

# ---------------------------
# TRADE EXECUTION LOGIC
# ---------------------------
def execute_trade(token_address, action, amount):
    """
    Execute a trade for a token.
    In simulation mode, returns a fixed simulated price.
    In real transaction mode, sends a real SOL transfer.
    """
    if REAL_TRANSACTIONS:
        if action in ["buy", "sell"]:
            print(f"[REAL TRADE] {action.capitalize()} order for token {token_address}")
            return send_sol_transfer(TEST_RECIPIENT, TRANSFER_LAMPORTS)
        else:
            print("[REAL TRADE] Unknown action")
            return None
    else:
        print(f"[SIMULATION] Executing {action} order for token {token_address} with amount {amount}")
        simulated_price = 0.1
        return simulated_price

def buy_token(token):
    """
    If a token qualifies (by categorization, scoring, and risk checks), execute (or simulate) a buy.
    """
    category = categorize_token(token)
    token_score = score_token(token)
    token["score"] = token_score
    if category is None or token_score < MIN_SCORE_THRESHOLD or advanced_rug_pull_check(token):
        sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
        print(f"[FILTER] {sym} skipped (Category: {category}, Score: {token_score})")
        return None

    token_address = token.get("tokenAddress")
    if not token_address:
        print("[BUY] Token address not found; skipping.")
        return None

    trade_result = execute_trade(token_address, "buy", RISK_AMOUNT)
    if not trade_result:
        return None
    buy_price = 0.1  # In simulation, fixed price
    quantity = RISK_AMOUNT / buy_price
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    print(f"[BUY] {sym} | Category: {category} | Score: {token_score} | Bought {quantity} at price {buy_price}")
    return {"token": token, "buy_price": buy_price, "quantity": quantity}

def sell_token(position):
    """
    Execute (or simulate) a sell order for an open position.
    """
    token = position["token"]
    token_address = token.get("tokenAddress")
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    trade_result = execute_trade(token_address, "sell", position["quantity"])
    print(f"[SELL] {sym} | Sold {position['quantity']} at price {trade_result}")
    return trade_result

def monitor_position(position):
    """
    Monitor an open position and trigger a sell when profit target or stop-loss conditions are met.
    """
    buy_price = position["buy_price"]
    target_price = buy_price * PROFIT_TARGET_MULTIPLIER
    stop_loss_price = buy_price * STOP_LOSS_RATIO
    token = position["token"]
    token_address = token.get("tokenAddress")
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    
    while True:
        tokens = fetch_tokens()
        current_token = None
        for t in tokens:
            if t.get("tokenAddress") == token_address:
                current_token = t
                break
        if not current_token:
            print(f"[MONITOR] {sym}: No updated data; retrying...")
            time.sleep(POSITION_POLL_INTERVAL)
            continue
        current_price = float(current_token.get("priceUsd", 0))
        print(f"[MONITOR] {sym}: current price = {current_price}, target = {target_price}, stop loss = {stop_loss_price}")
        if current_price >= target_price:
            print(f"[MONITOR] {sym}: Profit target reached.")
            sell_token(position)
            break
        if current_price <= stop_loss_price:
            print(f"[MONITOR] {sym}: Stop loss triggered.")
            sell_token(position)
            break
        time.sleep(POSITION_POLL_INTERVAL)

# ---------------------------
# TOKEN DISCOVERY
# ---------------------------
def fetch_tokens():
    """
    Fetch token profiles from Dexscreener for Solana.
    Returns a list of token profiles or an empty list on error.
    """
    try:
        response = requests.get(DEXSCEENER_API_URL, timeout=10)
        print(f"[DEBUG] HTTP Status Code: {response.status_code}")
        print(f"[DEBUG] Response Text (first 300 chars): {response.text[:300]}")
        data = response.json()
        if isinstance(data, list):
            tokens = data
        elif isinstance(data, dict):
            tokens = data.get("data", [])
        else:
            tokens = []
        return tokens
    except Exception as e:
        print(f"[ERROR] Fetching tokens: {e}")
        return []

# ---------------------------
# MAIN BOT LOOP
# ---------------------------
def main():
    positions = []
    discovered = set()
    while True:
        tokens = fetch_tokens()
        if tokens:
            good_tokens = filter_tokens(tokens, MIN_SCORE_THRESHOLD)
            for token in good_tokens:
                sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
                category = categorize_token(token)
                if category is None:
                    continue
                if sym in discovered:
                    continue
                discovered.add(sym)
                print(f"[DISCOVERY] Found token: {sym} | Category: {category} | Score: {token.get('score')}")
                position = buy_token(token)
                if position:
                    monitor_thread = threading.Thread(target=monitor_position, args=(position,))
                    monitor_thread.start()
                    positions.append(position)
        else:
            print("[INFO] No tokens fetched at this time.")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("Starting Solana trading bot prototype version 6...")
    main()
