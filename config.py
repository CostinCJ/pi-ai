import os

DB_PATH    = '/home/pi/pi-ai/memory.db'
OLLAMA_BASE = 'http://localhost:11434'
OLLAMA_CHAT_URL = f'{OLLAMA_BASE}/api/chat'
OLLAMA_GENERATE_URL = f'{OLLAMA_BASE}/api/generate'
MODEL      = 'hf.co/MaziyarPanahi/Qwen3-1.7B-GGUF:Q4_K_M'

TELEGRAM_TOKEN = '8689871377:AAFWsv-5jRjwHAm3moGUeZsd8sun2B7S4ts'
CHAT_ID        = '6357656372'

OWM_API_KEY = '08bcc3a5977d6ba6fb97c8968dcb22ec'

SPOTIFY_CLIENT_ID     = '8ae0ce2f360949cab272d137ce3a23f2'
SPOTIFY_CLIENT_SECRET = 'cd6881d037b841b88011e72808c452c2'
SPOTIFY_REDIRECT_URI  = 'http://127.0.0.1:8888/callback'

LAPTOP_MAC = 'AA-BB-CC-DD-EE-FF'

PHONE_MAC = 'aa:bb:cc:dd:ee:ff'

TAILSCALE_IP = '100.64.0.1'     # Pi's Tailscale IPv4 address
SESSION_SERVER_PORT = 8765
