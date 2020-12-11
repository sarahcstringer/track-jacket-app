import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


twilio_num = os.environ["TWILIO_NUMBER"]
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)
