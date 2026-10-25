# Copy or rename this file to `automation_credentials.py` on the machine running the automations.
# Replace every sample value below with your real local credentials before starting any service.
# Keep the real `automation_credentials.py` out of version control; this file contains placeholders only.

import os

# MQTT broker connection details
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.0.2.51")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "sample_mqtt_user_7f3a")
MQTT_PASS = os.getenv("MQTT_PASS", "not-a-real-mqtt-password-7f3a")

# Omada controller connection details
OMADA_BASE_URL = os.getenv("OMADA_BASE_URL", "https://192.0.2.10:8043")
OMADA_OMADAC_ID = os.getenv("OMADA_OMADAC_ID", "sample_omadac_id_7f3a")
OMADA_CLIENT_ID = os.getenv("OMADA_CLIENT_ID", "sample_client_id_7f3a")
OMADA_CLIENT_SECRET = os.getenv("OMADA_CLIENT_SECRET", "not-a-real-client-secret-7f3a")
OMADA_SITE_ID = os.getenv("OMADA_SITE_ID", "sample_site_id_7f3a")
OMADA_SITE_NAME = os.getenv("OMADA_SITE_NAME", "SampleOmadaNetwork")

# Legacy Omada auth values (if your controller still requires them)
OMADA_USERNAME = os.getenv("OMADA_USERNAME", "sample_omada_reader")
OMADA_PASSWORD = os.getenv("OMADA_PASSWORD", "not-a-real-omada-password-7f3a")

__all__ = [
    "MQTT_BROKER",
    "MQTT_PORT",
    "MQTT_USER",
    "MQTT_PASS",
    "OMADA_BASE_URL",
    "OMADA_OMADAC_ID",
    "OMADA_CLIENT_ID",
    "OMADA_CLIENT_SECRET",
    "OMADA_SITE_ID",
    "OMADA_SITE_NAME",
    "OMADA_USERNAME",
    "OMADA_PASSWORD",
]
