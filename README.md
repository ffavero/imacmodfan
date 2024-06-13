# imacmodfan
Handle the fans in a GPU modified old imac in linux


# Sample configuration

The config is at the header of the script (for now)

```
[DEFAULT]
sys_dir = /sys/devices/platform/applesmc.768
polling_seconds = 5
cooling_curve_multiplier = 0.5

[ODD]
bind=NVGPU
temp1=50
temp2=80

[HDD]
bind=TL0P 
temp1=38
temp2=60


[CPU]
bind=TC0H
temp1=50
temp2=90
"""
```

# How to run it

```
$ sudo python fan.py 
06/13/2024 10:49:43 PM INFO:TL0P temperature changed from 0.0 to 42.0
06/13/2024 10:49:43 PM INFO:Set fan HDD RPM to 2860
06/13/2024 10:49:43 PM INFO:TC0H temperature changed from 0.0 to 36.0
06/13/2024 10:49:43 PM INFO:Set fan CPU RPM to 940
06/13/2024 10:49:43 PM INFO:NVGPU temperature changed from 0.0 to 47.0
06/13/2024 10:49:43 PM INFO:Set fan ODD RPM to 1150
06/13/2024 10:49:48 PM INFO:TC0H temperature changed from 36.0 to 35.0
06/13/2024 10:49:48 PM INFO:Set fan CPU RPM to 940
06/13/2024 10:49:53 PM INFO:TL0P temperature changed from 42.0 to 42.0
06/13/2024 10:49:53 PM INFO:Set fan HDD RPM to 2948
06/13/2024 10:49:53 PM INFO:TC0H temperature changed from 35.0 to 35.0
06/13/2024 10:49:53 PM INFO:Set fan CPU RPM to 940
06/13/2024 10:50:08 PM INFO:NVGPU temperature changed from 47.0 to 46.0
06/13/2024 10:50:08 PM INFO:Set fan ODD RPM to 1150
06/13/2024 10:50:13 PM INFO:TL0P temperature changed from 42.0 to 42.0
06/13/2024 10:50:13 PM INFO:Set fan HDD RPM to 3036
```

# Future

It might be advisable to launch the script within a service

something on the line with

```
sudo cp fan.py usr/sbin/imacmodfan.py
sudo nano -w /etc/systemd/system/imacmodfan.service
```

where the content is smething like:

```
[Unit]
Description=A fan manager daemon for modified iMacs
After=syslog.target
After=sysinit.target

[Service]
Type=simple
ExecStart=/usr/sbin/imacmodfan.py
ExecReload=/usr/bin/kill -HUP $MAINPID
PIDFile=/run/imacmodfan.pid
Restart=always
RestartSec=5

[Install]
WantedBy=sysinit.target
```

however the configuration is built in the script, so it's not
very elegant. But it could easily be modified to use a config file.


# Random info

I came across a post explaining what are some of the labels in
applesmc, here they are:


```
# Bit Hex Dec Key Description
# --- ------ ----- ---- ------------
# 0 0x0001 1 TC0H CPU Heatsink
# 1 0x0002 2 TG0H GPU Heatsink
# 2 0x0004 4 TH0P HDD Proximity
# 3 0x0008 8 TO0P ODD Proximity
# 4 0x0010 16 Tm0P MLB Proximity
# 5 0x0020 32 TA0P Ambient
# 6 0x0040 64 Tp0P Power Supply Proximity
# 7 0x0080 128 TW0P Wireless (Airport) Proximity
# 8 0x0100 256 TC0P CPU Proximity
# 9 0x0200 512 TC0D CPU Die
# 10 0x0400 1024 TG0P GPU Proximity
# 11 0x0800 2048 TG0D GPU Die
# 12 0x1000 4096 TL0P LCD Proximity
# 13 0x2000 8192 SGTT GPU Heatsink Throttle Threshold
```
