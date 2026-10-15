# Omada Controller Migration Guide

This document captures the information needed to migrate from the current Docker-hosted Omada controller to a native Omada controller, preserve the current Wi-Fi configuration, verify the wireless network is working before decommissioning the old system, and safely clean up the legacy Docker install.

## 1. Why this migration is recommended

The current Docker-based Omada controller is older and is not behaving like a modern Omada controller. In particular, the controller is not reliably returning the expected JSON from endpoints such as:

- /api/v2/sites
- /api/v2/sites/{site_id}/clients

This mismatch is why a script that depends on the modern API may appear to fail even though the controller is reachable. A native Omada controller is more likely to expose the expected API structure and be easier to support long-term.

## 2. Before you change anything: create backups

Do this before removing or changing the existing controller.

### 2.1 Back up the current Omada configuration from the controller UI

Use the existing Omada web interface and export a backup from the controller settings.

Typical flow:

1. Log in to the current Omada controller.
2. Open Settings or System.
3. Look for Backup / Restore, Maintenance, or Configuration.
4. Create a full configuration backup.
5. Save the backup file to a safe location on the Pi, another PC, or external storage.

Record the following details as well:

- Controller IP address
- Controller hostname
- Site name
- Site ID (if visible)
- List of APs and their serial numbers
- WLAN names (SSID names)
- Security modes (WPA2/WPA3, PSK, etc.)
- VLANs and guest network configuration
- DHCP/Gateway settings
- Any special guest or management SSIDs

### 2.2 Back up the Docker configuration as well

If the current Omada controller is running in Docker, collect the Docker details too:

```bash
docker ps -a

docker inspect <container_name>

docker volume ls

docker images
```

If you have a docker-compose file, save it too:

```bash
ls -la
find /opt /docker /home -maxdepth 3 -type f \( -name '*docker*compose*' -o -name 'docker-compose*' \) 2>/dev/null
```

Also keep a copy of any bind-mounted Omada data directories, for example:

```bash
ls -la /opt
ls -la /docker
ls -la /var/lib/docker/volumes 2>/dev/null
```

## 3. Install the native Omada controller on Linux Mint

### 3.1 Recommended approach

The cleanest path is to run the native Omada controller on a supported Debian/Ubuntu host or VM. Linux Mint is similar to Ubuntu and usually works, but a clean Ubuntu 22.04 LTS or 24.04 LTS host or VM is the least problematic option.

If possible, use a dedicated Ubuntu/Debian VM instead of trying to force the old Docker install to keep running.

### 3.2 Install prerequisites

On the Linux Mint system or the Ubuntu VM, install the basic dependencies:

```bash
sudo apt update
sudo apt install -y curl wget ca-certificates gnupg
```

### 3.3 Add the official Omada repository

Use the official Omada installer instructions for the version of Debian/Ubuntu you are using. The exact repository steps can vary by release, but the process is usually:

1. Add the official Omada repository key.
2. Add the Omada repository to /etc/apt/sources.list.d.
3. Run apt update.
4. Install the native controller package.

Example pattern:

```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL <official-omada-key-url> | sudo gpg --dearmor -o /etc/apt/keyrings/omada.gpg

sudo nano /etc/apt/sources.list.d/omada.list
```

Then add the repository entry exactly as provided by the official Omada instructions for your distro, then run:

```bash
sudo apt update
sudo apt install -y omada-controller
```

If the exact package name differs for your release, follow the official package listing and install the matching controller package.

### 3.4 Start the controller service

After installation, the package usually creates a service you can start with:

```bash
sudo systemctl enable --now omada-controller
sudo systemctl status omada-controller
```

Then connect to the web UI on the controller host:

```text
https://<controller-ip>:8043
```

On the host itself, this is often also reachable at:

```text
https://localhost:8043
```

### 3.5 Initial setup and site creation

During the first-run wizard:

- create or validate the admin account
- create the site
- set the site name
- confirm the controller is accepting connections
- note the site name and site ID for automation

## 4. Keep the old controller running until the new one is ready

Do not remove the old controller before the new controller is fully working.

If the APs are still managed by the old controller, then the APs may disconnect if the network is suddenly cut over. The safest order is:

1. Install the new native controller
2. Bring it online on the same LAN
3. Confirm it is reachable
4. Adopt the APs to the new controller
5. Verify SSIDs and client connectivity
6. Only then decommission the old controller

## 5. Adopt the APs to the new controller

### 5.1 Do not factory reset the APs immediately

The APs should normally remain on the same LAN and keep their current configuration until they are adopted by the new controller.

### 5.2 Steps to adopt the APs

1. Log in to the new native Omada controller.
2. Open the Devices or AP Management section.
3. Look for discovered APs or pending APs.
4. Select each AP and click Adopt.
5. Wait for the AP to reach a green/healthy state.
6. Confirm the AP is assigned to the right site and AP group.

### 5.3 If the old controller still owns the APs

If the APs are still managed by the old controller, the new controller may not adopt them until the old controller relinquishes control or the AP is no longer associated with the old manager.

In that case, follow the controller’s normal procedure for:

- removing the AP from the old controller
- deleting stale device records
- allowing re-adoption by the new controller

Do not run two controllers managing the same APs at the same time unless the APs are specifically designed for a controlled migration path. The safer route is to migrate sequentially and verify before shutting down the old system.

## 6. Verify the Wi-Fi setup after adoption

Before you consider the migration complete, confirm that the Wi-Fi network is functionally correct.

### 6.1 Check the basic site settings

In the new Omada controller, verify:

- WLAN names (SSID names) match the old network names
- Security type matches the original network setup
- WPA2/WPA3 settings are correct
- VLAN tagging is correct
- Guest network configuration is correct
- AP groups are assigned as expected
- DHCP and gateway settings are still valid for each VLAN

### 6.2 Check the AP status

Verify each AP is:

- online
- connected to the controller
- assigned to the expected site
- reporting healthy signal and client counts

### 6.3 Connect clients to the Wi-Fi

From a phone or laptop:

1. Connect to each SSID.
2. Verify the client receives a valid IP address.
3. Check internet connectivity.
4. Confirm the client shows up in the Omada controller client list.
5. Verify the correct VLAN or network policy is applied.

### 6.4 Validate guest and management networks

If you have multiple SSIDs, confirm:

- management SSID still works
- guest SSID still isolates traffic as expected
- internal SSID still reaches the right VLANs and resources

### 6.5 If the restore does not match the old setup exactly

If the backup restore does not reproduce the original configuration perfectly, recreate the WLANs manually:

- SSID name
- security type
- pre-shared key
- VLAN assignment
- guest isolation
- radio settings

This is very common during large version jumps.

## 7. Decommission the old controller

Only after the new Omada controller is fully working and the wireless clients are verified should you remove the old system.

### 7.1 Stop the old Omada container

On the host running Docker:

```bash
docker ps -a

docker stop <omada_container_name>
docker rm <omada_container_name>
```

Remove the image if it is no longer needed:

```bash
docker images
docker rmi <omada_image_name>
```

Remove leftover Docker volumes if they are no longer needed:

```bash
docker volume ls
docker volume rm <omada_volume_name>
```

### 7.2 Remove leftover files and config directories

If the Docker install created local data folders or custom compose files, remove them after you are satisfied the new controller is stable:

```bash
sudo rm -rf /opt/omada
sudo rm -rf /docker/omada
```

### 7.3 Optional: remove Docker itself

If Docker is no longer needed for anything else on the system, uninstall it:

```bash
sudo apt-get purge docker.io docker-ce docker-ce-cli containerd.io
sudo apt-get autoremove -y
```

If you still use Docker for other services, keep it and only remove the Omada container and its data.

## 8. Final migration checklist

Use this as a final verification list:

- [ ] Backup of the old controller created and saved
- [ ] Native Omada controller installed on the Linux Mint host or Ubuntu VM
- [ ] Controller UI reachable on port 8043
- [ ] Site created and correct
- [ ] APs discovered and adopted by new controller
- [ ] WLAN names, security, VLANs, and guest network match the old setup
- [ ] Wireless clients connect normally
- [ ] DHCP and internet connectivity work on all SSIDs
- [ ] Old controller is still available until the new one is proven stable
- [ ] Old controller is decommissioned only after final testing

## 9. Important warnings

- Do not remove the old controller before the new controller is fully adopted and working.
- Do not factory reset the APs prematurely.
- Do not run two Omada controllers managing the same APs at the same time without a controlled migration plan.
- Expect a brief loss of Wi-Fi during the AP handoff if the old controller is removed too early.
- If the configuration restore is not complete, re-create the WLANs manually and validate them before removing the old system.

## 10. Practical recommendation

For best results, install the native Omada controller on a dedicated Ubuntu/Debian VM and migrate the APs to that controller, then validate all Wi-Fi before decommissioning the Docker-based controller. This is the safest and most predictable path for a home network that depends on Omada for access control and wireless presence detection.
