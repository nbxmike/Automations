import ssl
import json
import time
import sys
import socket
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from automation_credentials import (
    MQTT_BROKER,
    MQTT_PASS,
    MQTT_PORT,
    MQTT_USER,
    OMADA_BASE_URL,
    OMADA_CLIENT_ID,
    OMADA_CLIENT_SECRET,
    OMADA_OMADAC_ID,
    OMADA_SITE_ID,
)
from paho.mqtt import client as mqtt_client

# ================= Configuration =================
OMADA_HOST = OMADA_BASE_URL.replace("https://", "").replace("http://", "").split(":")[0]
OMADA_PORT = int(OMADA_BASE_URL.rsplit(":", 1)[-1].split("/")[0]) if ":" in OMADA_BASE_URL else 8043
OMADAC_ID = OMADA_OMADAC_ID
SITE_ID = OMADA_SITE_ID

CLIENT_ID = OMADA_CLIENT_ID
CLIENT_SECRET = OMADA_CLIENT_SECRET

# House MQTT broker settings (same values used in kitchen automations).
MQTT_ROOT_TOPIC = "phonePresence"

# Target phone MAC addresses (lower-case or upper-case, normalized in code)
TARGET_MACS = {
    "9E-F6-8D-D5-C2-B5": "Aislinn's Phone",
    "1E-43-40-08-75-23": "Hannah's A55 Phone",
    "AE-3F-CB-3D-20-2A": "Sean's Phone",
    "EA-23-62-12-14-E1": "Meghan's Phone",
    "B2-05-4B-D7-67-A3": "Dee's Phone",
    "00-62-01-2D-C7-D1": "Mike's Phone"
}

POLL_INTERVAL = 30  # Seconds between polls
# =================================================

BASE_URL = f"https://{OMADA_HOST}:{OMADA_PORT}"

# Bypass self-signed SSL verification
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def normalize_mac(value):
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", ":")


def client_mac(client_record):
    """Return the best MAC candidate from a client record."""
    for key in ("mac", "macAddress", "wirelessMac", "clientMac"):
        value = client_record.get(key)
        if value:
            return normalize_mac(value)
    return ""


def first_name_from_label(label):
    """Extract a stable first-name token for topic leaves."""
    text = str(label).strip()
    if not text:
        return "unknown"
    token = text.split()[0]
    token = token.split("'")[0]
    clean = "".join(ch for ch in token if ch.isalnum() or ch == "-")
    return clean.lower() if clean else "unknown"


def build_phone_topic_map(target_macs):
    """Build unique MQTT topic leaves from the configured person names."""
    topic_map = {}
    used_leaves = set()
    for mac, label in target_macs.items():
        leaf = first_name_from_label(label)
        if leaf in used_leaves:
            leaf = f"{leaf}{normalize_mac(mac).replace(':', '')[-4:]}"
        used_leaves.add(leaf)
        topic_map[normalize_mac(mac)] = f"{MQTT_ROOT_TOPIC}/{leaf}"
    return topic_map


def publish_presence_topics(mqttc, topic_map, active_macs):
    everyone_home = True

    for mac, topic in topic_map.items():
        is_present = mac in active_macs
        if not is_present:
            everyone_home = False
        mqttc.publish(topic, "true" if is_present else "false", retain=True)

    mqttc.publish(f"{MQTT_ROOT_TOPIC}/everyone", "true" if everyone_home else "false", retain=True)


def create_mqtt_client():
    hostname = socket.gethostname()
    client_id = f"{hostname}_OmadaPresenceV2"
    mqttc = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    mqttc.username_pw_set(MQTT_USER, MQTT_PASS)
    mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
    mqttc.connect(MQTT_BROKER, MQTT_PORT)
    mqttc.loop_start()
    return mqttc


class OmadaOpenAPI:
    def __init__(self, host_url, omadac_id, client_id, client_secret):
        self.base_url = host_url
        self.omadac_id = omadac_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = 0

    def get_token(self):
        """Authenticates and fetches a fresh access token."""
        url = f"{self.base_url}/openapi/authorize/token?grant_type=client_credentials"
        payload = json.dumps({
            "omadacId": self.omadac_id,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }).encode("utf-8")

        req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        
        try:
            with urlopen(req, context=SSL_CTX, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("errorCode") == 0:
                    result = res.get("result", {})
                    self.access_token = result.get("accessToken")
                    # Expire 60s earlier than server timeout to ensure buffer
                    self.token_expiry = time.time() + result.get("expiresIn", 7200) - 60
                    print(f"[AUTH] Token obtained successfully. Valid for {result.get('expiresIn')}s")
                    return self.access_token
                else:
                    print(f"[AUTH ERROR] Code {res.get('errorCode')}: {res.get('msg')}")
                    return None
        except (HTTPError, URLError) as e:
            print(f"[AUTH HTTP ERROR] {e}")
            return None

    def ensure_authenticated(self):
        """Ensures a valid access token is available."""
        if not self.access_token or time.time() >= self.token_expiry:
            return self.get_token() is not None
        return True

    def fetch_clients(self, site_id):
        """Fetches active clients for the specified site."""
        if not self.ensure_authenticated():
            return None

        url = f"{self.base_url}/openapi/v1/{self.omadac_id}/sites/{site_id}/clients?page=1&pageSize=100"
        
        # Try both common OpenAPI authorization header formats if primary fails
        headers = {
            "Authorization": f"AccessToken={self.access_token}",
            "Content-Type": "application/json"
        }

        req = Request(url, headers=headers, method="GET")

        try:
            with urlopen(req, context=SSL_CTX, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                
                # If errorCode -44116 occurs, retry with alternative header format
                if res.get("errorCode") == -44116:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    req = Request(url, headers=headers, method="GET")
                    with urlopen(req, context=SSL_CTX, timeout=10) as retry_resp:
                        res = json.loads(retry_resp.read().decode("utf-8"))

                if res.get("errorCode") == 0:
                    return res.get("result", {}).get("data", [])
                else:
                    print(f"[API ERROR] Code {res.get('errorCode')}: {res.get('msg')}")
                    return None
        except (HTTPError, URLError) as e:
            print(f"[API HTTP ERROR] {e}")
            return None


def main():
    api = OmadaOpenAPI(BASE_URL, OMADAC_ID, CLIENT_ID, CLIENT_SECRET)
    target_mac_set = {normalize_mac(m): name for m, name in TARGET_MACS.items()}
    topic_map = build_phone_topic_map(TARGET_MACS)
    mqttc = create_mqtt_client()

    print("Starting Omada Presence Monitoring Service...")
    print(f"Publishing presence topics under: {MQTT_ROOT_TOPIC}/")

    try:
        while True:
            clients = api.fetch_clients(SITE_ID)

            if clients is not None:
                active_macs = {
                    client_mac(c): c
                    for c in clients
                    if isinstance(c, dict) and client_mac(c)
                }

                print(f"\n--- Poll Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
                print(f"Total connected devices on LAN: {len(clients)}")

                for mac, name in target_mac_set.items():
                    if mac in active_macs:
                        device = active_macs[mac]
                        ip = device.get("ip", "N/A")
                        ssid = device.get("ssid", "Ethernet/Unknown")
                        print(f" [+] PRESENT: {name} ({mac}) - IP: {ip} [SSID: {ssid}]")
                    else:
                        print(f" [-] ABSENT : {name} ({mac})")

                publish_presence_topics(mqttc, topic_map, active_macs)

            time.sleep(POLL_INTERVAL)
    finally:
        mqttc.loop_stop()
        mqttc.disconnect()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping Presence Monitor.")
        sys.exit(0)