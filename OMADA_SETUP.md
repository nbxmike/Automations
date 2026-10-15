# Omada setup for phone-presence shutdown

This file documents the Omada controller settings needed before using the presence-based yard shutoff automation.

## 1. Controller requirements

- Omada Controller must be reachable from the Pi over HTTPS or HTTP.
- The Omada controller site must contain the WiFi SSIDs your phones use.
- The user account used by the script must have permission to read the site and its client list.
- The controller must be able to show connected WiFi clients, including phone names and MAC addresses.

A typical endpoint looks like this:

- https://omada.example.com:8043
- or http://192.168.1.10:8088

The script is configured with:

- OMADA_BASE_URL
- OMADA_USERNAME
- OMADA_PASSWORD
- OMADA_SITE_NAME

in the Python script itself, or by setting matching environment variables before starting the script.

### Using the administrator account vs a dedicated account

You can use the Omada administrator account as OMADA_USERNAME / OMADA_PASSWORD if you want, but it is not required. A cleaner and safer setup is to create a dedicated Omada user with the minimum rights needed to read the client list for your site.

If you are using the Omada admin account directly, set:

```python
OMADA_USERNAME = "admin"
OMADA_PASSWORD = "<your administrator password>"
```

If you do not want to use the admin password, create a dedicated Omada user instead:

1. Log in to the Omada controller as the administrator.
2. Open the user or account management section.
3. Create a new user account, such as `pi_omada_reader` or `presence_check`.
4. Give that user at least read access to the site where your phones connect.
5. Grant permission to view clients / wireless clients / device list for that site.
6. Save the new user.
7. Use that username and password in the script:

```python
OMADA_USERNAME = "pi_omada_reader"
OMADA_PASSWORD = "<the user password you created>"
```

If the account cannot see the WiFi clients, the script will fail to log in or will see no devices. In that case, either give the account site-level read access or switch back to the admin account for testing.

## 2. Omada system options to enable or confirm

Make sure these are true on the Omada controller:

1. The site is the same site your phones connect to.
2. The devices are connected to the main WiFi SSID, not a guest network, unless you intentionally include guest devices in your list.
3. The controller is reporting client access information and online status for client devices.
4. The phone names or MAC addresses match what the script expects.
5. The controller is not hiding clients behind a guest portal or a network isolation setting that removes client visibility.

If your Omada controller is managed through the cloud or direct controller, confirm the configuration page shows clients as online and includes a MAC address or host name for each phone.

## 3. Matching the phones correctly

The script compares the configured list of expected devices against the Omada client list. You can match by either:

- a friendly phone name, such as "AlicePhone"
- or a MAC address, such as "aa:bb:cc:dd:ee:ff"

The safest option is to use MAC addresses because names can change.

Edit this section in the script:

```python
EXPECTED_CLIENTS = [
    "AlicePhone",
    "BobPhone",
    "aa:bb:cc:dd:ee:ff",
]
```

If you want the script to treat only one phone as required, keep just that one entry.

## 4. API access

The script uses the Omada controller API to read clients. Some Omada versions use different login endpoints or return different result formats. The script tries a few common patterns and logs the result clearly if it cannot authenticate.

If the script cannot log in:

- confirm the username/password are valid
- confirm the controller is on the expected URL and port
- confirm the account has access to the site
- confirm the account is allowed to view clients for that site
- confirm the server certificate or self-signed certificate is acceptable for the environment if you are using HTTPS

If you are using a dedicated account and it fails, log back in as the administrator and check the account's role or permissions. Many Omada installs require explicit read access to the site and wireless client information, not just general login access.

## 5. Required phone states

The script only turns off the yard outlet when every expected phone is present and online.

The logic is intentionally conservative:

- a client must be marked online or connected
- it must not be older than the configured stale threshold
- if any expected phone is absent, the outlet stays on

The stale threshold is configured here:

```python
ONLINE_STALE_SECONDS = 1800
```

That is 1800 seconds, or 30 minutes.

## 6. What this automation does

When every configured phone is confirmed to be home, the script publishes the same command used by the yard midnight automation:

```python
POWER1_OFF_TOPIC = "cmnd/wyze_parking_tree/POWER1"
```

with this payload:

```python
OFF
```

This matches the same first-outlet shutoff behavior used in yard_midnight_automation.py.

## 7. Recommended validation steps

1. Start the script manually in a terminal.
2. Confirm the Omada login succeeds.
3. Confirm the client list includes your phones.
4. Confirm the script logs each phone as detected.
5. Temporarily disable WiFi on one phone and verify the script does not switch off the outlet.
6. Re-enable that phone and verify the outlet turns off when all phones are home again.

## 8. Notes

- This script is best run as a systemd service on the Pi in the same way as the other automations.
- If your Omada environment uses a cloud controller or different API layout, you may need to adjust the API URLs in the script.
- Keep the list of phones realistic; do not include guests or devices that should not prevent the yard shutoff.
