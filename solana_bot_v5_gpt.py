#!/usr/bin/env python3
"""
Solana Trading Bot Prototype (Version 5)

This bot fetches token profiles from Dexscreener for Solana, scores tokens based on 
market cap, liquidity, and volume, and then filters for tokens that meet a minimum score.
For tokens that pass the filters, it simulates a buy order and monitors the token's price
to eventually simulate a sell when either a profit target or stop-loss condition is met.

It supports two modes:
  - Simulation Mode (REAL_TRANSACTIONS = False): Trades are simulated with a fixed price.
  - Real Transaction Mode (REAL_TRANSACTIONS = True): A real SOL transfer is executed.

**WARNING:** Real transactions affect real funds. Test on devnet or in simulation mode
before using mainnet.
"""

# ---------------------------
# Imports
# ---------------------------
# Low-level operations from solders
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey

# High-level RPC client for Solana
from solana.rpc.api import Client as SolanaClient
from solana.rpc.types import TxOpts

import requests
import time
import threading
import json

# ---------------------------
# CONFIGURATION
# ---------------------------
# Dexscreener API endpoint for token profiles (live mainnet data)
DEXSCEENER_API_URL = "https://api.dexscreener.com/token-profiles/latest/v1"

# Trading & filtering parameters
RISK_AMOUNT = 10                 # Risk amount per trade (simulation value)
PROFIT_TARGET_MULTIPLIER = 1.5    # E.g., sell when price doubles
STOP_LOSS_RATIO = 0.8             # E.g., sell if price falls to 80% of buy price

# Scoring threshold: only tokens with a score >= this value will be considered.
MIN_SCORE_THRESHOLD = 2.0         

# Polling intervals (in seconds)
POLL_INTERVAL = 60              # How often to fetch tokens
POSITION_POLL_INTERVAL = 30     # How often to monitor open positions

# Real transaction settings
REAL_TRANSACTIONS = True         # Set to True to execute real transactions
TEST_RECIPIENT = "RecipientPublicKeyHere"  # Replace with an actual recipient address when trading live
TRANSFER_LAMPORTS = 10_000_000    # For a SOL transfer (e.g., 0.01 SOL = 10,000,000 lamports)

# ---------------------------
# WALLET & RPC CLIENT SETUP
# ---------------------------
def load_keypair(filepath="phantom-keypair.json"):
    """Load a keypair from a JSON file (expects a JSON array of numbers)."""
    with open(filepath, "r") as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

# Load your wallet keypair (make sure phantom-keypair.json is in your project directory)
wallet = load_keypair("phantom-keypair.json")

# Choose RPC endpoint:
# Use devnet for simulation to protect funds; switch to mainnet-beta if REAL_TRANSACTIONS is True.
rpc_url = "https://api.devnet.solana.com" if not REAL_TRANSACTIONS else "https://api.mainnet-beta.solana.com"
solana_client = SolanaClient(rpc_url)

# ---------------------------
# REAL TRANSACTION FUNCTION
# ---------------------------
def send_sol_transfer(recipient_address: str, lamports: int):
    """
    Send a SOL transfer transaction.
    
    Parameters:
      recipient_address (str): The recipient's public key (base58 string).
      lamports (int): Amount in lamports (1 SOL = 1,000,000,000 lamports).
      
    Returns:
      The transaction response from the RPC endpoint.
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
# SCORING & FILTERING FUNCTIONS
# ---------------------------
def score_token(token):
    """
    Calculate a score for a token based on market cap (or FDV), liquidity, and 24H volume.
    
    Example formula (adjust weights as needed):
      score = (marketCap / 100k) + (liquidity / 50k) + (volume24h / 1M)
    """
    try:
        market_cap = token.get("marketCapUsd", token.get("fdvUsd", 0))
        market_cap = float(market_cap) if market_cap else 0
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
    
    Returns a list of tokens that score >= min_score.
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
    Execute a trade (buy or sell).
    In simulation mode, return a fixed simulated price.
    In real transaction mode, send a SOL transfer.
    """
    if REAL_TRANSACTIONS:
        if action in ["buy", "sell"]:
            print(f"[REAL TRADE] {action.capitalize()} order for token {token_address}")
            # For a real trade, execute a SOL transfer; here, we simply send the same amount
            return send_sol_transfer(TEST_RECIPIENT, TRANSFER_LAMPORTS)
        else:
            print("[REAL TRADE] Unknown action")
            return None
    else:
        print(f"[SIMULATION] Executing {action} order for token {token_address} with amount {amount}")
        simulated_price = 0.1  # Fixed simulated price
        return simulated_price

def buy_token(token):
    """
    If a token qualifies (i.e., passes the scoring filter), execute (or simulate) a buy order.
    
    Returns a position dictionary or None if the buy fails.
    """
    token_score = score_token(token)
    token["score"] = token_score
    if token_score < MIN_SCORE_THRESHOLD or advanced_rug_pull_check(token):
        sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
        print(f"[FILTER] {sym} skipped (score: {token_score})")
        return None

    token_address = token.get("tokenAddress")
    if not token_address:
        print("[BUY] Token address not found; skipping.")
        return None

    trade_result = execute_trade(token_address, "buy", RISK_AMOUNT)
    if not trade_result:
        return None
    # In simulation, we assume a fixed price; if real, you'd extract the price from trade_result.
    buy_price = 0.1
    quantity = RISK_AMOUNT / buy_price
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    print(f"[BUY] {sym} | Score: {token_score} | Bought {quantity} at price {buy_price}")
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
    Continuously monitor an open position and trigger a sell when conditions are met.
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
# ADDITIONAL RISK CHECKS
# ---------------------------
def advanced_rug_pull_check(token):
    """
    Perform additional risk checks.
    For example, ensure the token has a minimum market cap and acceptable volume and price.
    """
    try:
        market_cap = token.get("marketCapUsd", token.get("fdvUsd", 0))
        market_cap = float(market_cap) if market_cap else 0
        if market_cap < 100000:
            sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
            print(f"[FILTER] {sym} skipped: market cap {market_cap} < 100000")
            return True

        volume = float(token.get("volumeUsd24Hr", 0))
        if volume < 1000:
            sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
            print(f"[RUG CHECK] {sym} flagged as high risk (low volume: {volume})")
            return True

        price = float(token.get("priceUsd", 0))
        if price < 0.0001:
            sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
            print(f"[RUG CHECK] {sym} flagged as high risk (extremely low price: {price})")
            return True

        return False
    except Exception as e:
        print(f"[ERROR] In advanced risk analysis: {e}")
        return True

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
        # The API may return a list directly or a dict with a "data" key.
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
            # Filter tokens using the scoring function and our threshold.
            good_tokens = filter_tokens(tokens, MIN_SCORE_THRESHOLD)
            for token in good_tokens:
                sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
                if sym in discovered:
                    continue
                discovered.add(sym)
                print(f"[DISCOVERY] Found token: {sym} | Score: {token.get('score')}")
                position = buy_token(token)
                if position:
                    monitor_thread = threading.Thread(target=monitor_position, args=(position,))
                    monitor_thread.start()
                    positions.append(position)
        else:
            print("[INFO] No tokens fetched at this time.")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("Starting Solana trading bot prototype version 5...")
    main()
