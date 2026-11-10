#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mousekey — 用鍵盤按鍵取代滑鼠按鍵（Linux：evdev + uinput）

為什麼要這樣做？
  Wayland 下沒有任何「全域鍵盤 hook」API，任何程式都無法偷聽按鍵。
  唯一可行的通用做法是：
    1. 直接讀 /dev/input/event*（核心層，繞過 compositor）
    2. 獨佔（EVIOCGRAB）該鍵盤，把按鍵原樣轉送到自建的虛擬鍵盤
    3. 想取代的按鍵不轉送，改成送出滑鼠事件到自建的虛擬滑鼠

  這樣在 Wayland / X11 / 甚至純 TTY 都能用，且不需要 X11 或任何圖形庫。

用法：
  ./mousekey.py --list-devices        # 看看有哪些鍵盤
  ./mousekey.py --check               # 檢查設定檔
  ./mousekey.py --dry-run             # 只印出動作，不真的送出（除錯用）
  ./mousekey.py                       # 正式執行
  ./mousekey.py --send toggle         # 叫執行中的實例切換開關

需要一次性權限設定，請先執行 setup-permissions.sh。
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import glob
import os
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time
import tomllib

__version__ = "0.1.0"

# --------------------------------------------------------------------------
# 核心常數
# --------------------------------------------------------------------------

EV_SYN, EV_KEY, EV_REL, EV_MSC, EV_LED, EV_REP = 0, 1, 2, 4, 17, 20
SYN_REPORT = 0

REL_X, REL_Y, REL_WHEEL, REL_HWHEEL = 0, 1, 8, 6

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114
BTN_RANGE = range(0x100, 0x120)  # BTN_* 的區間（滑鼠鍵）
KEY_MAX = 0x2FF

KEY_ESC = 1

BUTTONS = {
    "left": BTN_LEFT,
    "right": BTN_RIGHT,
    "middle": BTN_MIDDLE,
    "side": BTN_SIDE,
    "extra": BTN_EXTRA,
}
WHEELS = {
    "wheel_up": (REL_WHEEL, 1),
    "wheel_down": (REL_WHEEL, -1),
    "wheel_left": (REL_HWHEEL, -1),
    "wheel_right": (REL_HWHEEL, 1),
}
ACTIONS = set(BUTTONS) | set(WHEELS) | {"double"}

# --------------------------------------------------------------------------
# 按鍵名稱表（由 kernel 的 include/uapi/linux/input-event-codes.h 產生）
# --------------------------------------------------------------------------

_RAW_KEY_TABLE = """
RESERVED=0 ESC=1 1=2 2=3 3=4 4=5 5=6 6=7 7=8 8=9 9=10 0=11 MINUS=12 EQUAL=13
BACKSPACE=14 TAB=15 Q=16 W=17 E=18 R=19 T=20 Y=21 U=22 I=23 O=24 P=25 LEFTBRACE=26
RIGHTBRACE=27 ENTER=28 LEFTCTRL=29 A=30 S=31 D=32 F=33 G=34 H=35 J=36 K=37 L=38
SEMICOLON=39 APOSTROPHE=40 GRAVE=41 LEFTSHIFT=42 BACKSLASH=43 Z=44 X=45 C=46 V=47 B=48
N=49 M=50 COMMA=51 DOT=52 SLASH=53 RIGHTSHIFT=54 KPASTERISK=55 LEFTALT=56 SPACE=57
CAPSLOCK=58 F1=59 F2=60 F3=61 F4=62 F5=63 F6=64 F7=65 F8=66 F9=67 F10=68 NUMLOCK=69
SCROLLLOCK=70 KP7=71 KP8=72 KP9=73 KPMINUS=74 KP4=75 KP5=76 KP6=77 KPPLUS=78 KP1=79
KP2=80 KP3=81 KP0=82 KPDOT=83 ZENKAKUHANKAKU=85 102ND=86 F11=87 F12=88 RO=89 KATAKANA=90
HIRAGANA=91 HENKAN=92 KATAKANAHIRAGANA=93 MUHENKAN=94 KPJPCOMMA=95 KPENTER=96
RIGHTCTRL=97 KPSLASH=98 SYSRQ=99 RIGHTALT=100 LINEFEED=101 HOME=102 UP=103 PAGEUP=104
LEFT=105 RIGHT=106 END=107 DOWN=108 PAGEDOWN=109 INSERT=110 DELETE=111 MACRO=112
MUTE=113 VOLUMEDOWN=114 VOLUMEUP=115 POWER=116 KPEQUAL=117 KPPLUSMINUS=118 PAUSE=119
SCALE=120 KPCOMMA=121 HANGEUL=122 HANJA=123 YEN=124 LEFTMETA=125 RIGHTMETA=126
COMPOSE=127 STOP=128 AGAIN=129 PROPS=130 UNDO=131 FRONT=132 COPY=133 OPEN=134 PASTE=135
FIND=136 CUT=137 HELP=138 MENU=139 CALC=140 SETUP=141 SLEEP=142 WAKEUP=143 FILE=144
SENDFILE=145 DELETEFILE=146 XFER=147 PROG1=148 PROG2=149 WWW=150 MSDOS=151 COFFEE=152
ROTATE_DISPLAY=153 CYCLEWINDOWS=154 MAIL=155 BOOKMARKS=156 COMPUTER=157 BACK=158
FORWARD=159 CLOSECD=160 EJECTCD=161 EJECTCLOSECD=162 NEXTSONG=163 PLAYPAUSE=164
PREVIOUSSONG=165 STOPCD=166 RECORD=167 REWIND=168 PHONE=169 ISO=170 CONFIG=171
HOMEPAGE=172 REFRESH=173 EXIT=174 MOVE=175 EDIT=176 SCROLLUP=177 SCROLLDOWN=178
KPLEFTPAREN=179 KPRIGHTPAREN=180 NEW=181 REDO=182 F13=183 F14=184 F15=185 F16=186
F17=187 F18=188 F19=189 F20=190 F21=191 F22=192 F23=193 F24=194 PLAYCD=200 PAUSECD=201
PROG3=202 PROG4=203 ALL_APPLICATIONS=204 SUSPEND=205 CLOSE=206 PLAY=207 FASTFORWARD=208
BASSBOOST=209 PRINT=210 HP=211 CAMERA=212 SOUND=213 QUESTION=214 EMAIL=215 CHAT=216
SEARCH=217 CONNECT=218 FINANCE=219 SPORT=220 SHOP=221 ALTERASE=222 CANCEL=223
BRIGHTNESSDOWN=224 BRIGHTNESSUP=225 MEDIA=226 SWITCHVIDEOMODE=227 KBDILLUMTOGGLE=228
KBDILLUMDOWN=229 KBDILLUMUP=230 SEND=231 REPLY=232 FORWARDMAIL=233 SAVE=234
DOCUMENTS=235 BATTERY=236 BLUETOOTH=237 WLAN=238 UWB=239 UNKNOWN=240 VIDEO_NEXT=241
VIDEO_PREV=242 BRIGHTNESS_CYCLE=243 BRIGHTNESS_AUTO=244 DISPLAY_OFF=245 WWAN=246
RFKILL=247 MICMUTE=248 OK=352 SELECT=353 GOTO=354 CLEAR=355 POWER2=356 OPTION=357
INFO=358 TIME=359 VENDOR=360 ARCHIVE=361 PROGRAM=362 CHANNEL=363 FAVORITES=364 EPG=365
PVR=366 MHP=367 LANGUAGE=368 TITLE=369 SUBTITLE=370 ANGLE=371 FULL_SCREEN=372 MODE=373
KEYBOARD=374 ASPECT_RATIO=375 PC=376 TV=377 TV2=378 VCR=379 VCR2=380 SAT=381 SAT2=382
CD=383 TAPE=384 RADIO=385 TUNER=386 PLAYER=387 TEXT=388 DVD=389 AUX=390 MP3=391
AUDIO=392 VIDEO=393 DIRECTORY=394 LIST=395 MEMO=396 CALENDAR=397 RED=398 GREEN=399
YELLOW=400 BLUE=401 CHANNELUP=402 CHANNELDOWN=403 FIRST=404 LAST=405 AB=406 NEXT=407
RESTART=408 SLOW=409 SHUFFLE=410 BREAK=411 PREVIOUS=412 DIGITS=413 TEEN=414 TWEN=415
VIDEOPHONE=416 GAMES=417 ZOOMIN=418 ZOOMOUT=419 ZOOMRESET=420 WORDPROCESSOR=421
EDITOR=422 SPREADSHEET=423 GRAPHICSEDITOR=424 PRESENTATION=425 DATABASE=426 NEWS=427
VOICEMAIL=428 ADDRESSBOOK=429 MESSENGER=430 DISPLAYTOGGLE=431 SPELLCHECK=432 LOGOFF=433
DOLLAR=434 EURO=435 FRAMEBACK=436 FRAMEFORWARD=437 CONTEXT_MENU=438 MEDIA_REPEAT=439
10CHANNELSUP=440 10CHANNELSDOWN=441 IMAGES=442 NOTIFICATION_CENTER=444 PICKUP_PHONE=445
HANGUP_PHONE=446 LINK_PHONE=447 DEL_EOL=448 DEL_EOS=449 INS_LINE=450 DEL_LINE=451 FN=464
FN_ESC=465 FN_F1=466 FN_F2=467 FN_F3=468 FN_F4=469 FN_F5=470 FN_F6=471 FN_F7=472
FN_F8=473 FN_F9=474 FN_F10=475 FN_F11=476 FN_F12=477 FN_1=478 FN_2=479 FN_D=480 FN_E=481
FN_F=482 FN_S=483 FN_B=484 FN_RIGHT_SHIFT=485 BRL_DOT1=497 BRL_DOT2=498 BRL_DOT3=499
BRL_DOT4=500 BRL_DOT5=501 BRL_DOT6=502 BRL_DOT7=503 BRL_DOT8=504 BRL_DOT9=505
BRL_DOT10=506 NUMERIC_0=512 NUMERIC_1=513 NUMERIC_2=514 NUMERIC_3=515 NUMERIC_4=516
NUMERIC_5=517 NUMERIC_6=518 NUMERIC_7=519 NUMERIC_8=520 NUMERIC_9=521 NUMERIC_STAR=522
NUMERIC_POUND=523 NUMERIC_A=524 NUMERIC_B=525 NUMERIC_C=526 NUMERIC_D=527
CAMERA_FOCUS=528 WPS_BUTTON=529 TOUCHPAD_TOGGLE=530 TOUCHPAD_ON=531 TOUCHPAD_OFF=532
CAMERA_ZOOMIN=533 CAMERA_ZOOMOUT=534 CAMERA_UP=535 CAMERA_DOWN=536 CAMERA_LEFT=537
CAMERA_RIGHT=538 ATTENDANT_ON=539 ATTENDANT_OFF=540 ATTENDANT_TOGGLE=541
LIGHTS_TOGGLE=542 ALS_TOGGLE=560 ROTATE_LOCK_TOGGLE=561 REFRESH_RATE_TOGGLE=562
BUTTONCONFIG=576 TASKMANAGER=577 JOURNAL=578 CONTROLPANEL=579 APPSELECT=580
SCREENSAVER=581 VOICECOMMAND=582 ASSISTANT=583 KBD_LAYOUT_NEXT=584 EMOJI_PICKER=585
DICTATE=586 CAMERA_ACCESS_ENABLE=587 CAMERA_ACCESS_DISABLE=588 CAMERA_ACCESS_TOGGLE=589
ACCESSIBILITY=590 DO_NOT_DISTURB=591 BRIGHTNESS_MIN=592 BRIGHTNESS_MAX=593
EPRIVACY_SCREEN_ON=594 EPRIVACY_SCREEN_OFF=595 ACTION_ON_SELECTION=596
CONTEXTUAL_INSERT=597 CONTEXTUAL_QUERY=598 KBDINPUTASSIST_PREV=608
KBDINPUTASSIST_NEXT=609 KBDINPUTASSIST_PREVGROUP=610 KBDINPUTASSIST_NEXTGROUP=611
KBDINPUTASSIST_ACCEPT=612 KBDINPUTASSIST_CANCEL=613 RIGHT_UP=614 RIGHT_DOWN=615
LEFT_UP=616 LEFT_DOWN=617 ROOT_MENU=618 MEDIA_TOP_MENU=619 NUMERIC_11=620 NUMERIC_12=621
AUDIO_DESC=622 3D_MODE=623 NEXT_FAVORITE=624 STOP_RECORD=625 PAUSE_RECORD=626 VOD=627
UNMUTE=628 FASTREVERSE=629 SLOWREVERSE=630 DATA=631 ONSCREEN_KEYBOARD=632
PRIVACY_SCREEN_TOGGLE=633 SELECTIVE_SCREENSHOT=634 NEXT_ELEMENT=635 PREVIOUS_ELEMENT=636
AUTOPILOT_ENGAGE_TOGGLE=637 MARK_WAYPOINT=638 SOS=639 NAV_CHART=640 FISHING_CHART=641
SINGLE_RANGE_RADAR=642 DUAL_RANGE_RADAR=643 RADAR_OVERLAY=644 TRADITIONAL_SONAR=645
CLEARVU_SONAR=646 SIDEVU_SONAR=647 NAV_INFO=648 BRIGHTNESS_MENU=649 MACRO1=656
MACRO2=657 MACRO3=658 MACRO4=659 MACRO5=660 MACRO6=661 MACRO7=662 MACRO8=663 MACRO9=664
MACRO10=665 MACRO11=666 MACRO12=667 MACRO13=668 MACRO14=669 MACRO15=670 MACRO16=671
MACRO17=672 MACRO18=673 MACRO19=674 MACRO20=675 MACRO21=676 MACRO22=677 MACRO23=678
MACRO24=679 MACRO25=680 MACRO26=681 MACRO27=682 MACRO28=683 MACRO29=684 MACRO30=685
MACRO_RECORD_START=688 MACRO_RECORD_STOP=689 MACRO_PRESET_CYCLE=690 MACRO_PRESET1=691
MACRO_PRESET2=692 MACRO_PRESET3=693 KBD_LCD_MENU1=696 KBD_LCD_MENU2=697
KBD_LCD_MENU3=698 KBD_LCD_MENU4=699 KBD_LCD_MENU5=700 PERFORMANCE=701 MAX=767
"""

KEY_CODES: dict[str, int] = {}
for _tok in _RAW_KEY_TABLE.split():
    _name, _, _val = _tok.partition("=")
    KEY_CODES[_name] = int(_val)
del _tok, _name, _val

KEY_NAMES: dict[int, str] = {v: k for k, v in KEY_CODES.items()}


class ConfigError(Exception):
    pass


def key_code(name) -> int:
    """把設定檔裡的名字轉成 keycode。接受 F / KEY_F / key_f / 58 / 0x3a。"""
    s = str(name).strip().upper()
    if s.startswith("KEY_"):
        s = s[4:]
    if s in KEY_CODES:
        return KEY_CODES[s]
    try:
        return int(s, 0)
    except ValueError:
        raise ConfigError(f"認不得的按鍵名稱：{name!r}") from None


def key_name(code: int) -> str:
    return KEY_NAMES.get(code, f"0x{code:x}")


# --------------------------------------------------------------------------
# evdev / uinput 的 ioctl 封裝
# --------------------------------------------------------------------------

def _ioc(direction: int, type_: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (type_ << 8) | nr


_E, _U = ord("E"), ord("U")
EVIOCGNAME = lambda n: _ioc(2, _E, 0x06, n)          # noqa: E731
EVIOCGPHYS = lambda n: _ioc(2, _E, 0x07, n)          # noqa: E731
EVIOCGBIT = lambda ev, n: _ioc(2, _E, 0x20 + ev, n)  # noqa: E731
EVIOCGRAB = _ioc(1, _E, 0x90, 4)

UI_DEV_CREATE = _ioc(0, _U, 1, 0)
UI_DEV_DESTROY = _ioc(0, _U, 2, 0)
UI_DEV_SETUP = _ioc(1, _U, 3, 92)
UI_SET_EVBIT = _ioc(1, _U, 100, 4)
UI_SET_KEYBIT = _ioc(1, _U, 101, 4)
UI_SET_RELBIT = _ioc(1, _U, 102, 4)

_EVENT = struct.Struct("<qqHHi")  # struct input_event (x86_64)
_BITS_BYTES = (KEY_MAX + 8) // 8


def _get_bits(fd: int, ev_type: int) -> set[int]:
    buf = bytearray(_BITS_BYTES)
    try:
        fcntl.ioctl(fd, EVIOCGBIT(ev_type, _BITS_BYTES), buf, True)
    except OSError:
        return set()
    out = set()
    for i, byte in enumerate(buf):
        if byte:
            base = i * 8
            for bit in range(8):
                if byte >> bit & 1:
                    out.add(base + bit)
    return out


def _get_name(fd: int) -> str:
    buf = bytearray(256)
    try:
        fcntl.ioctl(fd, EVIOCGNAME(256), buf, True)
    except OSError:
        return "?"
    return buf.split(b"\0", 1)[0].decode("utf-8", "replace")


def _get_phys(fd: int) -> str:
    """實體裝置會有 phys（例如 usb-0000:00:14.0-1/input0、isa0060/serio0/input0）。
    uinput 造出來的虛擬裝置沒有設 PHYS，所以是空字串 —— 用這個分辨真假。"""
    buf = bytearray(256)
    try:
        fcntl.ioctl(fd, EVIOCGPHYS(256), buf, True)
    except OSError:
        return ""
    return buf.split(b"\0", 1)[0].decode("utf-8", "replace")


# --------------------------------------------------------------------------
# 輸入裝置
# --------------------------------------------------------------------------

class InputDevice:
    """一個 /dev/input/eventN。"""

    def __init__(self, path: str, fd: int, name: str, keys: set[int], rels: set[int],
                 phys: str = ""):
        self.path = path
        self.fd = fd
        self.name = name
        self.keys = keys
        self.rels = rels
        self.phys = phys
        self.grabbed = False
        self.removed = False

    @classmethod
    def open(cls, path: str) -> "InputDevice":
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            name = _get_name(fd)
            phys = _get_phys(fd)
            keys = _get_bits(fd, EV_KEY)
            rels = _get_bits(fd, EV_REL)
        except OSError:
            os.close(fd)
            raise
        return cls(path, fd, name, keys, rels, phys)

    @property
    def is_virtual(self) -> bool:
        """uinput 造出來的裝置（input-remapper、keyd、我們自己…）沒有 phys。"""
        return not self.phys

    # 鍵盤的判斷：有字母、空白、Enter、Shift，就不是滑鼠/麥克風/電源鍵
    @property
    def looks_like_keyboard(self) -> bool:
        need = {KEY_CODES["A"], KEY_CODES["Z"], KEY_CODES["SPACE"], KEY_CODES["ENTER"]}
        shift = {KEY_CODES["LEFTSHIFT"], KEY_CODES["RIGHTSHIFT"]}
        return need <= self.keys and bool(self.keys & shift)

    def grab(self, enable: bool = True) -> None:
        fcntl.ioctl(self.fd, EVIOCGRAB, 1 if enable else 0)
        self.grabbed = enable

    def read(self) -> list[tuple[int, int, int]]:
        try:
            data = os.read(self.fd, _EVENT.size * 128)
        except BlockingIOError:
            return []
        out = []
        for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _, _, etype, code, value = _EVENT.unpack_from(data, off)
            out.append((etype, code, value))
        return out

    def close(self) -> None:
        if self.fd is None:
            return
        if self.grabbed:
            try:
                self.grab(False)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None


class UinputDevice:
    """自建的虛擬裝置。"""

    def __init__(self, name: str, keys=(), rels=(), ev_types=(EV_KEY, EV_REL)):
        try:
            fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            raise SystemExit(
                "找不到 /dev/uinput。\n"
                "請先執行 sudo modprobe uinput，並把模組設為開機載入：\n"
                "  echo uinput | sudo tee /etc/modules-load.d/uinput.conf"
            ) from None
        except PermissionError:
            raise SystemExit(
                "沒有 /dev/uinput 的寫入權限。\n"
                "請執行 setup-permissions.sh（把使用者加入 input 群組並設定 udev 規則），"
                "或改用 sudo 執行本程式。"
            ) from None

        self.fd = fd
        self.name = name
        try:
            for ev in ev_types:
                fcntl.ioctl(fd, UI_SET_EVBIT, ev)
            for k in sorted(set(keys)):
                fcntl.ioctl(fd, UI_SET_KEYBIT, k)
            for r in sorted(set(rels)):
                fcntl.ioctl(fd, UI_SET_RELBIT, r)
            # struct uinput_setup：input_id(4*u16) + name[80] + ff_effects_max(u32)
            setup = struct.pack("<HHHH80sI", 0x03, 0x1234, 0x5678, 1, name.encode()[:80], 0)
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE, 0)
        except OSError:
            os.close(fd)
            raise
        time.sleep(0.12)  # 讓 udev / compositor 有時間看到新裝置

    def emit(self, events: list[tuple[int, int, int]]) -> None:
        if not events:
            return
        try:
            os.write(self.fd, b"".join(_EVENT.pack(0, 0, t, c, v) for t, c, v in events))
        except OSError as exc:
            if exc.errno != errno.EAGAIN:
                raise

    def destroy(self) -> None:
        if self.fd is None:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY, 0)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None


# --------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------

# realpath：用 symlink 安裝到 ~/.local/bin 時，才找得到真正的程式旁邊的 config
SELF_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_CONFIG = os.path.join(SELF_DIR, "config.toml")


def _xdg_config() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "mousekey", "config.toml")

FALLBACK_CONFIG = """
[general]
toggle_key = "CAPSLOCK"
grab = true
feedback = "notify"
wheel_first_ms = 320
wheel_repeat_ms = 70
control_socket = true

[keys]
F = "left"
D = "right"
S = "middle"
A = "double"
R = "wheel_up"
V = "wheel_down"
"""


class Config:
    def __init__(self, raw: dict, source: str):
        g = raw.get("general", {}) or {}
        d = raw.get("device", {}) or {}
        k = raw.get("keys", {}) or {}

        self.source = source
        self.toggle_key = key_code(g.get("toggle_key", "CAPSLOCK"))
        self.grab = bool(g.get("grab", True))
        self.feedback = str(g.get("feedback", "notify"))
        self.wheel_first_ms = int(g.get("wheel_first_ms", 320))
        # 同一把鍵盤常常有兩三條 event 路徑，會送出重複事件。
        # 同一個鍵在這麼短的時間內由「不同裝置」重複送來，就只算一次。
        self.dedup_ms = int(g.get("dedup_ms", 10))
        self.wheel_repeat_ms = int(g.get("wheel_repeat_ms", 70))
        self.control_socket = bool(g.get("control_socket", True))
        # tap-hold：輕按切換鍵 = 鎖定開關；按住 = 暫時生效，放開就回原狀
        self.tap_hold = bool(g.get("tap_hold", True))
        self.tap_ms = int(g.get("tap_ms", 250))

        match = d.get("match", []) or []
        if isinstance(match, str):
            match = [match]
        self.match = [str(m) for m in match]

        self.mapping: dict[int, str] = {}
        for name, action in k.items():
            action = str(action).strip().lower()
            if action not in ACTIONS:
                raise ConfigError(
                    f"[keys] {name} = {action!r} 不是合法動作。"
                    f"可用：{', '.join(sorted(ACTIONS))}"
                )
            self.mapping[key_code(name)] = action

        if self.toggle_key in self.mapping:
            raise ConfigError("toggle_key 不能同時出現在 [keys] 裡")

    def describe(self) -> str:
        lines = [
            f"設定檔      : {self.source}",
            f"切換鍵      : {key_name(self.toggle_key)}",
            f"獨佔鍵盤    : {self.grab}",
            f"回饋        : {self.feedback}",
            f"tap-hold    : {'開（輕按 %.0fms 內=切換，按住=暫時）' % self.tap_ms if self.tap_hold else '關'}",
            f"滾輪        : 首次 {self.wheel_first_ms}ms，之後每 {self.wheel_repeat_ms}ms",
            "按鍵對應    :",
        ]
        for code, action in sorted(self.mapping.items()):
            lines.append(f"  {key_name(code):<14} → {action}")
        return "\n".join(lines)


def load_config(path: str | None) -> Config:
    if path:
        with open(path, "rb") as fh:
            return Config(tomllib.load(fh), path)
    # 找尋順序：程式旁邊 → ~/.config/mousekey/ → 內建預設
    for candidate in (DEFAULT_CONFIG, _xdg_config()):
        if os.path.exists(candidate):
            with open(candidate, "rb") as fh:
                return Config(tomllib.load(fh), candidate)
    return Config(tomllib.loads(FALLBACK_CONFIG), "<內建預設>")


# --------------------------------------------------------------------------
# 狀態機：把鍵盤事件變成滑鼠事件
# --------------------------------------------------------------------------

def _finalize(events: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if events and events[-1][0] != EV_SYN:
        return events + [(EV_SYN, SYN_REPORT, 0)]
    return events


class Engine:
    def __init__(self, cfg: Config, on_toggle=None):
        self.cfg = cfg
        self.enabled = False
        self.quit = False
        self.pressed: set[int] = set()
        self.held: dict[int, str] = {}
        self.wheels: dict[int, list[float]] = {}
        self.forwarded_down: set[int] = set()
        self.locked = False          # 輕按切換後鎖定的狀態
        self.momentary = False       # 按住切換鍵時的暫時狀態
        self.toggle_pressed_at: float | None = None
        self.on_toggle = on_toggle or (lambda on: None)

    # -- 對外接口 --------------------------------------------------------

    def handle(self, evtype: int, code: int, value: int):
        """回傳 (要轉送到虛擬鍵盤的事件, 要送到虛擬滑鼠的事件)。"""
        kbd: list[tuple[int, int, int]] = []
        mouse: list[tuple[int, int, int]] = []

        if evtype == EV_SYN:
            return kbd, mouse
        if evtype != EV_KEY:
            kbd.append((evtype, code, value))
            return kbd, mouse

        if value == 1:
            self.pressed.add(code)
        elif value == 0:
            self.pressed.discard(code)

        # 切換鍵：永遠吞掉，不會變成 Caps Lock
        if code == self.cfg.toggle_key:
            self._handle_toggle_key(value, mouse)
            return kbd, mouse

        if value != 2 and self._panic_combo(code, value):
            self.quit = True
            return kbd, mouse

        # 讓 compositor 自己處理按鍵重複，避免重複兩次
        if value == 2:
            return kbd, mouse

        action = self.cfg.mapping.get(code) if self.enabled else None
        if action is None:
            kbd.append((evtype, code, value))
            if value == 1:
                self.forwarded_down.add(code)
            elif value == 0:
                self.forwarded_down.discard(code)
            return kbd, mouse

        if value == 1:
            self._start(code, action, mouse)
        elif code in self.forwarded_down:
            # 按下的時候還是「一般按鍵」，放開時才切到滑鼠模式：
            # 補送 up，否則應用程式會卡鍵。
            self.forwarded_down.discard(code)
            kbd.append((evtype, code, value))
        else:
            self._end(code, action, mouse)
        return kbd, mouse

    def _handle_toggle_key(self, value: int, mouse: list) -> None:
        if not self.cfg.tap_hold:
            if value == 1:
                self.set_enabled(not self.enabled, mouse)
            return

        if value == 1:
            # 先當成「按住」立刻生效，放開時再決定是輕按還是長按
            self.toggle_pressed_at = time.monotonic()
            self.momentary = True
            self._sync(mouse)
        elif value == 0:
            started = self.toggle_pressed_at
            self.toggle_pressed_at = None
            self.momentary = False
            if started is not None and (time.monotonic() - started) * 1000 < self.cfg.tap_ms:
                self.locked = not self.locked     # 輕按 = 切換鎖定
            self._sync(mouse)

    def _sync(self, mouse: list) -> None:
        want = self.locked or self.momentary
        if want != self.enabled:
            self.set_enabled(want, mouse)

    def tick(self, now: float) -> list[tuple[int, int, int]]:
        """滾輪的連續觸發。"""
        out: list[tuple[int, int, int]] = []
        for code, state in list(self.wheels.items()):
            if now >= state[0]:
                rel, val = WHEELS[self.held[code]]
                out += [(EV_REL, rel, val), (EV_SYN, SYN_REPORT, 0)]
                state[0] = now + state[1]
        return out

    def next_deadline(self) -> float | None:
        if not self.wheels:
            return None
        return min(s[0] for s in self.wheels.values())

    def set_enabled(self, on: bool, mouse: list) -> None:
        if on == self.enabled:
            return
        self.enabled = on
        if not on:
            for code, action in list(self.held.items()):
                self._end(code, action, mouse)
            self.held.clear()
            self.wheels.clear()
        self.on_toggle(on)

    # -- 內部 ------------------------------------------------------------

    def _start(self, code: int, action: str, mouse: list) -> None:
        self.held[code] = action
        if action in BUTTONS:
            mouse += [(EV_KEY, BUTTONS[action], 1), (EV_SYN, SYN_REPORT, 0)]
        elif action == "double":
            # 按下送第一次點擊，放開送第二次 → 天然的雙擊
            mouse += _double_click()
        elif action in WHEELS:
            rel, val = WHEELS[action]
            self.wheels[code] = [
                time.monotonic() + self.cfg.wheel_first_ms / 1000.0,
                self.cfg.wheel_repeat_ms / 1000.0,
            ]
            mouse += [(EV_REL, rel, val), (EV_SYN, SYN_REPORT, 0)]

    def _end(self, code: int, action: str, mouse: list) -> None:
        # 只有真的送過「按下」才補「放開」，避免送出孤兒的 up 事件
        if self.held.pop(code, None) is None:
            return
        if action in BUTTONS:
            mouse += [(EV_KEY, BUTTONS[action], 0), (EV_SYN, SYN_REPORT, 0)]
        elif action == "double":
            mouse += _double_click()
        elif action in WHEELS:
            self.wheels.pop(code, None)

    def _panic_combo(self, code: int, value: int) -> bool:
        if value != 1 or code != KEY_ESC:
            return False
        ctrl = self.pressed & {KEY_CODES["LEFTCTRL"], KEY_CODES["RIGHTCTRL"]}
        alt = self.pressed & {KEY_CODES["LEFTALT"], KEY_CODES["RIGHTALT"]}
        shift = self.pressed & {KEY_CODES["LEFTSHIFT"], KEY_CODES["RIGHTSHIFT"]}
        return bool(ctrl and alt and shift)


def _double_click() -> list[tuple[int, int, int]]:
    return [
        (EV_KEY, BTN_LEFT, 1), (EV_SYN, SYN_REPORT, 0),
        (EV_KEY, BTN_LEFT, 0), (EV_SYN, SYN_REPORT, 0),
    ]


# --------------------------------------------------------------------------
# 裝置探索
# --------------------------------------------------------------------------

ENUM_ERRORS: list[tuple[str, str]] = []


def enumerate_devices() -> list[InputDevice]:
    found = []
    ENUM_ERRORS.clear()
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice.open(path)
        except PermissionError:
            ENUM_ERRORS.append((path, "Permission denied"))
            continue
        except OSError as exc:
            ENUM_ERRORS.append((path, exc.strerror or str(exc)))
            continue
        if dev.name.startswith("mousekey"):
            dev.close()
            continue
        found.append(dev)
    return found


def device_matches(cfg: Config, dev: InputDevice) -> bool:
    """這個裝置該不該被抓？（select_devices 與執行中的重掃都用同一套規則）"""
    if cfg.match:
        for pat in cfg.match:
            if pat.startswith("/"):
                if dev.path == pat:
                    return True
            elif pat.lower() in dev.name.lower():
                return True
        return False
    return dev.looks_like_keyboard and not dev.is_virtual


def select_devices(cfg: Config) -> tuple[list[InputDevice], list[str]]:
    notes = []
    candidates = enumerate_devices()

    if cfg.match:
        picked = []
        for dev in candidates:
            if device_matches(cfg, dev):
                picked.append(dev)
            else:
                dev.close()
        if not picked:
            notes.append(
                "設定的裝置現在不存在：" + "、".join(cfg.match) + "\n"
                "    /dev/input/eventN 的編號在拔插或重開機後會變，建議改用名稱片段，例如\n"
                "      match = [\"AT Translated\"]\n"
                "    用 ./mousekey.py --probe 可以查到正確名稱。"
            )
        for dev in picked:
            if not dev.looks_like_keyboard:
                notes.append(
                    f"⚠ {dev.path}（{dev.name}）看起來不像鍵盤 —— 可能是編號跑掉了。"
                )
        return picked, notes

    wrong = [d for d in candidates if not d.looks_like_keyboard]
    virt = [d for d in candidates if d.looks_like_keyboard and d.is_virtual]
    picked = [d for d in candidates if d.looks_like_keyboard and not d.is_virtual]

    for dev in wrong + virt:
        dev.close()

    if virt:
        names = "、".join(sorted({d.name for d in virt}))
        notes.append(
            f"略過 {len(virt)} 個虛擬裝置（{names}）——"
            "這是其他程式（input-remapper / keyd）產生出來的，搶過來會互相打架。"
        )
    return picked, notes


def cmd_list_keys() -> int:
    items = sorted(KEY_NAMES.items())
    print("可用按鍵名稱（寫在 config.toml 的名字，括號內是 keycode）")
    print("找特定按鍵： ./mousekey.py --keys | grep -i num\n")
    col_w, per_line = 19, 5
    for i in range(0, len(items), per_line):
        row = "".join(f"{f'{n}({c})':<{col_w}}" for c, n in items[i:i + per_line])
        print(row.rstrip())
    print(f"\n共 {len(items)} 個。也可以直接寫數字：58 或 0x3a。")
    return 0


def process_identity() -> str:
    """service 與前景執行的權限差在哪，看這行最快。"""
    import grp
    import pwd

    try:
        pw = pwd.getpwuid(os.getuid())
        who = f"{pw.pw_name} (uid {pw.pw_uid}, gid {pw.pw_gid})"
    except KeyError:
        who = f"uid {os.getuid()}, gid {os.getgid()}"
    names = []
    for gid in os.getgroups():
        try:
            names.append(grp.getgrgid(gid).gr_name)
        except KeyError:
            names.append(str(gid))
    return f"{who}　groups: {', '.join(names)}"


def permission_diagnosis() -> list[str]:
    """告訴使用者到底卡在哪一步，而不是只說「沒有權限」。"""
    if not glob.glob("/dev/input/event*"):
        return ["/dev/input/event* 不存在 —— 這個環境看不到輸入裝置（容器/沙箱裡很正常）"]

    out: list[str] = []
    try:
        import grp
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        user, grp = str(os.getuid()), None

    try:
        entry = grp.getgrnam("input") if grp else None
    except KeyError:
        entry = None

    if entry is None:
        out.append("系統上找不到 input 群組（罕見）→ 直接 sudo 執行，或改用自訂的 udev 規則")
    elif entry.gr_gid in os.getgroups():
        out.append(
            "這個 shell 已經有 input 群組權限，卻還是讀不到 → 看看裝置權限：ls -l /dev/input/event*"
        )
    elif user in entry.gr_mem:
        out.append(
            f"你（{user}）已經在 input 群組裡了，但「目前這個 shell / 桌面 session」還沒套用。\n"
            "    立即解法： newgrp input   然後再跑本程式\n"
            "    永久解法： 登出 niri 再登入（或重開機）"
        )
    else:
        out.append(
            "你還沒被加入 input 群組 → 執行 ./setup-permissions.sh，完成後登出再登入"
        )

    if not os.path.exists("/dev/uinput"):
        out.append("/dev/uinput 不存在 → sudo modprobe uinput")
    elif not os.access("/dev/uinput", os.W_OK):
        out.append("/dev/uinput 不能寫 → 同樣是群組還沒生效，或還沒跑 setup-permissions.sh")

    return out


def _grab_test(dev: InputDevice) -> str:
    """試著獨佔一下再放開，判斷是否已被其他程式（input-remapper 等）佔用。"""
    try:
        fcntl.ioctl(dev.fd, EVIOCGRAB, 1)
    except OSError as exc:
        return "被佔用" if exc.errno == errno.EBUSY else "不可用"
    try:
        fcntl.ioctl(dev.fd, EVIOCGRAB, 0)
    except OSError:
        pass
    return "可用"


def cmd_list_devices() -> int:
    print(f"{'路徑':<21} {'鍵盤':<4} {'類型':<4} {'鍵數':<5} {'獨佔':<6} 名稱")
    print("-" * 88)
    unreadable = 0
    readable = 0
    read_kbd = 0
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice.open(path)
        except PermissionError:
            unreadable += 1
            print(f"{path:<21} {'?':<4} {'':<4} {'':<5} {'':<6} (沒有讀取權限)")
            continue
        except OSError as exc:
            print(f"{path:<21} {'?':<4} {'':<4} {'':<5} {'':<6} ({exc.strerror})")
            continue
        readable += 1
        mark = "是" if dev.looks_like_keyboard else "－"
        read_kbd += 1 if dev.looks_like_keyboard else 0
        nkeys = len({k for k in dev.keys if k not in BTN_RANGE})
        kind = "虛擬" if dev.is_virtual else "實體"
        state = _grab_test(dev) if dev.looks_like_keyboard else "－"
        extra = " [含滑鼠鍵]" if dev.keys & set(BTN_RANGE) else ""
        print(f"{dev.path:<21} {mark:<4} {kind:<4} {nkeys:<5} {state:<6} {dev.name}{extra}")
        dev.close()

    print()
    if readable == 0:
        print("沒有半個裝置讀得到。原因：")
        for line in permission_diagnosis():
            print(f"  • {line}")
    elif read_kbd == 0:
        print("讀得到裝置，但沒有半個像鍵盤（需要 A/Z/Space/Enter/Shift）。")
        print("  • 若你有特殊鍵盤，可在 config.toml 的 [device] match 直接指定路徑")
    else:
        print("說明：")
        print("  • 「虛擬」是其他程式（input-remapper / keyd）造出來的裝置，mousekey 會自動略過")
        print("  • 「被佔用」表示那個裝置已經被別的程式獨佔，mousekey 也會略過")
        print("  • 不確定哪個才是你的鍵盤？跑 ./mousekey.py --probe 按幾個鍵就會告訴你")
    return 0


def cmd_probe(seconds: float = 10.0) -> int:
    """讓使用者按鍵，看事件是從哪個裝置進來的 —— 這是最可靠的辨識方式。"""
    devices = enumerate_devices()
    if not devices:
        print("讀不到任何輸入裝置。", file=sys.stderr)
        for line in permission_diagnosis():
            print(f"  • {line}", file=sys.stderr)
        return 2

    print(f"請在接下來 {seconds:.0f} 秒內，按幾下你平常用來打字的鍵（例如 A、空白鍵）。")
    print("（不會獨佔、不會影響輸入，只是聽一下）\n", flush=True)

    sel = selectors.DefaultSelector()
    for dev in devices:
        sel.register(dev.fd, selectors.EVENT_READ, dev)

    seen: dict[str, list[int]] = {}
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            for key, _mask in sel.select(0.2):
                dev = key.data
                for etype, code, value in dev.read():
                    if etype == EV_KEY and value == 1:
                        seen.setdefault(dev.path, []).append(code)
    finally:
        sel.close()
        for dev in devices:
            dev.close()

    if not seen:
        print("沒收到任何按鍵。可能原因：")
        print("  • 這台機器的鍵盤被別的程式獨佔了（input-remapper / keyd）")
        print("  • 你按的是滑鼠或觸控板")
        return 1

    print("收到按鍵的裝置（依次數排序）：\n")
    rows = sorted(seen.items(), key=lambda kv: -len(kv[1]))
    by_path = {}
    for dev in enumerate_devices():
        by_path[dev.path] = dev.name
        dev.close()
    for path, codes in rows:
        names = "、".join(dict.fromkeys(key_name(c) for c in codes[:8]))
        print(f"  {path:<21} {len(codes):>3} 次   {by_path.get(path, '?')}")
        print(f"  {'':<21} 按過：{names}")

    best = rows[0][0]
    best_name = by_path.get(best, "?")
    print(f"\n最可能是這個： {best}  ({best_name})")

    shared = [p for p, codes in rows[1:] if set(codes) & set(rows[0][1])]
    if shared:
        print("⚠ 有另一個裝置也收到同一批按鍵（同一把鍵盤的多條路徑）。")
        print("  只挑一個，否則按一下會變成兩下：")
        for p in shared:
            print(f"    {p}  {by_path.get(p, '?')}")

    print("\n把它寫進 config.toml（用名稱，跨重開機也有效）：\n")
    print(f'  [device]\n  match = ["{best_name}"]')
    print("\n注意：不要用 /dev/input/eventN，拔插或重開機後編號會變。")
    return 0


# --------------------------------------------------------------------------
# 回饋
# --------------------------------------------------------------------------

TRACE = False


def _describe(events) -> str:
    parts = []
    for etype, code, value in events:
        if etype == EV_SYN:
            continue
        if etype == EV_KEY:
            kind = "BTN" if code in BTN_RANGE else "KEY"
            state = {0: "up", 1: "down", 2: "repeat"}.get(value, str(value))
            parts.append(f"{kind} {key_name(code)} {state}")
        elif etype == EV_REL:
            parts.append(f"REL {code} {value:+d}")
        else:
            parts.append(f"type{etype} {code} {value}")
    return " | ".join(parts)


def _uinput_event_node(name: str) -> str | None:
    for path in glob.glob("/sys/class/input/event*/device/name"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if fh.read().strip() != name:
                    continue
        except OSError:
            continue
        return path.split("/")[-3]  # eventN
    return None


def udev_properties(name: str) -> set[str]:
    node = _uinput_event_node(name)  # eventN
    if node is None:
        return set()
    # udev 的資料檔是用 inputN 命名，要從 /sys/class/input/eventN/device 推回去
    try:
        base = os.path.basename(os.path.realpath(f"/sys/class/input/{node}/device"))
    except OSError:
        base = ""
    for key in (base, node):
        if not key:
            continue
        try:
            with open(f"/run/udev/data/+input:{key}", encoding="utf-8",
                      errors="replace") as fh:
                props = {ln[2:].split("=", 1)[0] for ln in fh if ln.startswith("E:")}
        except OSError:
            continue
        if props:
            return props
    return set()


def verify_uinput(name: str, want: str) -> bool:
    """確認 udev 有沒有把我們的虛擬裝置認成該有的類型。

    compositor 只理會 udev 標記過的裝置（ID_INPUT_MOUSE / ID_INPUT_KEYBOARD），
    沒有標記 = 整個裝置被忽略，按了完全沒反應，而且不會有任何錯誤訊息。
    """
    if not glob.glob("/sys/class/input/event*"):
        return True  # 沒有 sysfs（容器/沙箱），無從檢查

    # sysfs 節點在 UI_DEV_CREATE 時就同步出現了，不用等；要等的是 udev 跑完
    node = _uinput_event_node(name)
    props: set[str] = set()
    if node:
        for _ in range(10):
            props = udev_properties(name)
            if props:
                break
            time.sleep(0.05)

    if not props:
        return True  # 讀不到 udev 資訊（權限或時機），不要亂叫
    if want in props:
        return True

    kind = "滑鼠" if want == "ID_INPUT_MOUSE" else "鍵盤"
    print(
        f"⚠ 虛擬{kind}「{name}」沒有被 udev 認成{kind}（缺少 {want}）。\n"
        f"   compositor 會直接忽略這個裝置，所以按了不會有反應。\n"
        f"   檢查方式： udevadm info /dev/input/{node} | grep ID_INPUT",
        file=sys.stderr,
    )
    return False


def runtime_path(name: str) -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, f"mousekey.{name}")


def write_state(on: bool) -> None:
    try:
        with open(runtime_path("state"), "w", encoding="utf-8") as fh:
            fh.write("on\n" if on else "off\n")
    except OSError:
        pass


def feedback(cfg: Config, on: bool) -> None:
    write_state(on)
    mode = cfg.feedback.lower()
    if mode not in ("notify", "beep", "both"):
        return
    if mode in ("notify", "both"):
        _run_quiet([
            "notify-send", "-a", "mousekey", "-t", "600",
            "-h", "string:x-canonical-private-synchronous:mousekey",
            "mousekey", "滑鼠鍵模式：開" if on else "滑鼠鍵模式：關",
        ])
    if mode in ("beep", "both"):
        _run_quiet(["canberra-gtk-play", "-i", "bell"])


def _run_quiet(argv: list[str]) -> None:
    try:
        subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


# --------------------------------------------------------------------------
# 主迴圈
# --------------------------------------------------------------------------

class DryRunSink:
    """--dry-run 用：把要送出的東西印出來。"""

    def __init__(self, tag: str, stream=sys.stdout):
        self.tag = tag
        self.stream = stream

    def emit(self, events) -> None:
        parts = []
        for etype, code, value in events:
            if etype == EV_SYN:
                continue
            if etype == EV_KEY:
                kind = "BTN" if code in BTN_RANGE else "KEY"
                state = {0: "up", 1: "down", 2: "repeat"}.get(value, str(value))
                parts.append(f"{kind} {key_name(code)} {state}")
            elif etype == EV_REL:
                axis = {REL_WHEEL: "wheel", REL_HWHEEL: "hwheel"}.get(code, f"rel{code}")
                parts.append(f"REL {axis} {value:+d}")
            else:
                parts.append(f"type{etype} {code} {value}")
        if parts:
            print(f"  {self.tag}  " + " | ".join(parts), file=self.stream, flush=True)


class ControlSocket:
    """讓外部用 `mousekey --send toggle` 控制。"""

    def __init__(self, path: str, on_command):
        self.path = path
        self.on_command = on_command
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o600)
        self.sock.listen(4)
        self.sock.setblocking(False)

    def accept_ready(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except BlockingIOError:
            return
        with conn:
            conn.settimeout(0.5)
            try:
                raw = conn.recv(256)
            except OSError:
                return
            cmd = raw.decode("utf-8", "replace").strip().lower()
            reply = self.on_command(cmd)
            try:
                conn.sendall((reply + "\n").encode())
            except OSError:
                pass

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


def run(cfg: Config, dry_run: bool = False, verbose: bool = False) -> int:
    sources, notes = select_devices(cfg)
    for note in notes:
        print(note, file=sys.stderr)

    if not sources:
        paths = glob.glob("/dev/input/event*")
        print(
            f"目前沒有可用的鍵盤裝置（掃到 {len(paths)} 個 /dev/input 節點）"
            " —— 會持續等待（Ctrl+C 結束）。",
            file=sys.stderr,
        )
        print(f"  身分：{process_identity()}", file=sys.stderr)
        if ENUM_ERRORS:
            shown = "、".join(f"{os.path.basename(p)}({e})" for p, e in ENUM_ERRORS[:3])
            print(
                f"  {len(ENUM_ERRORS)} 個節點打不開，例如：{shown}",
                file=sys.stderr,
            )
        for line in permission_diagnosis():
            print(f"  • {line}", file=sys.stderr)

    if verbose:
        for dev in sources:
            print(f"使用裝置：{dev.path}  {dev.name}", flush=True)

    kbd_out = mouse_out = None
    if not dry_run:
        # 直接宣告「所有」非滑鼠鍵，這樣之後熱插拔的新鍵盤也轉送得出去
        all_keys = {k for k in range(1, KEY_MAX + 1) if k not in BTN_RANGE}
        try:
            kbd_out = UinputDevice("mousekey virtual keyboard", keys=all_keys, rels=set())
            mouse_out = UinputDevice(
                "mousekey virtual mouse",
                keys=set(BTN_RANGE),
                # REL_X/REL_Y 一定要有！udev 的 input_id 要看到座標軸才會標成
                # ID_INPUT_MOUSE，否則 compositor 會把這個裝置當空氣。
                # 我們不會送任何移動事件，只是為了讓它被認成滑鼠。
                rels={REL_X, REL_Y, REL_WHEEL, REL_HWHEEL},
            )
        except OSError as exc:
            print(f"建立虛擬裝置失敗：{exc}", file=sys.stderr)
            return 2
        verify_uinput(kbd_out.name, "ID_INPUT_KEYBOARD")
        verify_uinput(mouse_out.name, "ID_INPUT_MOUSE")
    else:
        kbd_out = DryRunSink("鍵盤→")
        mouse_out = DryRunSink("滑鼠→")

    engine = Engine(cfg, on_toggle=lambda on: _toggle_side_effects(cfg, on, verbose))

    write_state(False)

    ctrl = None
    if cfg.control_socket:
        try:
            ctrl = ControlSocket(
                runtime_path("sock"),
                lambda cmd: _control_command(cmd, engine, mouse_out),
            )
        except OSError as exc:
            print(f"（控制 socket 建立失敗，忽略：{exc}）", file=sys.stderr)

    sel = selectors.DefaultSelector()
    if ctrl:
        sel.register(ctrl.sock, selectors.EVENT_READ, ctrl)

    live: dict[str, "InputDevice"] = {}
    # 已經判斷過「不是我們要的」的節點，避免每秒重開 50 個裝置
    evaluated: set[str] = set()

    def attach(dev: "InputDevice") -> bool:
        if cfg.grab and not dry_run:
            try:
                dev.grab(True)
            except OSError as exc:
                reason = "被其他程式獨佔" if exc.errno == errno.EBUSY else exc.strerror
                print(f"略過 {dev.path}（{dev.name}）：{reason}", file=sys.stderr)
                dev.close()
                return False
        sel.register(dev.fd, selectors.EVENT_READ, dev)
        live[dev.path] = dev
        print(f"接手：{dev.path}  {dev.name}", flush=True)
        return True

    def detach(dev: "InputDevice") -> None:
        live.pop(dev.path, None)
        try:
            sel.unregister(dev.fd)
        except (KeyError, ValueError, OSError):
            pass
        dev.close()
        print(f"裝置移除：{dev.path}  {dev.name}", file=sys.stderr, flush=True)

    def rescan() -> None:
        """裝置拔插後重新接手 —— 不重掃的話，拔掉滑鼠或鍵盤就再也不理它了。"""
        present = set(glob.glob("/dev/input/event*"))
        evaluated.intersection_update(present)   # 消失過的路徑要重新判斷
        for path in list(live):
            if path not in present:
                detach(live[path])
        for path in present - evaluated - set(live):
            try:
                dev = InputDevice.open(path)
            except OSError:
                evaluated.add(path)
                continue
            if dev.name.startswith("mousekey") or not device_matches(cfg, dev):
                dev.close()
                evaluated.add(path)
                continue
            # 被獨佔的裝置不標記，下一輪會再試（等其他程式放開）
            if attach(dev):
                evaluated.add(path)

    for dev in sources:
        attach(dev)
    evaluated |= set(glob.glob("/dev/input/event*")) - set(live)

    if not live and cfg.grab and not dry_run:
        print(
            "沒有任何裝置可以獨佔。若你正在用 input-remapper / keyd，"
            "請先停用它（兩個工具會互搶裝置）；否則會持續等待。",
            file=sys.stderr,
        )

    stop = {"flag": False}

    def _on_signal(signum, _frame):
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    if verbose:
        print("執行中…（Ctrl+Alt+Shift+Esc 或關閉終端結束）", flush=True)

    next_scan = time.monotonic() + 1.0
    warned_empty = bool(live)
    window = max(0, cfg.dedup_ms) / 1000.0
    last_seen: dict[tuple[int, int], tuple[str, float]] = {}

    try:
        while not stop["flag"] and not engine.quit:
            deadline = engine.next_deadline()
            timeout = 0.25
            if deadline is not None:
                timeout = max(0.0, min(0.25, deadline - time.monotonic()))
            for key, _mask in sel.select(timeout):
                target = key.data
                if isinstance(target, ControlSocket):
                    target.accept_ready()
                    continue
                dev = target
                try:
                    events = dev.read()
                except OSError:
                    detach(dev)
                    continue
                for evtype, code, value in events:
                    if window and evtype == EV_KEY and value in (0, 1):
                        key = (code, value)
                        prev = last_seen.get(key)
                        now_t = time.monotonic()
                        if prev and prev[0] != dev.path and now_t - prev[1] < window:
                            # 同一把鍵盤的另一條路徑，忽略這份重複
                            continue
                        last_seen[key] = (dev.path, now_t)
                    if TRACE and evtype == EV_KEY:
                        state = {0: "up", 1: "down", 2: "repeat"}.get(value, str(value))
                        print(f"  ← {dev.name}: {key_name(code)} {state}",
                              file=sys.stderr, flush=True)
                    _pump(engine, kbd_out, mouse_out, evtype, code, value)
                    if engine.quit:
                        break

            now = time.monotonic()
            repeats = engine.tick(now)
            if repeats:
                mouse_out.emit(repeats)

            if now >= next_scan:
                next_scan = now + 1.0
                rescan()
                if not live and warned_empty:
                    print("目前沒有任何鍵盤被接手，等待裝置重新出現…",
                          file=sys.stderr, flush=True)
                    warned_empty = False
                elif live:
                    warned_empty = True
    finally:
        try:
            sel.close()
        except Exception:
            pass
        _cleanup(list(live.values()), kbd_out, mouse_out, ctrl)

    print("已結束。", flush=True)
    return 0


def _pump(engine: Engine, kbd_out, mouse_out, evtype: int, code: int, value: int) -> None:
    kbd, mouse = engine.handle(evtype, code, value)
    if TRACE:
        if mouse:
            print(f"      滑鼠→ {_describe(mouse)}", file=sys.stderr, flush=True)
        if kbd:
            print(f"      鍵盤→ {_describe(kbd)}", file=sys.stderr, flush=True)
    if kbd and kbd_out is not None:
        # 滑鼠鍵（BTN_*）與相對移動要送給虛擬滑鼠，其餘送虛擬鍵盤
        to_mouse = [e for e in kbd if e[0] == EV_REL or (e[0] == EV_KEY and e[1] in BTN_RANGE)]
        to_kbd = [e for e in kbd if e not in to_mouse]
        if to_kbd:
            kbd_out.emit(_finalize(to_kbd))
        if to_mouse and mouse_out is not None:
            mouse_out.emit(_finalize(to_mouse))
    if mouse and mouse_out is not None:
        mouse_out.emit(_finalize(mouse))


def _toggle_side_effects(cfg: Config, on: bool, verbose: bool) -> None:
    feedback(cfg, on)
    if verbose:
        print(f"[{'ON ' if on else 'OFF'}] 滑鼠鍵模式", flush=True)


def _control_command(cmd: str, engine: Engine, mouse_out=None) -> str:
    """由控制 socket 呼叫。切換時可能要把按住的滑鼠鍵放開，所以要真的送出事件。"""
    mouse: list = []
    if cmd in ("on", "1", "enable"):
        engine.set_enabled(True, mouse)
    elif cmd in ("off", "0", "disable"):
        engine.set_enabled(False, mouse)
    elif cmd in ("toggle", "t"):
        engine.set_enabled(not engine.enabled, mouse)
    elif cmd in ("status", "state", ""):
        return "on" if engine.enabled else "off"
    elif cmd in ("quit", "exit"):
        engine.quit = True
        return "byebye"
    else:
        return f"unknown:{cmd}"

    if mouse and mouse_out is not None:
        mouse_out.emit(_finalize(mouse))
    return "on" if engine.enabled else "off"


def _cleanup(sources, kbd_out, mouse_out, ctrl) -> None:
    for dev in sources:
        try:
            dev.close()
        except Exception:
            pass
    for out in (mouse_out, kbd_out):
        if out is not None and hasattr(out, "destroy"):
            try:
                out.destroy()
            except Exception:
                pass
    if ctrl is not None:
        ctrl.close()


# --------------------------------------------------------------------------
# 命令列
# --------------------------------------------------------------------------

def send_command(cmd: str) -> int:
    path = runtime_path("sock")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(path)
        sock.sendall(cmd.encode())
        reply = sock.recv(256).decode("utf-8", "replace").strip()
        sock.close()
    except OSError as exc:
        print(f"連不上執行中的 mousekey（{path}）：{exc}", file=sys.stderr)
        return 1
    print(reply)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mousekey",
        description="用鍵盤按鍵取代滑鼠按鍵（Linux evdev/uinput，支援 Wayland）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  %(prog)s --keys                  列出所有可用的按鍵名稱
  %(prog)s --list-devices          列出輸入裝置，確認鍵盤路徑
  %(prog)s --probe                 按幾個鍵，看看事件是從哪個裝置進來
  %(prog)s --check                 檢查設定檔
  %(prog)s --dry-run --verbose     只印出會送出的動作，不真的送出
  %(prog)s                         正式執行（需先跑 setup-permissions.sh）
  %(prog)s --send toggle           切換執行中實例的開關
""",
    )
    parser.add_argument("-c", "--config", help="設定檔路徑（預設為程式旁邊的 config.toml）")
    parser.add_argument("--list-devices", action="store_true", help="列出 /dev/input 裝置")
    parser.add_argument("--keys", action="store_true", help="列出所有可用的按鍵名稱")
    parser.add_argument("--probe", nargs="?", type=float, const=10.0, metavar="秒數",
                        help="監聽幾秒（預設 10），回報按鍵來自哪個裝置")
    parser.add_argument("--check", action="store_true", help="檢查設定檔後結束")
    parser.add_argument("--dry-run", action="store_true", help="不獨佔、不建立虛擬裝置，只印動作")
    parser.add_argument("--send", metavar="CMD", help="對執行中的實例送指令：on/off/toggle/status/quit")
    parser.add_argument("-v", "--verbose", action="store_true", help="顯示更多訊息")
    parser.add_argument("--trace", action="store_true",
                        help="把收到的按鍵與送出的動作逐行印出來（除錯用）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    global TRACE
    TRACE = args.trace

    if args.list_devices:
        return cmd_list_devices()
    if args.keys:
        return cmd_list_keys()
    if args.probe is not None:
        return cmd_probe(args.probe)
    if args.send:
        return send_command(args.send)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"找不到設定檔：{args.config}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return 2
    except tomllib.TOMLDecodeError as exc:
        print(f"TOML 解析錯誤：{exc}", file=sys.stderr)
        return 2

    if args.check:
        print(cfg.describe())
        devs, _ = select_devices(cfg)
        if devs:
            print("偵測到的鍵盤：")
            for dev in devs:
                print(f"  {dev.path}  {dev.name}")
                dev.close()
        else:
            print("偵測到的鍵盤：（無，可能需要權限）")
        return 0

    if args.dry_run:
        print("※ dry-run：不會獨佔鍵盤，按鍵仍會送到目前視窗", file=sys.stderr)

    return run(cfg, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
