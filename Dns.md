# ePoster Admin Panel - User Guide

This system allows you to configure the ePoster device (Wi-Fi, Device ID, Rotation) via a web interface. It works in two modes:
1.  **Network Mode:** Access the admin panel while connected to the same Wi-Fi.
2.  **Setup Mode:** The device creates its own Hotspot if no Wi-Fi is available.

---

## 1. Prerequisites
Ensure the following are installed on the Linux device:

```bash
# System tools
sudo apt-get install dnsmasq avahi-daemon

# Python libraries
sudo pip3 install flask dnslib