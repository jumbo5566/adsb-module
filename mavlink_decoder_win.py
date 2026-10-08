# -*- coding: utf-8 -*-
"""
ADSBee mavlink_decoder.py 的 Windows 兼容副本.

改动:
1. pymavlink 的 mavserial 会先以 1200 波特打开串口再切换 (Linux 内核 bug
   的变通), 而 1200bps 是很多板子"进入刷机模式"的特殊波特率, 在 Windows
   USB CDC 上经常报 "设备不存在" -> monkeypatch: 探测波特直接用 115200 + 重试
2. 默认把每条 ADSB_VEHICLE 保存到当前目录 adsb_log.jsonl (与 adsb_server.py
   的日志格式兼容, 可用第三个参数换路径)
3. cls 清屏仅在交互终端执行 (管道/重定向时可正常捕获输出)
4. HEARTBEAT 显示一行链路确认 (原版只认飞机报文, 夜间无飞机时无输出)

用法: python mavlink_decoder_win.py COM25 115200 [日志路径]
"""
import json
import sys
import time
from datetime import datetime

import serial as _serial

_orig_init = _serial.Serial.__init__


def _patched_init(self, port=None, baudrate=1200, *a, **k):
    rate = 115200 if baudrate == 1200 else baudrate
    last = None
    for _ in range(6):
        try:
            return _orig_init(self, port, rate, *a, **k)
        except Exception as e:
            last = e
            time.sleep(0.5)
    raise last


_serial.Serial.__init__ = _patched_init

from pymavlink import mavutil  # noqa: E402
import os  # noqa: E402

SERIAL_PORT = sys.argv[1]
BAUD_RATE = int(sys.argv[2])
LOG_PATH = sys.argv[3] if len(sys.argv) > 3 else "adsb_log.jsonl"
MAVLINK_PACKET_TYPE_LIST = ['ADSB_VEHICLE', 'HEARTBEAT',
                            'MESSAGE_INTERVAL', 'REQUEST_DATA_STREAM']

log_file = None
try:
    log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    print(f"日志: {LOG_PATH}")
except Exception as e:
    print(f"! 无法打开日志 {LOG_PATH}: {e} (仅解码不保存)")


def log_adsb(msg):
    """ADSB_VEHICLE -> 一行 JSONL, 字段与 adsb_server.py 兼容"""
    rec = {
        "t": datetime.now().isoformat(timespec="seconds"),
        "src": "mavlink",
        "icao": "%06X" % msg.ICAO_address,
        "lat": round(msg.lat / 1e7, 6) if msg.flags & 0x0001 else None,
        "lon": round(msg.lon / 1e7, 6) if msg.flags & 0x0001 else None,
        "alt_ft": round(msg.altitude / 304.8) if msg.flags & 0x0002 else None,
        "gs_kt": round(msg.hor_velocity / 51.4444) if msg.flags & 0x0008 else None,
        "trk_deg": round(msg.heading / 100.0) if msg.flags & 0x0004 else None,
        "vr_fpm": round(msg.ver_velocity * 1.9685) if msg.flags & 0x0080 else None,
        "callsign": (msg.callsign or "").rstrip("\x00 ").strip() or None,
        "tslc": msg.tslc,
        "flags": msg.flags,
    }
    if log_file:
        log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")


print(f"Connecting to MAVLINK device on {SERIAL_PORT} at {BAUD_RATE} baud.")
mavlink_connection = mavutil.mavlink_connection(SERIAL_PORT, baud=BAUD_RATE)

try:
    while True:
        msg = mavlink_connection.recv_match(type=MAVLINK_PACKET_TYPE_LIST,
                                            blocking=True)
        if sys.stdout.isatty():
            os.system('cls')  # Clear the screen (仅交互终端)
        print("ICAO Addr |Latitude  |Longitude |Alt Type  |Alt (m)   |Hdg (deg) |Hvel (m/s)|Vvel (m/s)|Callsign  |Type      |TSLC (sec)|Flags     |Squawk")
        print("----------|----------|----------|----------|----------|----------|----------|----------|----------|----------|----------|----------|----------")

        while msg.get_type() == 'ADSB_VEHICLE':
            print(f"{msg.ICAO_address:10x}|{msg.lat / 1e7:+10.4f}|{msg.lon / 1e7:+10.4f}|{msg.altitude_type:10x}|"
                  f"{msg.altitude / 1e3:10.2f}|{msg.heading / 100:10.4f}|{msg.hor_velocity / 100:10}|"
                  f"{msg.ver_velocity / 100:10}|{msg.callsign:10}|{msg.emitter_type:10}|{msg.tslc:10}|{msg.flags:10b}|"
                  f"{msg.squawk:10o}")
            log_adsb(msg)
            msg = mavlink_connection.recv_match(type=MAVLINK_PACKET_TYPE_LIST,
                                                blocking=True)
        if msg.get_type() == 'HEARTBEAT':
            print(f"(heartbeat, status={msg.system_status}, link ok)")
except KeyboardInterrupt:
    print("\n退出")
finally:
    if log_file:
        log_file.close()
        print(f"日志已保存: {LOG_PATH}")
