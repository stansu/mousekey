#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整合測試：用假的裝置跑完整的 run() 迴圈，驗證事件流與控制 socket。"""

import errno
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mousekey as mk  # noqa: E402

K = mk.KEY_CODES
CAPS = K["CAPSLOCK"]


class FakeDevice:
    _seq = 0

    def __init__(self):
        FakeDevice._seq += 1
        self.path = f"/dev/input/fake{FakeDevice._seq}"
        self.r, self.w = os.pipe()
        os.set_blocking(self.r, False)
        self.fd = self.r
        self.name = "Fake Keyboard"
        self.grabbed = False
        self.busy = False
        self.keys = {K["A"], K["Z"], K["SPACE"], K["ENTER"], K["LEFTSHIFT"], CAPS, K["F"]}
        self.rels = set()

    def grab(self, enable=True):
        if enable and self.busy:
            raise OSError(errno.EBUSY, "Device or resource busy")
        self.grabbed = enable

    def read(self):
        try:
            data = os.read(self.r, 4096)
        except BlockingIOError:
            return []
        out = []
        for off in range(0, len(data) - mk._EVENT.size + 1, mk._EVENT.size):
            _, _, t, c, v = mk._EVENT.unpack_from(data, off)
            out.append((t, c, v))
        return out

    def close(self):
        self.grabbed = False  # 關閉 fd 時核心會自動解除獨佔
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass
        self.fd = None

    def send(self, etype, code, value):
        os.write(self.w, mk._EVENT.pack(0, 0, etype, code, value))
        time.sleep(0.02)

    def key(self, name, value):
        self.send(mk.EV_KEY, K[name], value)
        self.send(mk.EV_SYN, 0, 0)


class FakeUinput:
    instances = []

    def __init__(self, name, keys=(), rels=(), ev_types=None):
        self.name = name
        self.events = []
        FakeUinput.instances.append(self)

    def emit(self, events):
        self.events.extend(events)

    def destroy(self):
        pass

    def keys_sent(self):
        return [e for e in self.events if e[0] == mk.EV_KEY and e[1] < 0x100]

    def buttons_sent(self):
        return [e for e in self.events if e[0] == mk.EV_KEY and e[1] >= 0x100]


class TestRunLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        FakeUinput.instances = []
        self.dev = FakeDevice()
        self._orig = (mk.select_devices, mk.UinputDevice)
        mk.select_devices = lambda cfg: ([self.dev], [])
        mk.UinputDevice = FakeUinput
        cfg = {
            "general": {"toggle_key": "CAPSLOCK", "feedback": "none", "control_socket": True},
            "keys": {"F": "left"},
        }
        self.cfg = mk.Config(cfg, "<test>")
        self.result = []
        self.thread = threading.Thread(
            target=lambda: self.result.append(mk.run(self.cfg)), daemon=True
        )
        self.thread.start()
        self.wait_socket()

    def tearDown(self):
        self.thread.join(timeout=3)
        mk.select_devices, mk.UinputDevice = self._orig
        self.tmp.cleanup()

    def wait_socket(self):
        path = mk.runtime_path("sock")
        for _ in range(300):
            if os.path.exists(path):
                return
            time.sleep(0.01)
        self.fail("控制 socket 沒出現")

    def send(self, cmd):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(mk.runtime_path("sock"))
        sock.sendall(cmd.encode())
        reply = sock.recv(256).decode().strip()
        sock.close()
        return reply

    def test_full_flow(self):
        self.assertEqual(self.send("status"), "off")

        self.dev.key("F", 1)  # 關閉時：應該原樣送給鍵盤
        self.dev.key("F", 0)
        self.assertEqual(
            FakeUinput.instances[0].keys_sent(),
            [(mk.EV_KEY, K["F"], 1), (mk.EV_KEY, K["F"], 0)],
        )

        self.assertEqual(self.send("toggle"), "on")

        self.dev.key("F", 1)  # 開啟時：應該變成左鍵按下
        self.dev.key("F", 0)
        time.sleep(0.1)

        kbd, mouse = FakeUinput.instances[0], FakeUinput.instances[1]
        self.assertIn((mk.EV_KEY, mk.BTN_LEFT, 1), mouse.buttons_sent())
        self.assertIn((mk.EV_KEY, mk.BTN_LEFT, 0), mouse.buttons_sent())
        self.assertNotIn((mk.EV_KEY, K["F"], 1), kbd.keys_sent()[1:])

        self.assertEqual(self.send("quit"), "byebye")
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.result, [0])

    def test_disabled_forwards_everything(self):
        self.dev.key("F", 1)
        self.dev.key("F", 0)
        time.sleep(0.1)
        kbd = FakeUinput.instances[0]
        self.assertEqual(
            kbd.keys_sent(), [(mk.EV_KEY, K["F"], 1), (mk.EV_KEY, K["F"], 0)]
        )
        self.send("quit")
        self.thread.join(timeout=3)

    def test_grab_and_release(self):
        self.assertTrue(self.dev.grabbed)
        self.send("quit")
        self.thread.join(timeout=3)
        self.assertFalse(self.dev.grabbed)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSkipBusy(unittest.TestCase):
    """一個裝置被別的程式獨佔時，應該跳過它、繼續用其他裝置，而不是整個結束。"""

    def test_busy_device_is_skipped(self):
        tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_RUNTIME_DIR"] = tmp.name
        FakeUinput.instances = []
        good, busy = FakeDevice(), FakeDevice()
        busy.busy = True
        orig = (mk.select_devices, mk.UinputDevice)
        mk.select_devices = lambda cfg: ([busy, good], [])
        mk.UinputDevice = FakeUinput
        cfg = mk.Config(
            {"general": {"feedback": "none"}, "keys": {"F": "left"}}, "<test>"
        )
        result = []
        thread = threading.Thread(target=lambda: result.append(mk.run(cfg)), daemon=True)
        try:
            thread.start()
            path = mk.runtime_path("sock")
            for _ in range(300):
                if os.path.exists(path):
                    break
                time.sleep(0.01)
            # socket 是在「獨佔完成後」才建立的，所以這時候狀態已定
            self.assertTrue(good.grabbed)
            self.assertFalse(busy.grabbed)
            busy_check = True
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(path)
            sock.sendall(b"quit")
            sock.recv(64)
            sock.close()
            thread.join(timeout=3)
        finally:
            mk.select_devices, mk.UinputDevice = orig
            tmp.cleanup()
        self.assertEqual(result, [0])
        self.assertTrue(busy_check)


class TestHotplug(unittest.TestCase):
    """拔掉再插回來要能自動接手（原本只掃一次，拔掉就再也不理它了）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        FakeUinput.instances = []
        self.present = set()
        self.made = {}
        self._orig = (mk.select_devices, mk.UinputDevice, mk.InputDevice, mk.glob.glob, mk.ConfigError)

        def fake_open(path):
            if path not in self.present:
                raise FileNotFoundError(path)
            dev = self.made.get(path)
            if dev is None or dev.fd is None:
                dev = FakeDevice()
                dev.path = path
                dev.name = "Fake Keyboard"
                self.made[path] = dev
            return dev

        class FakeInput:
            open = staticmethod(fake_open)

        mk.select_devices = lambda cfg: ([], [])
        mk.UinputDevice = FakeUinput
        mk.InputDevice = FakeInput
        mk.glob.glob = lambda pattern: list(self.present)

        self.cfg = mk.Config(
            {
                "general": {"feedback": "none", "control_socket": True},
                "device": {"match": ["Fake Keyboard"]},
                "keys": {"F": "left"},
            },
            "<test>",
        )
        self.thread = threading.Thread(target=lambda: mk.run(self.cfg), daemon=True)
        self.thread.start()
        for _ in range(300):
            if os.path.exists(mk.runtime_path("sock")):
                break
            time.sleep(0.01)

    def tearDown(self):
        mk.select_devices, mk.UinputDevice, mk.InputDevice, mk.glob.glob, mk.ConfigError = self._orig
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def wait_for(self, predicate, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_unplug_and_replug(self):
        self.present.add("/dev/input/fake1")
        self.assertTrue(self.wait_for(lambda: self.made.get("/dev/input/fake1") is not None
                                      and self.made["/dev/input/fake1"].grabbed))
        first = self.made["/dev/input/fake1"]

        self.present.clear()                       # 拔掉
        self.assertTrue(self.wait_for(lambda: not first.grabbed))

        self.present.add("/dev/input/fake1")       # 插回來
        self.assertTrue(self.wait_for(lambda: self.made["/dev/input/fake1"].grabbed))
