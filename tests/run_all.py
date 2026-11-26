# -*- coding: utf-8 -*-
"""
一鍵執行全部功能測試。

    python tests/run_all.py

各測試檔皆以替身（stub）隔離 whisper／ffmpeg 相依，無須安裝任何
外部程式即可執行；每檔獨立子程序跑完並回報結果，全部通過才回傳 0。

另外兩件事（3.0 之後 A-5）：

- **使用者的個人資料檔不准動**：程式把 config.json（含 API 金鑰、習慣設定）與生字本存在「目前的
  資料夾」，從原始碼跑程式的人，這兩個檔就在專案根目錄。每個測試跑之前記下它們的內容，跑完被
  改過、建出來或刪掉就換回原樣，並把那個測試算失敗——test_v1500 曾經每跑一次就把整份 config.json
  換成只剩兩個區塊。
- **字型固定**：每個測試都拿到 FONTCONFIG_FILE＝tests/fonts.conf（已經有設的照用），量像素與
  版面的測試不會因為開發容器換了預設字型就失敗；原因見 tests/fonts.conf。
"""

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
FONTS_CONF = os.path.join(BASE, "fonts.conf")

# 程式用相對路徑存在「目前的資料夾」的個人資料（config.CONFIG_PATH、生字本 quicklookup.VOCAB_FILENAME）。
PROTECTED_FILES = ("config.json", "quicktranslate_vocab.json")

TESTS = ["test_pipeline.py", "test_review.py", "test_v140.py", "test_v150.py",
         "test_v160.py", "test_v170.py", "test_v180.py", "test_v190.py",
         "test_v1100.py", "test_v1110.py", "test_v1120.py", "test_v1130.py",
         "test_v1131.py", "test_v1140.py", "test_v1141.py", "test_v1150.py", "test_v1160.py", "test_v1170.py",
         "test_v1180.py", "test_v1190.py", "test_v1200.py", "test_v1201.py",
         "test_v1210.py", "test_v1220.py", "test_v1230.py", "test_v1240.py",
         "test_v1250.py", "test_v1260.py", "test_v1270.py", "test_v1280.py",
         "test_v1290.py", "test_v1300.py", "test_v1310.py",
         "test_v1320.py", "test_v1330.py",
         "test_v1340.py", "test_v1350.py",
         "test_v1360.py", "test_v1370.py",
         "test_v1380.py", "test_v1390.py",
         "test_v1400.py", "test_v1410.py", "test_v1420.py", "test_v1430.py", "test_v1440.py", "test_v1450.py", "test_v1460.py", "test_v1470.py",
         "test_v1480.py", "test_v1480_gui.py", "test_v1490.py",
         "test_v1500.py", "test_v1501.py", "test_v1510.py", "test_v1520.py",
         "test_v1521.py", "test_v1522.py", "test_v1523.py",
         "test_v200.py", "test_v210.py", "test_v220.py",
         "test_ocrlayout.py", "test_ocrengine.py",
         "test_tesseract_setup.py", "test_screencap.py",
         "test_hotkey.py", "test_speech.py",
         "test_screentranslate.py",
         "test_screentranslate_gui.py", "test_v230.py", "test_v231.py",
         "test_v232.py", "test_v233.py", "test_v235.py", "test_v236.py",
         "test_qt_skeleton.py", "test_qt_preview_pack.py", "test_qt_player.py", "test_waveform.py", "test_filmstrip.py",
         "test_qt_timeline.py", "test_cueedit.py", "test_qt_timeline_edit.py",
         "test_qt_timeline_undo.py", "test_qt_timeline_move.py",
         "test_dynamic_preview.py", "test_qt_dynamic_preview.py",
         "test_cutmarks.py", "test_qt_cutmarks.py", "test_qt_cutedit.py",
         "test_cutexport.py", "test_qt_cutexport.py", "test_proxy.py", "test_qt_proxy.py",
         "test_assemble.py", "test_qt_tracks.py", "test_qt_track_edit.py",
         "test_qt_overlay_preview.py", "test_qt_track_cuts.py", "test_qt_seam.py",
         "test_qt_preview_cut.py", "test_picture.py", "test_qt_picture.py",
         "test_qt_overlay_picture.py", "test_qt_crop.py", "test_project.py", "test_qt_project.py", "test_cuetext.py", "test_qt_proofread.py",
         "test_cuelist.py", "test_qt_cuelist.py", "test_cuetranslate.py", "test_qt_translate.py",
         "test_stylecheck.py", "test_qt_style.py", "test_qt_projectstyle.py", "test_generate.py",
         "test_qt_generate.py", "test_multilangpack.py", "test_qt_multilang.py",
         "test_qt_health.py", "test_qt_healthfix.py", "test_qt_healthmedia.py",
         "test_qt_healthpublish.py", "test_qt_healththumb.py", "test_qt_output.py", "test_qt_branding.py", "test_qt_music.py", "test_qt_review.py", "test_qt_review_output.py",
         "test_qt_review_publish.py", "test_qt_review_thumbs.py",
         "test_qt_review_shorts.py",
 "test_qt_audiovis.py",
 "test_batch_stop.py", "test_qt_batch.py", "test_qt_lookup.py",
 "test_qt_lookup_voice.py", "test_qt_lookup_screen.py",
 "test_qt_lookup_hotkey.py", "test_qt_series.py",
 "test_configmerge.py", "test_qt_settings_save.py",
 "test_tesseract_install_selected.py", "test_qt_install.py",
 "test_updatecheck.py", "test_qt_update_notice.py",
 "test_profiles.py", "test_qt_presets.py",
 "test_transcribecfg.py", "test_qt_transcription.py",
 "test_correctionrules.py", "test_qt_corrections.py",
 "test_qt_theme_toggle.py",
 "test_qtguide.py", "test_qt_guide.py",
 "test_onedirupdate.py", "test_qt_selfupdate.py",
 "test_switch_selftest.py",
    "test_qtbridge.py", "test_qtbridge_gui.py", "test_whatsnew30.py",
    "test_entry30.py", "test_qt_none_refcount.py", "test_licenses30.py",
    "test_configfile.py"]


def snapshot(folders) -> dict:
    """記下各資料夾裡個人資料檔現在的內容（bytes；不存在記 None）。"""
    state = {}
    for folder in folders:
        for name in PROTECTED_FILES:
            path = os.path.join(folder, name)
            try:
                with open(path, "rb") as fh:
                    state[path] = fh.read()
            except FileNotFoundError:
                state[path] = None
    return state


def restore(before: dict) -> list:
    """跟 `snapshot` 記下的比，被動過的檔換回原樣（原本沒有的就刪掉）；回傳被動過的路徑。"""
    touched = []
    for path, data in before.items():
        try:
            with open(path, "rb") as fh:
                now = fh.read()
        except FileNotFoundError:
            now = None
        if now == data:
            continue
        touched.append(path)
        if data is None:
            os.remove(path)
        else:
            with open(path, "wb") as fh:
                fh.write(data)
    return touched


def test_env(environ=None) -> dict:
    """給每個測試的環境變數：沒有另外指定字型設定的話，用 tests/fonts.conf。"""
    env = dict(os.environ if environ is None else environ)
    env.setdefault("FONTCONFIG_FILE", FONTS_CONF)
    return env


def run_one(path, folders, env=None):
    """跑一個測試檔：回傳（結束碼, 被動過而已經換回去的個人資料檔清單）。"""
    before = snapshot(folders)
    result = subprocess.run([sys.executable, path], env=test_env() if env is None else env)
    return result.returncode, restore(before)


def main() -> int:
    folders = sorted({os.path.realpath(os.getcwd()), os.path.realpath(ROOT)})
    failed = []
    for name in TESTS:
        print(f"===== {name} =====", flush=True)
        code, touched = run_one(os.path.join(BASE, name), folders)
        if touched:
            print(f"FAIL {name} 動到了使用者的個人資料檔（已換回原樣）：{', '.join(touched)}",
                  flush=True)
        if code != 0 or touched:
            failed.append(name)
    print()
    if failed:
        print(f"測試失敗：{', '.join(failed)}")
        return 1
    print(f"全部 {len(TESTS)} 個測試檔通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
