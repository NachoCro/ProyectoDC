import os

from dotenv import load_dotenv

load_dotenv()

PRESTASHOP_API_URL = os.getenv("PRESTASHOP_API_URL", "").rstrip("/")
PRESTASHOP_API_KEY = os.getenv("PRESTASHOP_API_KEY", "")
ICECAT_USERNAME = os.getenv("ICECAT_USERNAME", "")
ICECAT_API_TOKEN = os.getenv("ICECAT_API_TOKEN", "")

DB_PATH = os.getenv("DB_PATH", "catalogo.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))
API_SLEEP = int(os.getenv("API_SLEEP", "2"))
