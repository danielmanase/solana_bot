import base58
import json

# Replace this string with your exported Phantom key (Base58-encoded)
phantom_key = "5dtPnJAXAtoeFZb48hyy7ZSeDafC2aSatDC6hJQSQ7ymDrsid8BcYHeoU8iEHNjo3oHAgZ6t1JHhsvgPk3ZZEhLf"

# Decode the Base58 string to bytes
key_bytes = base58.b58decode(phantom_key)

# Convert the bytes to a list of integers
key_list = list(key_bytes)

# Print the JSON representation of the list
print(json.dumps(key_list))

