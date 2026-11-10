#!/usr/bin/env bash
# mousekey 權限診斷：把所有會影響結果的東西一次印出來。
# 用法： bash diagnose.sh
# 不需要 root，也不會改任何設定。

set -u

hr() { printf '\n== %s ==\n' "$1"; }

hr "身分"
id
echo "SHELL 中的群組 → $(id -nG)"

hr "/etc/group 裡的 input（usermod 實際修改的檔案）"
if grep -E '^input:' /etc/group 2>/dev/null; then :; else
    echo "(沒有 input 這一行)"
fi

hr "getent group input（會經過 NSS，可能與上面不同）"
getent group input || echo "(查不到)"

hr "nsswitch 設定"
grep -E '^(passwd|group|shadow):' /etc/nsswitch.conf 2>/dev/null || echo "(讀不到)"

hr "/dev/uinput"
ls -l /dev/uinput 2>&1 || true

hr "/dev/input 前幾個裝置"
ls -l /dev/input/event0 /dev/input/event3 2>&1 || true

hr "ACL（如果有裝 setfacl）"
if command -v getfacl >/dev/null; then
    getfacl /dev/input/event3 2>&1 | sed 's/^/  /' || true
    getfacl /dev/uinput 2>&1 | sed 's/^/  /' || true
else
    echo "(沒有 getfacl)"
fi

hr "實際能不能讀 / 寫"
if head -c0 /dev/input/event3 2>/dev/null; then echo "  ✓ 可以讀 /dev/input/event3"; else
    echo "  ✗ 不能讀 /dev/input/event3"; fi
if [ -w /dev/uinput ]; then echo "  ✓ 可以寫 /dev/uinput"; else
    echo "  ✗ 不能寫 /dev/uinput"; fi

hr "udev 規則"
for f in /etc/udev/rules.d/60-uinput.rules /etc/udev/rules.d/61-mousekey*.rules; do
    [ -e "$f" ] && { echo "--- $f"; cat "$f"; }
done
[ -e /etc/udev/rules.d/60-uinput.rules ] || echo "(沒有 60-uinput.rules)"

hr "服務狀態"
systemctl --user is-active mousekey 2>&1 || true

hr "結論"
printf '  * 若 /etc/group 有 stan、但 id -nG 沒有 input → 重新登入（或 newgrp input）\n'
printf '  * 若 /etc/group 沒有 stan → sudo gpasswd -a %s input\n' "$(id -un)"
printf '  * 若兩邊都沒有 input 這一行 → sudo groupadd -r input 再 gpasswd -a\n'
