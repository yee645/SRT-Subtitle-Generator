# 配樂庫收集器

搜尋**開放授權**的剪輯配樂，自動依「**版權 → 情境 → 風格**」分資料夾存放，
檔名開頭直接帶同樣的分類標籤——檔案被拖進剪輯軟體或搬出資料夾，也一眼看得出
它能不能商用、要不要標註。

```
配樂庫/
├─ README_授權說明.txt        ← 給拿到資料夾的人看：每一類能怎麼用
├─ CREDITS_標註文字.txt       ← 用到哪首，就把那一行貼到影片說明欄
├─ 配樂清單.csv               ← Excel 直接開：授權、情境、風格、長度、原始頁面…
├─ 1_可商用-免標註(CC0-公眾領域)/
├─ 2_可商用-需標註作者(CC-BY)/
│   └─ 放鬆療癒/
│       └─ LoFi輕音/
│           └─ [需標註BY][放鬆療癒][浪漫甜蜜][LoFi輕音] Evening Tea - DJ Chill.mp3
├─ 3_可商用-需標註-影片需同授權(CC-BY-SA)/
├─ 4_非商用-需標註作者(CC-BY-NC)/
├─ 5_非商用-需標註-影片需同授權(CC-BY-NC-SA)/
└─ 9_僅限自用-勿轉傳(Pixabay等平台授權)/   ← 只有用 import 匯入的才會出現
```

只用 Python 標準函式庫，裝了 Python 3.8 以上就能跑，不必另外裝套件。

## 快速開始

Windows 命令列（在專案資料夾裡）：

```bat
py bgm_collector\collect_bgm.py fetch --dry-run
```

先**預覽**：只搜尋、不下載，產生 `配樂庫\配樂清單.csv`，用 Excel 打開看看抓到哪些歌、
分類合不合意。確定了再下載：

```bat
py bgm_collector\collect_bgm.py download
```

或一步到位（搜尋＋下載）：

```bat
py bgm_collector\collect_bgm.py fetch
```

預設每個情境收 10 首、13 個情境共約 130 首，Jamendo 的 mp3 一首約 3～8 MB，
整個配樂庫大約 0.5～1 GB。

### 常用參數

| 參數 | 說明 |
|------|------|
| `--moods 放鬆療癒,輕鬆愉快` | 只抓這幾個情境（`tags` 指令列出全部） |
| `--per-mood 30` | 每個情境收幾首。**重跑會補到這個數字**，已經有的不重抓 |
| `--commercial-only` | 只收可商用的（CC0、公眾領域、CC BY、CC BY-SA）。影片有開營利或接案用，建議加 |
| `--allow-vocal` | 也收有人聲的歌（預設只收純音樂，免得跟旁白打架） |
| `--min-sec` / `--max-sec` | 長度範圍，預設 30～600 秒 |
| `--layout mood/style` | 改資料夾層次，例如不分版權資料夾、情境直接放第一層 |
| `--out D:\素材\配樂庫` | 配樂庫放哪裡（預設目前資料夾下的「配樂庫」） |

## 版權分類

「有沒有版權」其實幾乎每首歌都有，真正要看的是**授權允許你做什麼**。這裡分成：

| 資料夾 | 授權 | 開營利／業配可用 | 要標註 | 影片需同授權 | 可轉傳給朋友 |
|---|---|:-:|:-:|:-:|:-:|
| `1_可商用-免標註` | CC0、公眾領域 | ✅ | — | — | ✅ |
| `2_可商用-需標註作者` | CC BY | ✅ | ✅ | — | ✅（附標註） |
| `3_可商用-需標註-影片需同授權` | CC BY-SA | ✅ | ✅ | ✅ | ✅（附標註） |
| `4_非商用-需標註作者` | CC BY-NC | ❌ | ✅ | — | ✅（附標註） |
| `5_非商用-需標註-影片需同授權` | CC BY-NC-SA | ❌ | ✅ | ✅ | ✅（附標註） |
| `9_僅限自用-勿轉傳` | Pixabay、YouTube 音效庫 | ✅ | 依平台 | — | ❌ |

- **「影片需同授權」**：CC 條款明定「音樂跟影像同步」算改作，所以用了 BY-SA 的歌，
  整支影片也要用 CC BY-SA 釋出。多數頻道不想這樣，所以單獨分一類。
- **禁止改作（ND）的歌完全不收**：同樣的理由，配進影片就違反授權。
- 標註文字照 CC 建議的 TASL 格式（曲名、作者、來源、授權）產生在
  `CREDITS_標註文字.txt`，例如：
  `Music: "Evening Tea" by DJ Chill (https://www.jamendo.com/track/...) | License: CC BY 3.0 https://creativecommons.org/licenses/by/3.0/`
- 上傳 YouTube 若被 Content ID 聲明（CC 的歌偶爾被發行商誤登記），拿清單上的
  原始頁面與授權條款去申訴。

## 情境與風格

**情境**（13 類）：輕鬆愉快、放鬆療癒、溫暖勵志、熱血動感、史詩壯闊、感傷抒情、
浪漫甜蜜、懸疑緊張、搞笑逗趣、科技未來、商務簡報、復古懷舊、節慶派對。

**風格**（12 類＋其他）：LoFi輕音、電子、流行、搖滾、嘻哈、爵士藍調、放克靈魂、
電影配樂、古典鋼琴、原聲民謠、氛圍、世界音樂。

分類依據是來源本身的標籤，不是用猜的：Jamendo 每首歌都有曲風（genres）與情緒標籤
（happy、relaxing、epic…）。情緒標籤命中最多的情境當資料夾，第二個情境有標籤命中時
也寫進檔名（`[放鬆療癒][浪漫甜蜜]`），所以在檔案總管搜尋「浪漫甜蜜」也找得到它。
對照表寫在 `collect_bgm.py` 開頭的 `MOODS`、`STYLES`，想加類別直接改那裡。

## 為什麼不直接爬 Pixabay

- Pixabay [服務條款](https://pixabay.com/service/terms/)明文禁止爬蟲與大量下載，
  [授權](https://pixabay.com/service/license-summary/)也禁止把音檔原封不動轉給別人
  （Standalone 散布）——收集來分享給朋友正好踩到這條。
- 這個工具改用 [Openverse](https://openverse.org)（WordPress 基金會維運的開放授權
  搜尋引擎）的 API，音樂來自 [Jamendo](https://www.jamendo.com)：每首歌都有機器
  可讀的授權、曲風與情緒標籤，而且 CC 授權本身就允許轉傳（標註跟著走就好）。

Pixabay、YouTube 音效庫的歌還是想一起管理的話，手動下載後用 `import` 歸類：

```bat
py bgm_collector\collect_bgm.py import "%USERPROFILE%\Downloads\*.mp3" --license pixabay
py bgm_collector\collect_bgm.py import 某首.mp3 --license ytal --mood 熱血動感 --style 電子
```

它們會放進 `9_僅限自用-勿轉傳`，檔名標 `[自用Pixabay]`／`[自用YT音效庫]`。情境和風格
會先從檔名猜（Pixabay 檔名通常含曲名，如 `lofi-study-112191.mp3`），猜不準就用
`--mood`、`--style` 指定。在別處下載的 CC 歌也能匯入：
`--license by --artist 作者 --url 原始頁面`，標註文字會一起產生。

## API 額度

Openverse 不需要帳號就能用，但匿名額度不高。額度用完時程式會停下來、把已找到的
歌存好並下載，**晚點再執行同一個指令就會接續**。常常要大量抓的話，申請免費金鑰：

```bat
py bgm_collector\collect_bgm.py register --name bgm-collector-你的名字 --email 你的信箱
```

照畫面指示收驗證信、設定環境變數 `OPENVERSE_CLIENT_ID`／`OPENVERSE_CLIENT_SECRET`，
之後 `fetch` 就會自動使用金鑰。金鑰**不要**存進配樂庫資料夾，免得跟著分享出去。

## 分享給朋友

建議**本機放一份主檔、用 Google Drive 共用資料夾分享**：

1. 剪輯軟體讀本機檔案最快，主檔放本機（或外接硬碟）。
2. 把整個「配樂庫」資料夾上傳到 Google Drive（或裝「Google 雲端硬碟」電腦版，
   讓資料夾自動同步），**排除 `9_僅限自用-勿轉傳`**。
3. 對朋友的 Gmail 分享「檢視者」權限，不要開「知道連結的任何人」。
4. 朋友在網頁上就能試聽再挑著下載，或裝電腦版同步到自己電腦直接拖進剪輯軟體；
   之後你再跑 `fetch --per-mood 20` 補歌，他那邊會自動多出來。

`README_授權說明.txt`、`CREDITS_標註文字.txt`、`配樂清單.csv` 放在資料夾最上層，
朋友拿到就知道每一類能怎麼用、要怎麼標註——這也是 CC 授權轉傳時的要求。

## 測試

```bash
python tests/test_bgm_collector.py
```

不連網：Openverse API 與下載都用替身，回傳格式照 Openverse 原始碼的真實欄位。
