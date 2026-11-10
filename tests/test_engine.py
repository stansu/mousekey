#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Engine 的單元測試（不需要真的鍵盤或 /dev/uinput）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mousekey as mk  # noqa: E402

K = mk.KEY_CODES
CAPS = K["CAPSLOCK"]


def make_cfg(keys=None, **general):
    general.setdefault("feedback", "none")
    raw = {
        "general": general,
        "keys": keys if keys is not None else {"F": "left", "D": "right", "R": "wheel_up", "A": "double"},
    }
    return mk.Config(raw, "<test>")


def press(engine, name):
    return engine.handle(mk.EV_KEY, K[name] if isinstance(name, str) else name, 1)


def release(engine, name):
    return engine.handle(mk.EV_KEY, K[name] if isinstance(name, str) else name, 0)


def kinds(mouse):
    """把事件串簡化成 [(type, code, value), ...]，去掉 SYN。"""
    return [e for e in mouse if e[0] != mk.EV_SYN]


class TestPassthrough(unittest.TestCase):
    def test_disabled_forwards_keys(self):
        e = mk.Engine(make_cfg())
        kbd, mouse = press(e, "F")
        self.assertEqual(kbd, [(mk.EV_KEY, K["F"], 1)])
        self.assertEqual(mouse, [])

    def test_repeat_is_always_dropped(self):
        e = mk.Engine(make_cfg())
        kbd, _ = e.handle(mk.EV_KEY, K["F"], 2)
        self.assertEqual(kbd, [])

    def test_modifiers_forwarded(self):
        e = mk.Engine(make_cfg())
        kbd, _ = press(e, "LEFTCTRL")
        self.assertEqual(kbd, [(mk.EV_KEY, K["LEFTCTRL"], 1)])


class TestToggle(unittest.TestCase):
    def test_toggle_key_is_swallowed(self):
        e = mk.Engine(make_cfg())
        kbd, mouse = press(e, "CAPSLOCK")
        self.assertEqual(kbd, [])
        self.assertEqual(mouse, [])
        self.assertTrue(e.enabled)
        kbd, _ = release(e, "CAPSLOCK")
        self.assertEqual(kbd, [])

    def test_toggle_callback(self):
        seen = []
        e = mk.Engine(make_cfg(), on_toggle=seen.append)
        for _ in range(2):                       # 輕按兩次 = 開、關
            press(e, "CAPSLOCK")
            release(e, "CAPSLOCK")
        self.assertEqual(seen, [True, False])


class TestButtons(unittest.TestCase):
    def setUp(self):
        self.e = mk.Engine(make_cfg())
        press(self.e, "CAPSLOCK")

    def test_click_presses_and_releases(self):
        kbd, mouse = press(self.e, "F")
        self.assertEqual(kbd, [])
        self.assertEqual(kinds(mouse), [(mk.EV_KEY, mk.BTN_LEFT, 1)])
        kbd, mouse = release(self.e, "F")
        self.assertEqual(kbd, [])
        self.assertEqual(kinds(mouse), [(mk.EV_KEY, mk.BTN_LEFT, 0)])

    def test_hold_is_drag(self):
        press(self.e, "F")
        # 按住期間一直沒有 up，這就是拖曳
        kbd, mouse = self.e.handle(mk.EV_KEY, K["F"], 2)
        self.assertEqual(mouse, [])
        release(self.e, "F")

    def test_right_and_middle(self):
        _, mouse = press(self.e, "D")
        self.assertEqual(kinds(mouse), [(mk.EV_KEY, mk.BTN_RIGHT, 1)])
        release(self.e, "D")
        e2 = mk.Engine(make_cfg(keys={"S": "middle"}))
        press(e2, "CAPSLOCK")
        _, mouse = press(e2, "S")
        self.assertEqual(kinds(mouse), [(mk.EV_KEY, mk.BTN_MIDDLE, 1)])

    def test_double_click(self):
        _, mouse = press(self.e, "A")
        self.assertEqual(
            kinds(mouse),
            [
                (mk.EV_KEY, mk.BTN_LEFT, 1),
                (mk.EV_KEY, mk.BTN_LEFT, 0),
            ],
        )
        _, mouse = release(self.e, "A")
        self.assertEqual(len(kinds(mouse)), 2)

    def test_orphan_release_is_ignored(self):
        # 先按著 F 再開啟，放開時不應該送出孤兒的 up
        e = mk.Engine(make_cfg())
        press(e, "F")
        press(e, "CAPSLOCK")
        kbd, mouse = release(e, "F")
        self.assertEqual(kinds(mouse), [])
        self.assertEqual(kbd, [(mk.EV_KEY, K["F"], 0)])

    def test_disable_releases_held_button(self):
        # 先輕按鎖定，再按住左鍵，最後再輕按關閉 → 左鍵要自動放開
        press(self.e, "CAPSLOCK")
        release(self.e, "CAPSLOCK")
        press(self.e, "F")
        _, m1 = press(self.e, "CAPSLOCK")
        _, m2 = release(self.e, "CAPSLOCK")
        self.assertEqual(kinds(m1 + m2), [(mk.EV_KEY, mk.BTN_LEFT, 0)])

    def test_unmapped_key_still_works_while_enabled(self):
        kbd, _ = press(self.e, "G")
        self.assertEqual(kbd, [(mk.EV_KEY, K["G"], 1)])


class TestWheel(unittest.TestCase):
    def test_wheel_emits_and_repeats(self):
        e = mk.Engine(make_cfg(wheel_first_ms=10, wheel_repeat_ms=5))
        press(e, "CAPSLOCK")
        _, mouse = press(e, "R")
        self.assertEqual(kinds(mouse), [(mk.EV_REL, mk.REL_WHEEL, 1)])

        import time as _t
        self.assertEqual(e.tick(_t.monotonic()), [])  # 還沒到
        later = _t.monotonic() + 1.0
        self.assertTrue(kinds(e.tick(later)))

        release(e, "R")
        self.assertEqual(e.tick(later + 10), [])  # 放開後不再重複


class TestPanic(unittest.TestCase):
    def test_panic_combo_quits(self):
        e = mk.Engine(make_cfg())
        press(e, "LEFTSHIFT")
        press(e, "LEFTCTRL")
        press(e, "LEFTALT")
        self.assertFalse(e.quit)
        press(e, "ESC")
        self.assertTrue(e.quit)

    def test_esc_alone_does_not_quit(self):
        e = mk.Engine(make_cfg())
        press(e, "ESC")
        self.assertFalse(e.quit)
        self.assertEqual(e.handle(mk.EV_KEY, K["ESC"], 0)[0], [(mk.EV_KEY, K["ESC"], 0)])


class TestConfig(unittest.TestCase):
    def test_key_name_variants(self):
        for name in ("F", "f", "KEY_F", "key_f", 33, "33", "0x21"):
            self.assertEqual(mk.key_code(name), K["F"], name)

    def test_bad_key_name(self):
        with self.assertRaises(mk.ConfigError):
            mk.key_code("NOTAKEY")

    def test_bad_action(self):
        with self.assertRaises(mk.ConfigError):
            make_cfg(keys={"F": "explode"})

    def test_toggle_conflicts_with_mapping(self):
        with self.assertRaises(mk.ConfigError):
            make_cfg(keys={"CAPSLOCK": "left"})

    def test_describe(self):
        text = make_cfg().describe()
        self.assertIn("CAPSLOCK", text)
        self.assertIn("left", text)


class TestFinalize(unittest.TestCase):
    def test_appends_syn(self):
        self.assertEqual(mk._finalize([(mk.EV_KEY, 1, 1)]), [(mk.EV_KEY, 1, 1), (mk.EV_SYN, 0, 0)])
        self.assertEqual(mk._finalize([(mk.EV_SYN, 0, 0)]), [(mk.EV_SYN, 0, 0)])
        self.assertEqual(mk._finalize([]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class _FakeDev:
    """只給 select_devices 用的假裝置。"""

    def __init__(self, path, name, phys, keyboard=True, btns=frozenset()):
        self.path = path
        self.name = name
        self.phys = phys
        self.keys = (
            {K["A"], K["Z"], K["SPACE"], K["ENTER"], K["LEFTSHIFT"]} | set(btns)
            if keyboard
            else {K["A"]}
        )
        self.closed = False

    @property
    def is_virtual(self):
        return not self.phys

    @property
    def looks_like_keyboard(self):
        need = {K["A"], K["Z"], K["SPACE"], K["ENTER"]}
        shift = {K["LEFTSHIFT"], K["RIGHTSHIFT"]}
        return need <= self.keys and bool(self.keys & shift)

    def close(self):
        self.closed = True


class TestDeviceSelection(unittest.TestCase):
    def setUp(self):
        self._orig = mk.enumerate_devices

    def tearDown(self):
        mk.enumerate_devices = self._orig

    def test_virtual_devices_are_skipped(self):
        real = _FakeDev("/dev/input/event3", "AT Keyboard", "isa0060/serio0/input0")
        virt = _FakeDev("/dev/input/event25", "input-remapper keyboard", "")
        mouse = _FakeDev("/dev/input/event5", "Mouse", "usb-1/input0", keyboard=False)
        mk.enumerate_devices = lambda: [real, virt, mouse]

        picked, notes = mk.select_devices(make_cfg())
        self.assertEqual([d.path for d in picked], ["/dev/input/event3"])
        self.assertTrue(virt.closed)
        self.assertTrue(mouse.closed)
        self.assertTrue(any("虛擬" in n for n in notes))

    def test_explicit_match_overrides_filter(self):
        virt = _FakeDev("/dev/input/event25", "input-remapper keyboard", "")
        mk.enumerate_devices = lambda: [virt]
        cfg = make_cfg()
        cfg.match = ["/dev/input/event25"]
        picked, _ = mk.select_devices(cfg)
        self.assertEqual(len(picked), 1)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestTapHold(unittest.TestCase):
    """輕按 = 鎖定切換；按住 = 暫時生效，放開就回原狀。"""

    def setUp(self):
        self.clock = FakeClock()
        self._orig = mk.time.monotonic
        mk.time.monotonic = self.clock
        self.e = mk.Engine(make_cfg(tap_hold=True, tap_ms=250))

    def tearDown(self):
        mk.time.monotonic = self._orig

    def tap(self, hold=0.05):
        press(self.e, "CAPSLOCK")
        self.clock.t += hold
        return release(self.e, "CAPSLOCK")

    def test_tap_locks_on(self):
        press(self.e, "CAPSLOCK")
        self.assertTrue(self.e.enabled)      # 按下立刻生效
        self.clock.t += 0.1
        release(self.e, "CAPSLOCK")
        self.assertTrue(self.e.enabled)      # 輕按 → 鎖定

    def test_hold_is_momentary(self):
        press(self.e, "CAPSLOCK")
        self.assertTrue(self.e.enabled)
        self.clock.t += 0.5
        release(self.e, "CAPSLOCK")
        self.assertFalse(self.e.enabled)     # 長按 → 放開就回原狀

    def test_tap_twice_turns_off(self):
        self.tap()
        self.assertTrue(self.e.enabled)
        self.clock.t += 0.1
        self.tap()
        self.assertFalse(self.e.enabled)

    def test_hold_while_locked_stays_locked(self):
        self.tap()
        self.clock.t += 0.1
        self.tap(hold=1.0)
        self.assertTrue(self.e.enabled)

    def test_disabled_tap_hold_keeps_old_behavior(self):
        e = mk.Engine(make_cfg(tap_hold=False))
        press(e, "CAPSLOCK")
        self.assertTrue(e.enabled)
        self.clock.t += 1.0
        release(e, "CAPSLOCK")
        self.assertTrue(e.enabled)           # 關掉 tap-hold 就是單純切換
