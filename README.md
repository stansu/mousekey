# mousekey

用鍵盤按鍵取代滑鼠按鍵 —— 給「滑鼠手」用的 Linux 小工具。

* 一個檔案、零依賴（Python 3.11+ 標準庫），複製就能跑
* 支援 **Wayland**（含 niri / sway / GNOME / KDE）與 **X11**
* 按一下 = 點擊，按住 = 拖曳，長按 = 連續滾輪
* `CapsLock` 一鍵切換，也可從外部指令或 niri 快捷鍵切換

```
CapsLock 按住/切換  →  進入滑鼠鍵模式
  F  → 左鍵      D  → 右鍵      S  → 中鍵
  A  → 雙擊      R  → 滾輪上    V  → 滾輪下
  其他按鍵照常打字
```

---

## 快速開始

### 1. 一次性權限設定

```bash
cd mouse_key
./setup-permissions.sh
```

它會做三件事（都不會覆蓋既有檔案）：

| 動作 | 為什麼 |
|---|---|
| 載入 `uinput` 模組並設為開機載入 | 才能建立虛擬滑鼠 |
| 加一條 udev 規則讓 `input` 群組可讀寫 `/dev/uinput` | 不用每次 `sudo` |
| 把你加入 `input` 群組 | 才能讀 `/dev/input/event*` |

> 完成後**登出再登入**（群組才生效）。

### 2. 確認看得到鍵盤

```bash
./mousekey.py --list-devices
```

應該看到你的鍵盤被標成「是」。

### 3. 執行

```bash
./mousekey.py            # 前景執行，Ctrl+Alt+Shift+Esc 結束
```

按 `CapsLock` 會在「一般模式」和「滑鼠鍵模式」之間切換，切換時右上角會有通知。

---

## 安裝到 PATH（建議）

放在專案資料夾裡每次都要 `cd`，裝成指令會順手很多：

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/mousekey.py" ~/.local/bin/mousekey
mousekey --version
```

之後在任何目錄都能直接用：

```bash
mousekey                  # 前景執行
mousekey --send toggle    # 切換執行中的那個
mousekey --send status    # 看目前是 on 還是 off
mousekey --probe          # 不確定哪個是鍵盤時
```

> 用 symlink 也找得到設定檔：程式會解析到真正的檔案位置，
> 所以 `config.toml` 留在原地就好。
> 想改成全域設定可以放 `~/.config/mousekey/config.toml`。

---

## 開機自動啟動

裝好 PATH 之後，一行就能搞定：

```bash
mkdir -p ~/.config/systemd/user
cp mousekey.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mousekey.service

systemctl --user status mousekey      # 看狀態
journalctl --user -u mousekey -f      # 看日誌
systemctl --user restart mousekey     # 改完設定後重啟
```

`mousekey` 是純 evdev/uinput，不需要圖形環境，所以跟著使用者管理員啟動（`default.target`），
不用等 `graphical-session.target`；當掉也會自動重啟。

**niri 使用者的替代方案**（不想用 systemd 的話），在 `~/.config/niri/config.kdl`：

```kdl
spawn-at-startup "mousekey"
```

差別是 niri 不會幫你重啟。

---

## 日常使用

設定好之後，平常只需要記住一件事：**按 `CapsLock` 切換**。

```
CapsLock          → 進入滑鼠鍵模式（右上角通知）
F / D / S         → 左鍵 / 右鍵 / 中鍵
F 按住不放        → 拖曳
A                 → 雙擊
R / V             → 滾輪上下
CapsLock          → 回到打字模式
Ctrl+Alt+Shift+Esc → 強制結束
```

搭配 niri 快捷鍵（可選，`config.kdl`）：

```kdl
Mod+Shift+M { spawn "mousekey" "--send" "toggle"; }
```

狀態列（waybar）：

```jsonc
"custom/mousekey": {
  "exec": "cat ${XDG_RUNTIME_DIR}/mousekey.state",
  "interval": 1,
  "format": "🖱 {}",
  "on-click": "mousekey --send toggle"
}
```

---

## 選對鍵盤（多個裝置 / 裝過 input-remapper 時）

現代筆電常常一次冒出 5～10 個「像鍵盤」的裝置。預設會抓所有**實體**鍵盤，
但如果你發現**打字變成雙字**（一個 `a` 出現兩次），代表同一把鍵盤有兩條事件路徑都被抓了。

用 `--probe` 讓它告訴你真相：

```bash
./mousekey.py --probe
```

```
請在接下來 10 秒內，按幾下你平常用來打字的鍵（例如 A、空白鍵）。

  /dev/input/event13    3 次   ASUE1403:00 04F3:319A Keyboard
                       按過：A、A、A

最可能是這個： /dev/input/event13  (ASUE1403:00 04F3:319A Keyboard)
把它寫進 config.toml 就只會抓這一個：

  [device]
  match = ["/dev/input/event13"]
```

`--list-devices` 也會標出三種容易搞混的裝置：

```
/dev/input/event25     是    虛擬   511    被佔用   input-remapper keyboard + mouse
/dev/input/event13     是    實體   146    可用     ASUE1403:00 04F3:319A Keyboard
```

| 標記 | 意思 |
|---|---|
| **虛擬** | 其他程式（input-remapper / keyd）用 uinput 造出來的，**一定會被略過**，搶過來會互打架 |
| **被佔用** | 已經被別的程式獨佔了，會被略過並警告 |
| **實體** | 真正的硬體，才會被接管 |

> 如果你已經在用 **input-remapper**，它其實就能把按鍵改成滑鼠鍵。
> 兩個工具同時跑會互搶裝置（`Device or resource busy`），只能選一個。

---

## 用法細節

| 操作 | 結果 |
|---|---|
| `F` 輕按 | 左鍵點一下 |
| `F` 按住不放 | 左鍵按住 → 移動滑鼠就是**拖曳** |
| `A` 按一下 | 雙擊（按下送第一次、放開送第二次） |
| `R` 按住 | 滾輪上，先等 320ms 再每 70ms 滾一格 |
| 模式中按 `G` | 照常打出 `g`（沒被對應的鍵不受影響） |
| `Ctrl+Alt+Shift+Esc` | 立刻結束程式 |

**切換方式有三種**，選你順手的：

```bash
# 1. CapsLock 鍵（預設）
# 2. 從任何地方送指令
./mousekey.py --send toggle
./mousekey.py --send on
./mousekey.py --send off
./mousekey.py --send status      # 印出 on / off
./mousekey.py --send quit

# 3. niri 快捷鍵：在 config.kdl 加入
Mod+Shift+M { spawn "sh" "-c" "python3 ~/Documents/deepseek-harness/mouse_key/mousekey.py --send toggle"; }
```

狀態也會寫在 `$XDG_RUNTIME_DIR/mousekey.state`（內容是 `on` 或 `off`），
可以直接拿來做 waybar 模組：

```jsonc
"custom/mousekey": {
  "exec": "cat ${XDG_RUNTIME_DIR}/mousekey.state",
  "interval": 1,
  "format": "🖱 {}",
  "on-click": "mousekey --send toggle"
}
```

---

## 自訂按鍵對應

`[keys]` 就是完整的映射表 —— 程式裡**沒有寫死任何按鍵**，全部由設定檔決定。格式是 `按鍵 = 動作`。

| 動作 | 意義 |
|---|---|
| `left` / `right` / `middle` | 左鍵 / 右鍵 / 中鍵 |
| `side` / `extra` | 滑鼠側鍵（瀏覽器上一頁 / 下一頁） |
| `double` | 雙擊（按下送第一次、放開送第二次） |
| `wheel_up` / `wheel_down` / `wheel_left` / `wheel_right` | 滾輪上下 / 左右 |

按鍵名稱四種寫法都通：

```toml
J = "left"        # 直接寫
KEY_J = "left"    # 加前綴
j = "left"        # 小寫也行
36 = "left"       # 直接寫 keycode（36 = J），0x24 也可以
```

不確定名字？查一下：

```bash
./mousekey.py --keys | grep -i kp     # 數字鍵盤
./mousekey.py --keys | grep -i shift  # 修飾鍵
```

**範例 A：左手放 home row，右手留著握滑鼠**

```toml
[general]
toggle_key = "CAPSLOCK"

[keys]
J = "left"
K = "right"
L = "double"
U = "wheel_up"
I = "wheel_down"
SEMICOLON = "middle"
```

**範例 B：只把數字鍵盤變成滑鼠（一般打字完全不受影響）**

```toml
[general]
toggle_key = "SCROLLLOCK"

[keys]
KP7 = "left"
KP9 = "right"
KP8 = "middle"
KP4 = "wheel_up"
KP6 = "wheel_down"
```

**範例 C：用平常沒在用的 F13–F24**

```toml
[keys]
F13 = "side"      # 有些鍵盤的 F13-F24 實體上不存在，但鍵盤仍可送出
F14 = "extra"
F15 = "middle"
```

規則：

- 同一個**動作**可以給很多個鍵（`F = "left"` 和 `J = "left"` 同時寫沒問題）
- 同一個**鍵**只能對一個動作
- `toggle_key` 不能同時出現在 `[keys]` 裡
- 改完要重啟程式（目前沒有熱重載）；用 `./mousekey.py --check` 確認解析結果

上面三個範例都是可以直接用的檔案，放在 `examples/`：

```bash
./mousekey.py --check --config examples/home-row.toml     # 先看解析結果
./mousekey.py --config examples/home-row.toml             # 用這組跑
```

---

## 設定檔

預設讀程式旁邊的 `config.toml`，也可以用 `--config` 指定。
沒有 `config.toml` 也能跑（使用內建預設）；想改就複製一份 `config.example.toml`：

```bash
cp config.example.toml config.toml
```

```toml
[general]
toggle_key = "CAPSLOCK"     # 切換鍵（永遠被吞掉，不會變成 Caps Lock）
grab = true                 # 獨佔鍵盤；false 只適合除錯
feedback = "notify"         # none / notify / beep / both
wheel_first_ms = 320        # 滾輪第一次觸發前的延遲
wheel_repeat_ms = 70        # 之後的間隔
control_socket = true       # 允許 --send 指令

[device]
match = []                  # 空 = 所有鍵盤；也可寫 ["AT Translated"] 或 ["/dev/input/event4"]

[keys]
F = "left"
D = "right"
S = "middle"
A = "double"
R = "wheel_up"
V = "wheel_down"
```

* **動作**：`left` `right` `middle` `side` `extra` `double`
  `wheel_up` `wheel_down` `wheel_left` `wheel_right`
* **按鍵名稱**：用 kernel 的 `KEY_` 名稱，`KEY_` 前綴可省略、大小寫皆可，
  也可以直接寫數字（`58` / `0x3a`）。完整對照表在程式裡的 `KEY_CODES`。

改完設定要**重啟**程式（目前沒有熱重載）。

---

## 原理（為什麼一定要這樣做）

Wayland 下**沒有任何**「全域鍵盤 hook」API —— 這是安全設計，不是 bug。
所以任何在 Wayland 上做按鍵改寫的工具（kanata、keyd、input-remapper）都走同一條路：

```
實體鍵盤 ──evdev──► mousekey ──┬──► 虛擬鍵盤（uinput）──► compositor → 應用程式
                               └──► 虛擬滑鼠（uinput）──► compositor → 應用程式
```

1. 讀 `/dev/input/event*`，直接從核心拿事件（繞過 compositor）
2. `EVIOCGRAB` 獨佔該鍵盤，否則按鍵會「漏」到視窗裡
3. 想保留的按鍵原樣轉送到自建的虛擬鍵盤
4. 想取代的按鍵改成送滑鼠事件到自建的虛擬滑鼠

好處是**完全不需要 X11、圖形庫或 compositor 支援任何協議**，X11、Wayland、純 TTY 都能用。

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 需要一次性權限設定 | 這是 Linux 的唯一代價；設定完就是一個檔案 |
| `CapsLock` 被吃掉 | 因為它是切換鍵；想改就用 `toggle_key` |
| 鍵盤 LED 不會同步 | 虛擬鍵盤沒有回寫 LED；NumLock/CapsLock 指示燈不會亮 |
| 遊戲 / 反作弊 | 有些遊戲會被虛擬裝置搞混，或偵測到而封鎖 |
| 全系統生效 | 沒有「只在某個視窗生效」的功能（Wayland 拿不到前景視窗以外的資訊） |
| 中文輸入 | 不影響；被對應的鍵才會被攔，其他照常 |

**如果程式卡住、鍵盤沒反應**：切到其他 TTY（`Ctrl+Alt+F3`）執行 `pkill -f mousekey.py`，
或直接拔插鍵盤 / 登出。正常結束（`Ctrl+C`、`SIGTERM`、關終端機）都會自動恢復，
因為 fd 一關閉，核心就自動解除獨佔。

---

## 疑難排解

| 症狀 | 原因 / 解法 |
|---|---|
| `找不到 /dev/uinput` | `sudo modprobe uinput`，再跑 `setup-permissions.sh` |
| `沒有 /dev/uinput 的寫入權限` | 重新登入（群組），或暫時用 `sudo ./mousekey.py` |
| `--list-devices` 什麼都沒有 | 沒有讀 `/dev/input` 的權限 → 加入 `input` 群組 |
| 加入群組後還是沒權限 | **群組只對「新登入的 session」生效**：`newgrp input` 可立刻生效，或登出 niri 再登入 |
| 按鍵卡住、一直重複 | 程式被 SIGSTOP 了；`pkill -9 -f mousekey.py` |
| 切換沒反應 | 確認 `--send status` 有回應；沒回應表示程式沒在跑 |
| 切換有效但點擊沒反應 | 虛擬滑鼠沒被 udev 認成滑鼠（缺 `REL_X`/`REL_Y`）→ 用最新版；程式啟動時會自己警告 |
| 打字變得怪怪的 | `grab = true` 時所有鍵都會繞過虛擬鍵盤，延遲約 1–3ms，正常 |
| 打一個字出現兩次 | 同一把鍵盤被抓了兩條路徑 → `--probe` 找出正確的那個，用 `[device] match` 限定 |
| `Device or resource busy` | 裝置被 input-remapper / keyd 獨佔了 → 停用其中一個 |

除錯時很有用：

```bash
./mousekey.py --trace                # 正式執行，但逐行印出「收到什麼 / 送出什麼」
./mousekey.py --dry-run --verbose    # 不獨佔鍵盤，只印出「會送出什麼」
./mousekey.py --check                # 檢查設定 + 列出會用到的鍵盤
```

---

## 測試

```bash
python3 -m unittest discover -s tests -v
```

27 個測試，涵蓋狀態機、切換、拖曳、滾輪、孤兒事件、控制 socket 與完整主迴圈
（用假裝置，不需要真的鍵盤或 `/dev/uinput`）。

---

## 之後可以加

- [ ] **tap-hold**：`CapsLock` 輕按 = 鎖定切換、按住 = 暫時生效（kanata 風格）
- [ ] 設定檔熱重載
- [ ] Windows 後端（`WH_KEYBOARD_LL` + `SendInput`，可做成單一免安裝 exe）
- [ ] Rust 重寫成單一 static binary
- [ ] 鍵盤游標移動（`REL_X/REL_Y`，數字鍵盤或 hjkl）
- [ ] 多組 profile（切換不同的按鍵對應）
