#!/usr/bin/env bash
# mousekey 的一次性權限設定（Linux）。
#
# 需要做兩件事：
#   1. 讓 /dev/uinput 存在且你的使用者可寫 → 才能建立虛擬滑鼠
#   2. 讓你的使用者能讀 /dev/input/event* → 才能讀鍵盤
#
# 這個腳本只會「新增」設定，不會刪除或覆蓋任何既有檔案。
# 在 Fedora Silverblue 上 /etc 是可寫的，所以這些設定會保留。

set -euo pipefail

BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'

say()  { printf "${BLUE}==>${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}  ok${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}  !${NC}  %s\n" "$*"; }
die()  { printf "${RED}  x${NC}  %s\n" "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "這個腳本只支援 Linux"
[ "$(id -u)" -ne 0 ] || die "請用一般使用者執行（腳本內部會自己呼叫 sudo）"

say "檢查 /dev/uinput"
if [ ! -e /dev/uinput ]; then
    warn "/dev/uinput 不存在，載入 uinput 模組"
    sudo modprobe uinput
fi
[ -e /dev/uinput ] || die "仍然找不到 /dev/uinput，請確認核心支援 CONFIG_INPUT_UINPUT"

say "設定開機自動載入 uinput"
if ! grep -qx 'uinput' /etc/modules-load.d/uinput.conf 2>/dev/null; then
    echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
    ok "已寫入 /etc/modules-load.d/uinput.conf"
else
    ok "已存在"
fi

say "設定 udev 規則（/dev/uinput 給 input 群組讀寫）"
RULE='/etc/udev/rules.d/60-uinput.rules'
if [ ! -e "$RULE" ]; then
    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
        | sudo tee "$RULE" >/dev/null
    ok "已寫入 $RULE"
else
    ok "已存在"
fi

sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput 2>/dev/null || true

say "把 $USER 加入 input 群組"
# 注意：這裡要查「群組資料庫」，不是查目前 shell 的群組。
# 目前 shell 的群組要重新登入才會更新，拿它判斷會永遠誤判成「還沒加入」。
# 直接讀 /etc/group（usermod 就是改這個檔），避免 NSS 快取造成誤判
in_db() {
    if grep -q '^input:' /etc/group 2>/dev/null; then
        grep '^input:' /etc/group | cut -d: -f4 | tr ',' '\n' | grep -qx "$USER"
    else
        getent group input 2>/dev/null | cut -d: -f4 | tr ',' '\n' | grep -qx "$USER"
    fi
}
in_now() { id -nG | tr ' ' '\n' | grep -qx input; }

if in_now; then
    ok "目前這個 shell 已經有 input 權限"
elif in_db; then
    ok "$USER 已經在 input 群組裡（只是這個 shell 還沒套用）"
else
    sudo usermod -aG input "$USER" || true
    sleep 0.2
    if ! in_db; then
        warn "usermod 沒有生效，改用 gpasswd 再試一次"
        sudo gpasswd -a "$USER" input || true
        sleep 0.2
    fi
    if in_db; then
        ok "已把 $USER 加入 input 群組"
    else
        warn "兩種方式都沒把 $USER 寫進 input 群組（下面會印出實際內容）"
    fi
fi

say "群組資料庫現在的樣子（除錯用）"
grep '^input:' /etc/group 2>/dev/null || echo "  /etc/group 裡沒有 input 這一行"
echo "  getent → $(getent group input 2>/dev/null || echo '(查不到)')"
echo "  目前 shell → $(id -nG)"

say "立即套用 /dev/uinput 權限（不等重新登入）"
sudo chgrp input /dev/uinput 2>/dev/null || true
sudo chmod 0660 /dev/uinput 2>/dev/null || true

say "驗證"
FAIL=0
if [ -e /dev/uinput ]; then ok "/dev/uinput 存在"; else warn "/dev/uinput 不存在"; FAIL=1; fi
if [ -w /dev/uinput ]; then ok "可以寫 /dev/uinput"; else warn "寫不了 /dev/uinput"; FAIL=1; fi
if [ -r /dev/input/event0 ]; then
    ok "可以讀 /dev/input/event0"
else
    warn "還讀不到 /dev/input/event0"
    FAIL=1
    if in_db && ! in_now; then
        echo "     → 群組已設定，只是這個 shell 還沒套用。不用登出，執行："
        echo "         newgrp input"
    elif ! in_db; then
        echo "     → /etc/group 裡沒有 $USER。手動執行："
        echo "         sudo gpasswd -a $USER input"
        echo "         grep '^input:' /etc/group      # 應該看到 input:x:NNN:$USER"
    fi
fi

echo
if [ "$FAIL" -eq 0 ]; then
    say "全部就緒，可以執行： ./mousekey.py --list-devices"
else
    say "下一步： newgrp input   （或登出 niri 再登入，這樣連自動啟動的程式也吃得到）"
fi
