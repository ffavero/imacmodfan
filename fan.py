#! /bin/env python3

import os
import shlex
import subprocess
import signal
import configparser
import logging
from contextlib import closing
from distutils.spawn import find_executable


config_text = """

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

def load_config(text):
    config = configparser.ConfigParser()
    config.read_string(text)

    config_dict = {"settings": {}, "fans": {}}
    for section in config:
        key_conf = "settings"
        if section != "DEFAULT":
            key_conf = "fans"
        config_dict[key_conf][section] = {}
        for key in config[section]:
            config_value = config[section][key]
            try:
                config_value = int(config_value)
            except ValueError:
                pass
            config_dict[key_conf][section][key] = config_value
    return config_dict


class NvidiaSmiTempPoll:
    """
    Use nvidia-smi to query the GPU temperature polling every N seconds
    NOTE: This method was not tested in case of multiple GPUs, the use
    case for this script is in iMacs modified with an unsupporteds
    NVIDIA GPUs
    This class produce an iterable, than can be use in python with a
    context manager to loop over the STDOT of teh command
    """

    def __init__(self, polling_interval, smi_bin="nvidia-smi"):
        smi_exec = find_executable(smi_bin)
        if smi_exec is None:
            raise Exception(("Please install nvidia-smi"))
        query_cmd = (
            "%(smi_bin)s --format=csv "
            '--query-gpu="temperature.gpu" -l %(polling_interval)i'
        ) % {"smi_bin": smi_exec, "polling_interval": polling_interval}

        query_cmd_list = shlex.split(query_cmd)
        self.proc = subprocess.Popen(
            query_cmd_list, stdout=subprocess.PIPE, bufsize=4096
        )

    def __iter__(self):
        while True:
            try:
                yield next(self.proc.stdout).decode("utf-8")
            except StopIteration:
                break

    def close(self):
        self.proc.stdout.close()
        self.kill_subproc(self.proc)

    def kill_subproc(self, proc):
        try:
            proc.kill()
            proc.wait()
        except AttributeError:
            os.kill(proc.pid, signal.SIGKILL)
            os.waitpid(proc.pid, 0)


class FanCoolingCurve:
    """
    This is a class that defines which sensor controls which fan
    It implement an exponential fitting to ramp up the RPM more rapidily
    when the sensor reports higher temperatures.
    The cooling curve shape is controlled byt the exp parameter
    """

    def __init__(
        self,
        sensol_label,
        fan_label,
        fan,
        temp_min,
        temp_max,
        n,
        exp,
        system_dir,
        logger,
    ):
        dx = (temp_max - temp_min) / n
        self.xs = [temp_min + dx * i for i in range(n + 1)]
        self.ys = [round((i / n) ** exp * 100, 0) for i in range(n + 1)]
        self.fan = fan
        self.sensor_label = sensol_label
        self.fan_label = fan_label
        self.fan_control_file = os.path.join(
            system_dir, "fan%i_manual" % self.fan["id"]
        )
        self.fan_output_file = os.path.join(system_dir, "fan%i_output" % self.fan["id"])
        self.current_temp = 0
        self.logger = logger

    def temp_to_percent(self, temp):
        """impements a percentual fan speed lookup for a given temperature"""
        index = min(range(len(self.xs)), key=lambda i: abs(self.xs[i] - temp))
        return self.ys[index]

    def percent_to_rpm(self, percent):
        """impements a conversion between fan percent and fan RPM"""

        fan_range = self.fan["range"][1] - self.fan["range"][0]
        fan_net = percent * fan_range / 100
        fan_rpm = fan_net + self.fan["range"][0]
        return int(fan_rpm)

    def set_fan_speed(self, temp):
        """It need root permission, it writes the fan RPM to the system"""

        rpm = self.percent_to_rpm(self.temp_to_percent(temp))
        self.logger.info(
            "Set fan %(fan)s RPM to %(rpm)i" % {"fan": self.fan_label, "rpm": rpm}
        )
        with open(self.fan_control_file, "wt") as fan_control:
            fan_control.write("1")
        with open(self.fan_output_file, "wt") as fan_control:
            fan_control.write(str(rpm))

    def update_temp(self, temp):
        """conveniency method to store and log tempeatue changes"""
        self.logger.info(
            "%(sensor)s temperature changed from %(last).1f to %(now).1f"
            % {
                "sensor": self.sensor_label,
                "last": round(self.current_temp, 0),
                "now": round(temp, 0),
            }
        )
        self.current_temp = temp

    def fan_to_auto(self):
        """
        set the fan back to auto, but I don't know how to properly call this method
        """
        with open(self.fan_control_file, "wt") as fan_control:
            fan_control.write("0")


def get_fan_info(fan_id, system_dir):
    """quick and dirsy lookup on the appesmc files to store fan information"""
    fan_info = {"fan_id": fan_id}
    for info in ["fan%i_label", "fan%i_max", "fan%i_min"]:
        info_id = info % fan_id
        fan_info_file = os.path.join(system_dir, info_id)
        with open(fan_info_file, "rt") as fan_info_data:
            info_value = next(fan_info_data).strip()
            if info_id == "fan%i_label" % fan_id:
                fan_info["fan_info"] = info_value
            elif info_id == "fan%i_max" % fan_id:
                fan_info["max"] = int(info_value)
            elif info_id == "fan%i_min" % fan_id:
                fan_info["min"] = int(info_value)
            else:
                pass
    return fan_info


def list_fan(system_dir):
    """loop over the appesmc files to detect fans"""
    fans = {}
    for sensor_file in os.listdir(system_dir):
        if sensor_file.startswith("fan") and sensor_file.endswith("label"):
            fan_id = int(sensor_file[3])
            fan_n_info = get_fan_info(fan_id, system_dir)
            fans[fan_n_info["fan_info"]] = {
                "id": fan_n_info["fan_id"],
                "range": (fan_n_info["min"], fan_n_info["max"]),
            }
    return fans


def get_teperature_sesor_info(sensor_label, system_dir):
    """loop over the appesmc files to detect temperature sensors"""
    for sensor_file in os.listdir(system_dir):
        if sensor_file.startswith("temp") and sensor_file.endswith("label"):
            sensor_id = int(sensor_file[4:][:-6])
            sensor_label_x = ""
            with open(os.path.join(system_dir, sensor_file), "rt") as sensor_data:
                sensor_label_x = next(sensor_data).strip()
            if sensor_label_x == sensor_label:
                return os.path.join(system_dir, "temp%i_input" % sensor_id)


if __name__ == "__main__":

    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
    )
    logger = logging.getLogger("imac_fans")
    logger.setLevel(logging.DEBUG)
    parsed_config = load_config(config_text)
    config = parsed_config["fans"]

    __SYS_DIR__ = parsed_config["settings"]["DEFAULT"]["sys_dir"]
    __POLLING_SEC__ = int(parsed_config["settings"]["DEFAULT"]["polling_seconds"])
    __COOLING_CURVE_MULT__ = float(
        parsed_config["settings"]["DEFAULT"]["cooling_curve_multiplier"]
    )

    system_fans = list_fan(__SYS_DIR__)
    configured_fans = config.keys()
    gpu_temp_monitor = NvidiaSmiTempPoll(__POLLING_SEC__)

    other_fans_cooling = []
    gpu_fan_cooling = None
    for fan_label in configured_fans:
        binding_sensor = config[fan_label]["bind"]
        try:
            cooling_curve_multiplier = float(
                config[fan_label]["cooling_curve_multiplier"]
            )
        except KeyError:
            cooling_curve_multiplier = __COOLING_CURVE_MULT__
        if binding_sensor == "NVGPU":
            gpu_fan_cooling = FanCoolingCurve(
                binding_sensor,
                fan_label,
                system_fans[fan_label],
                config[fan_label]["temp1"],
                config[fan_label]["temp2"],
                100,
                cooling_curve_multiplier,
                __SYS_DIR__,
                logger,
            )
        else:

            other_fans_cooling.append(
                {
                    "fan_cooling": FanCoolingCurve(
                        binding_sensor,
                        fan_label,
                        system_fans[fan_label],
                        config[fan_label]["temp1"],
                        config[fan_label]["temp2"],
                        100,
                        cooling_curve_multiplier,
                        __SYS_DIR__,
                        logger,
                    ),
                    "temperature_sensor_file": get_teperature_sesor_info(
                        config[fan_label]["bind"], __SYS_DIR__
                    ),
                }
            )

    with closing(gpu_temp_monitor) as gpu_temp_poll:
        for temp in gpu_temp_poll:
            try:
                num_temp = float(temp)
                if gpu_fan_cooling.current_temp == 0:
                    gpu_fan_cooling.update_temp(num_temp)
                    gpu_fan_cooling.set_fan_speed(num_temp)
                else:
                    if num_temp != gpu_fan_cooling.current_temp:
                        gpu_fan_cooling.update_temp(num_temp)
                        gpu_fan_cooling.set_fan_speed(num_temp)
            except ValueError:
                # skipping labels header
                pass
            for fan_control_dict in other_fans_cooling:
                fan_cooling = fan_control_dict["fan_cooling"]
                temperature_file = fan_control_dict["temperature_sensor_file"]
                num_temp = 0
                with open(temperature_file, "rt") as temperature_sensor:
                    num_temp = float(next(temperature_sensor)) / 1000
                if fan_cooling.current_temp == 0:
                    fan_cooling.update_temp(num_temp)
                    fan_cooling.set_fan_speed(num_temp)
                else:
                    if num_temp != fan_cooling.current_temp:
                        fan_cooling.update_temp(num_temp)
                        fan_cooling.set_fan_speed(num_temp)
