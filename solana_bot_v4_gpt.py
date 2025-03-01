#!/usr/bin/env python3
"""
A prototype Solana trading bot (version 3).

This bot fetches token profiles from Dexscreener for Solana, scores tokens based on market data,
and simulates buy/sell operations only on tokens that pass a minimum score threshold.
It uses solders for low-level operations (keypairs, transactions, system program instructions, and public keys)
and solana.rpc.api for higher-level RPC calls.
"""

# Low-level operations from solders
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey

# High-level RPC client for Solana
from solana.rpc.api import Client as SolanaClient

import requests
import time
import threading
import json

########################################
# CONFIGURATION
########################################

# Dexscreener API endpoint for Solana token profiles (live mainnet data)
DEXSCEENER_API_URL = "https://api.dexscreener.com/token-profiles/latest/v1"

# Trading parameters (simulation)
RISK_AMOUNT = 1.0                 # Risk amount per trade (simulation)
PROFIT_TARGET_MULTIPLIER = 2.0    # E.g., sell when the price doubles
STOP_LOSS_RATIO = 0.8             # E.g., sell if price falls to 80% of buy price

# Filtering / Scoring thresholds
MIN_SCORE_THRESHOLD = 2.0         # Only tokens with a score >= this value are considered

# Polling intervals (in seconds)
POLL_INTERVAL = 60              # How often to check for new tokens
POSITION_POLL_INTERVAL = 30     # How often to monitor open positions

########################################
# WALLET & SOLANA CLIENT SETUP
########################################

def load_keypair(filepath="phantom-keypair.json"):
    """Load a keypair from a JSON file."""
    with open(filepath, "r") as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

# Load your wallet keypair (ensure phantom-keypair.json is in your project directory)
wallet = load_keypair("phantom-keypair.json")

# Connect to the mainnet RPC endpoint (live data)
solana_client = SolanaClient("https://api.mainnet-beta.solana.com")

########################################
# SCORING FUNCTIONS
########################################

def score_token(token):
    """
    Calculate a score for a token based on:
      - Market Cap (or FDV): "marketCapUsd" (or "fdvUsd")
      - Liquidity: "liquidityUsd"
      - 24H Volume: "volumeUsd24Hr"
      
    The score is a weighted sum (adjust weights as needed):
      score = (marketCap / 100k) + (liquidity / 50k) + (volume24h / 1M)
    """
    try:
        # Get market cap (or FDV) from token profile
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
    
    Returns a list of tokens that have a score >= min_score.
    """
    filtered = []
    for token in tokens:
        s = score_token(token)
        if s >= min_score:
            token["score"] = s  # attach the score to the token for reference
            filtered.append(token)
    return filtered

########################################
# PLACEHOLDER TRADE FUNCTIONS
########################################

def execute_dex_trade(token_address, action, amount):
    """
    Simulate executing a trade on a DEX.
    
    Parameters:
      token_address (str): The token's address.
      action (str): "buy" or "sell".
      amount (float): The risk amount or quantity.
    
    Returns:
      simulated_price (float): A simulated trade price.
    """
    print(f"[TRADE] Executing {action} order for token {token_address} with amount {amount}")
    simulated_price = 0.1  # For simulation, assume a fixed price; replace with live data in production.
    return simulated_price

########################################
# TOKEN DISCOVERY & RISK CHECKS
########################################

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
        # The API might return a list directly or a dict with a "data" key.
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

########################################
# TRADE EXECUTION LOGIC
########################################

def buy_token(token):
    """
    If a token passes the score filter, simulate a buy order.
    
    Returns a dictionary with position data or None if buy fails.
    """
    token_address = token.get("tokenAddress")
    if not token_address:
        print("[BUY] Token address not found; skipping.")
        return None

    buy_price = execute_dex_trade(token_address, "buy", RISK_AMOUNT)
    if not buy_price:
        return None
    quantity = RISK_AMOUNT / buy_price
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    print(f"[BUY] {sym} | Score: {token.get('score', 'N/A')} | Bought {quantity} at price {buy_price}")
    return {"token": token, "buy_price": buy_price, "quantity": quantity}

def sell_token(position):
    """
    Simulate a sell order for an open position.
    """
    token = position["token"]
    token_address = token.get("tokenAddress")
    sym = token.get("symbol") or token.get("tokenAddress") or "Unknown"
    sell_price = execute_dex_trade(token_address, "sell", position["quantity"])
    print(f"[SELL] {sym} | Sold {position['quantity']} at price {sell_price}")
    return sell_price

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

########################################
# MAIN BOT LOOP
########################################

def main():
    positions = []
    discovered = set()
    while True:
        tokens = fetch_tokens()
        if tokens:
            # First, filter tokens using the scoring system.
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
    print("Starting Solana trading bot prototype version 3...")
    main()
