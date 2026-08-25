# -*- coding: utf-8 -*-
"""
命令列批次模式（免開 GUI）。

沿用 config.json 中記憶的所有設定（轉寫、斷句、樣式、自動化輸出），
直接對一個或多個檔案跑完整自動流程：生成字幕 → 匯出 →（可選）燒錄。

使用範例：
    python main.py 影片1.mp4 影片2.mp4
    python main.py --mode align 演講.mp4          # 文字稿放在同名的 演講.txt
    python main.py --burn *.mp4                   # 匯出並燒錄硬字幕影片
    python main.py --formats srt,ass 影片.mp4     # 本次改匯出 SRT 與 ASS
    python main.py --output-dir D:/out 影片.mp4   # 本次改輸出到指定資料夾
    python main.py --review 素材1.mp4 素材2.mp4   # 批次審片：輸出片段分析 CSV
    python main.py --shorts 長片.mp4              # 自動挑段並輸出多支直式短片
    python main.py --multilang 影片.mp4           # 多語字幕包：一次翻成多國語言
    python main.py --beatcheck --music 配樂.mp3 影片.mp4  # 節拍分析＋剪點對齊
    python main.py --multilang --languages en,ja,ko --subs 字幕.srt 影片.mp4
    python main.py --shorts --shorts-count 5 *.mp4  # 批次：每支各出 5 支短片
    python main.py --audiocheck 影片.mp4          # 上片前音訊健檢（免轉錄）
    python main.py --thumbnails 影片.mp4          # 封面候選圖（免轉錄）
    python main.py --audiofix 影片.mp4            # 音訊修復版（降噪等，免轉錄）
    python main.py --branding 影片.mp4          # 套用已設定的片頭/片尾/浮水印
    python main.py --review --thumbnails 素材.mp4 # 審片＋精彩段落封面候選
    python main.py --subs 影片.srt --burn 影片.mp4   # 既有字幕直接燒錄（免轉錄）
    python main.py --subcheck 影片.mp4            # 字幕健檢（閱讀速度/行數/時間軸重疊，可與其他模式併用）
    python main.py --jumpcut 影片.mp4             # 自動跳剪：剪掉句間停頓，字幕同步對齊
    python main.py --retakes 影片.mp4             # 重複片段偵測：輸出候選清單（不自動剪）
    python main.py --retakes --retakes-cut 影片.mp4  # 偵測後直接剪掉全部候選重複片段
    python main.py --volumecheck 影片.mp4         # 分段音量一致性分析（免轉錄）
    python main.py --volumefix 影片.mp4           # 一鍵拉平音量落差過大的段落（免轉錄）
    python main.py --audiovis 節目.mp3            # 音訊轉波形／頻譜視覺化影片
    python main.py --colorcheck 影片.mp4          # 畫面曝光與色偏健檢（免轉錄）
    python main.py --adcheck 影片.mp4             # 廣告友善度自查（黃標風險預檢）
    python main.py --hookcheck 影片.mp4           # 開場健檢（多久才進正題）
    python main.py --pacecheck 影片.mp4           # 剪輯節奏健檢（畫面太久沒變化）
    python main.py --thumbcheck 封面1.png 封面2.png # 封面健檢（手機上看不看得清）
    python main.py --publishcheck 發佈資訊.txt 影片.mp4  # 發佈資訊健檢（hashtag/長度上限）
    python main.py --legibility 影片.mp4          # 字幕可讀性（燒錄後看不看得清）
    python main.py --endscreen 影片.mp4           # 片尾空間（結束畫面放不放得下）
    python main.py --sponsorcheck 影片.mp4        # 工商揭露（業配揭露得夠不夠早）
    python main.py --termcheck 影片.mp4           # 術語一致性（同一個詞有幾種寫法）
    python main.py --termcheck --termfix 影片.mp4 # 順便把有主流寫法的統一
    python main.py --punctcheck 影片.mp4          # 中文字幕標點規範（行尾多餘標點）
    python main.py --punctcheck --punctfix 影片.mp4 # 順便輸出規範化後的字幕
    python main.py --preflight 影片.mp4           # 上片前總體檢（一次跑完所有健檢）
    python main.py --subs 舊字幕.srt --synccheck 影片.mp4  # 字幕與語音同步檢查

命令列旗標僅影響本次執行，不會改寫 config.json 記憶的設定。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from config import load_config
from subtitle.adbreaks import resolve_adbreak_settings, suggest_ad_breaks
from subtitle.adfriendly import (format_adfriendly_report,
                                 resolve_adfriendly_settings, scan_cues)
from subtitle.audio import DEFAULT_TARGET_LUFS
from subtitle.audiocheck import format_report, run_audio_check
from subtitle.audiofix import (fix_audio, resolve_audiofix_settings,
                               suggest_output_path)
from subtitle.audiovis import (render_audio_video, resolve_audiovis_settings,
                               suggest_output_path as
                               suggest_audiovis_output_path)
from subtitle.branding import (apply_branding, resolve_branding_settings,
                               suggest_output_path as
                               suggest_branding_output_path)
from subtitle.colorcheck import (analyze_color, format_color_report,
                                 resolve_colorcheck_settings)
from subtitle.errors import format_error_text
from subtitle.exporter import export
from subtitle.ffmpeg_setup import ensure_ffmpeg_on_path
from subtitle.importer import load_subtitle_file
from subtitle.jumpcut import (apply_jumpcut, format_jumpcut_report,
                              resolve_jumpcut_settings, suggest_output_path
                              as suggest_jumpcut_output_path)
from subtitle.retakes import (apply_retake_removal, find_retakes,
                              format_retake_removal_report,
                              format_retakes_report, resolve_retake_settings,
                              suggest_output_path as
                              suggest_retakes_output_path)
from subtitle.chaptercheck import (fix_chapters, format_chapter_report,
                                   format_chapters_text, parse_chapters,
                                   resolve_chaptercheck_settings,
                                   validate_chapters)
from subtitle.hookcheck import (analyze_hook, format_hook_report,
                                resolve_hookcheck_settings)
from subtitle.pacing import (analyze_pacing, format_pacing_report,
                             resolve_pacing_settings)
from subtitle.thumbcheck import (format_ranking_report,
                                 format_thumb_report,
                                 rank_thumbnails,
                                 resolve_thumbcheck_settings)
from subtitle.desccheck import (analyze_description, format_desc_report,
                                resolve_desccheck_settings)
from subtitle.publishcheck import (analyze_publish,
                                   format_publish_report,
                                   resolve_publishcheck_settings)
from subtitle.legibility import (analyze_legibility,
                                 format_legibility_report,
                                 resolve_legibility_settings)
from subtitle.endscreen import (analyze_endscreen,
                                format_endscreen_report,
                                resolve_endscreen_settings)
from subtitle.sponsorcheck import (analyze_sponsor,
                                   format_sponsor_report,
                                   resolve_sponsorcheck_settings)
from subtitle.termcheck import (analyze_terms, apply_term_fixes,
                                build_fix_choices, format_term_report,
                                resolve_termcheck_settings)
from subtitle.punctstyle import (analyze_punctuation, apply_punct_style,
                                 format_punct_report,
                                 resolve_punctstyle_settings)
from subtitle.preflight import (format_preflight_report,
                                run_preflight)
from subtitle.media import probe_duration
from subtitle.pipeline import (EXPORT_FORMATS, enabled_export_formats,
                               export_and_burn, run_batch, unique_path)
from subtitle.publisher import build_publish_pack, resolve_publish_settings
from subtitle.seriescheck import (analyze_series, format_series_report,
                                  resolve_seriescheck_settings)
from subtitle.subsync import (analyze_sync, apply_sync_correction,
                              format_sync_report, resolve_subsync_settings)
from subtitle.subtitlecheck import (analyze_cues, format_subtitle_report,
                                    resolve_subcheck_settings)
from subtitle.videocheck import (format_video_report, run_video_check)
from subtitle.volumeconsistency import (analyze_volume_consistency,
                                        fix_volume_consistency,
                                        format_volume_consistency_report,
                                        resolve_volume_consistency_settings,
                                        suggest_output_path as
                                        suggest_volume_output_path)
from subtitle.thumbnails import (generate_thumbnails,
                                 resolve_thumbnail_settings)
from subtitle.clipplan import (format_clip_plan_report, plan_clips,
                               resolve_clipplan_settings)
from subtitle.beatsync import (analyze_beats, format_beat_report,
                               resolve_beatsync_settings, snap_times)
from subtitle.multilang import (build_language_pack, format_pack_report,
                                pack_path, parse_languages,
                                resolve_multilang_settings)
from subtitle.translator import resolve_translate_settings
from subtitle.shorts import cut_vertical_clip, resolve_shorts_settings
from subtitle.segmenter import build_cues_from_words
from subtitle.review import (analyze, build_chapters, collect_highlights,
                             compute_loudness, export_batch_csv,
                             export_batch_html, export_csv,
                             export_html_report, resolve_settings)
from subtitle.transcriber import transcribe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="SRT 字幕自動化批次工具：生成字幕 → 匯出 →（可選）燒錄，"
                    "設定沿用 config.json。",
    )
    parser.add_argument(
        "files", nargs="+", metavar="媒體檔",
        help="要處理的影片或音訊檔，可一次列出多個。")
    parser.add_argument(
        "--mode", choices=["transcribe", "align"], default="transcribe",
        help="transcribe＝模式一音訊轉錄（預設）；align＝模式二文字稿對齊"
             "（文字稿放在媒體檔旁的同名 .txt）。")
    parser.add_argument(
        "--formats", metavar="srt,vtt,ass,txt",
        help="本次要匯出的格式（逗號分隔）；未指定時沿用 config.json 的勾選。")
    parser.add_argument(
        "--burn", action="store_true",
        help="本次強制燒錄硬字幕影片（覆寫 config.json 設定）。")
    parser.add_argument(
        "--no-burn", action="store_true",
        help="本次強制不燒錄（覆寫 config.json 設定）。")
    parser.add_argument(
        "--loudnorm", action="store_true",
        help="本次燒錄時強制做響度正規化（目標值沿用 config.json，預設 -14 LUFS）。")
    parser.add_argument(
        "--no-loudnorm", action="store_true",
        help="本次強制不做響度正規化（覆寫 config.json 設定）。")
    parser.add_argument(
        "--output-dir", metavar="資料夾",
        help="本次輸出資料夾；未指定時沿用 config.json（留空＝來源資料夾）。")
    parser.add_argument(
        "--review", action="store_true",
        help="審片模式：不產字幕，改為分析素材（冷場、重複拍攝、口頭禪）"
             "並輸出「檔名_審片清單.csv」，供快速挑選可用片段。")
    parser.add_argument(
        "--audiocheck", action="store_true",
        help="音訊健檢：檢查爆音、音量、底噪與聲道平衡，"
             "輸出「檔名_音訊健檢.txt」報告；可單獨使用或與 --review 併用。")
    parser.add_argument(
        "--thumbnails", action="store_true",
        help="封面候選：自動挑清晰畫面輸出「檔名_封面NN.png」候選圖；"
             "與 --review 併用時優先取精彩段落，單獨使用時整片均勻取樣。")
    parser.add_argument(
        "--videocheck", action="store_true",
        help="影片畫質健檢：位元率／解析度／更新率／編碼對照 YouTube 建議，"
             "並偵測頭尾廢秒，附加於健檢報告；可與 --audiocheck 併用。")
    parser.add_argument(
        "--audiofix", action="store_true",
        help="音訊修復：依 config.json 的 audiofix 設定（降噪／去低頻／"
             "響度正規化）輸出「檔名_修復」版本，畫面原樣複製。")
    parser.add_argument(
        "--branding", action="store_true",
        help="品牌套版：套用 config.json 已設定的片頭／片尾／浮水印，"
             "輸出「檔名_套版」版本；未設定任何一項時單檔略過並提示。")
    parser.add_argument(
        "--volumecheck", action="store_true",
        help="分段音量一致性分析：把影片切成固定長度分段逐段量測響度，"
             "找出與整體中位數落差過大（忽大忽小）的段落，輸出"
             "「檔名_音量一致性.txt」報告；可與 --audiocheck 併用。")
    parser.add_argument(
        "--volumefix", action="store_true",
        help="一鍵拉平音量：對音量落差過大的段落套用增益調整到接近整體"
             "中位數響度，其餘段落不動，輸出「檔名_音量平衡」版本"
             "（畫面原樣複製，僅音軌重新編碼）；沒有偵測到落差時單檔"
             "略過並提示。")
    parser.add_argument(
        "--colorcheck", action="store_true",
        help="畫面曝光與色偏健檢：全片均勻取樣，偵測曝光不足／過曝與明顯"
             "色偏（白平衡問題），輸出「檔名_色彩健檢.txt」報告（僅列出"
             "建議，不自動校色）；可與 --audiocheck／--videocheck 併用。")
    parser.add_argument(
        "--audiovis", action="store_true",
        help="音訊轉視覺化影片：把純音訊檔（podcast／錄音訪談等）轉成附"
             "波形或頻譜視覺化的 mp4，輸出「檔名_視覺化影片.mp4」；樣式"
             "（波形/頻譜、顏色、解析度、背景圖）依 config.json 的 "
             "audiovis 設定。輸出檔可直接當作來源接上轉錄／字幕燒錄等"
             "既有流程。")
    parser.add_argument(
        "--subs", metavar="字幕檔",
        help="使用既有字幕檔（.srt/.vtt）跳過語音辨識：搭配一個媒體檔，"
             "依自動化輸出設定匯出其他格式並可 --burn 燒錄硬字幕。")
    parser.add_argument(
        "--subcheck", action="store_true",
        help="字幕健檢：檢查產生（或 --subs 匯入）的字幕閱讀速度（CPS）、"
             "顯示時間、行數與時間軸重疊，輸出「檔名_字幕健檢.txt」報告"
             "（僅列出問題，修復請於 GUI 字幕健檢對話框操作）；可與一般"
             "轉錄／對齊模式或 --subs 併用（--review 等不產生字幕的"
             "模式無效果）。")
    parser.add_argument(
        "--chaptercheck", metavar="章節檔",
        help="YouTube 章節健檢：讀入一個純文字檔（每行「時間戳 空白 標題」，"
             "可直接是從說明欄複製回來的內容），檢查是否符合 YouTube 顯示"
             "章節的規則（首章 0:00、至少 3 章、每章至少 10 秒、時間戳格式），"
             "輸出「檔名_章節健檢.txt」。章節不合規時 YouTube 只會靜默不顯示、"
             "不給任何錯誤訊息，這個檢查就是要把原因指出來。需搭配一個媒體檔"
             "以取得影片長度（才能檢查最後一章）。")
    parser.add_argument(
        "--chapterfix", action="store_true",
        help="搭配 --chaptercheck 使用：把能安全修正的問題直接改好（排序、"
             "移除重複時間、首章補成 0:00、過短章節併入前一章），另存"
             "「檔名_章節修正.txt」可直接貼回說明欄；原始檔不受影響。"
             "章節數不足時不會憑空捏造章節，只會如實回報。")
    parser.add_argument(
        "--seriescheck", action="store_true",
        help="系列一致性檢查：比對一次給定的多支影片「彼此之間」的響度、"
             "解析度、更新率、編碼與畫面亮度／色調是否一致（以整批中位數"
             "為基準，抓出偏離整批的那幾支），輸出「系列一致性檢查.txt」。"
             "與單支影片是否合格的健檢（--audiocheck 等）是不同的問題；"
             "需一次給至少 2 個檔案。")
    parser.add_argument(
        "--synccheck", action="store_true",
        help="字幕與語音同步檢查：掃出素材實際語音區間，檢查字幕是否對得上，"
             "並自動算出建議的線性校正（同時涵蓋整體偏移與幀率漂移），"
             "輸出「檔名_同步檢查.txt」。特別適合搭配 --subs 匯入的既有"
             "字幕檔使用。")
    parser.add_argument(
        "--syncfix", action="store_true",
        help="搭配 --synccheck 使用：偵測到不同步時直接套用建議校正，另存"
             "「檔名_同步校正.ext」字幕（只調整時間軸、不改動文字內容，"
             "原始字幕檔不受影響）；判定為同步正常或無法可靠判定時略過。")
    parser.add_argument(
        "--adcheck", action="store_true",
        help="廣告友善度自查（黃標風險預檢）：掃描產生（或 --subs 匯入）的"
             "字幕，找出可能觸發 YouTube 廣告友善度審查的用詞，並以時間窗"
             "叢集分析標出「短時間內風險詞密集」的高風險段落，輸出"
             "「檔名_廣告友善度.txt」；詞表可於 config.json 的 adfriendly "
             "增補（extra_terms）與排除誤判（ignore_terms）。僅供自查，"
             "不自動改動內容。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--preflight", action="store_true",
        help="上片前總體檢：一次跑完所有適用的健檢（音訊、畫質、色偏、"
             "音量一致性、剪輯節奏、片尾空間，有字幕時再加上字幕健檢、"
             "廣告友善度、開場健檢、字幕可讀性、工商揭露與術語一致性），把結果依嚴重度排成一份清單並給出"
             "準備度評級。依素材自動略過不適用的項目（純音訊檔跳過畫面"
             "檢查、沒有字幕跳過字幕檢查）。輸出「檔名_總體檢.txt」；"
             "各項可於 config.json 的 preflight 單獨關閉。")
    parser.add_argument(
        "--legibility", action="store_true",
        help="字幕可讀性健檢：量測字幕實際會落在畫面上的那一條帶子有多亮，"
             "與文字顏色相比，抓出「燒錄後會糊在背景裡」的段落。白字遇到"
             "偏白的畫面就看不見，而這通常要等到燒錄完、播出去才發現。"
             "輸出「檔名_字幕可讀性.txt」；門檻可於 config.json 的 "
             "legibility 調整。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--endscreen", action="store_true",
        help="片尾空間健檢：YouTube 的結束畫面加在影片結束前的 5~20 秒處，"
             "官方也明講「編輯時請務必考慮影片最後 20 秒」。檢查最後這段"
             "放不放得下結束畫面、字幕會不會落進元素會擺的位置、有沒有"
             "變成一段什麼都不講的死寂片尾，以及畫面是不是雜到元素疊上去"
             "看不清。輸出「檔名_片尾空間.txt」；門檻可於 config.json 的 "
             "endscreen 調整。可與一般轉錄／對齊模式或 --subs 併用；"
             "沒有字幕也能跑（沒字幕本身就是死寂片尾的徵兆）。")
    parser.add_argument(
        "--sponsorcheck", action="store_true",
        help="工商揭露健檢：掃描逐字稿找出業配／贊助段落，檢查有沒有揭露、"
             "以及揭露是不是講在段落開始「之前」。FTC 已明確指出「影片稍早"
             "就出現業配、卻把揭露放在後面」不符合清楚顯著的標準，而揭露"
             "義務與頻道大小、金額無關。另外會把工商段落排成可直接貼上的"
             "章節行，讓觀眾能跳過（坦白反而留得住觀眾）。輸出"
             "「檔名_工商揭露.txt」；詞表與門檻可於 config.json 的 "
             "sponsorcheck 調整。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--beatcheck", action="store_true",
        help="音樂節拍分析：量出配樂的 BPM 與每一拍的時間點，並把影片"
             "既有的剪接點對齊到最近的拍子上。調研指出「把轉場對齊到"
             "音樂的重拍與停頓」至今仍是編輯得手動做的事。搭配 --music "
             "指定配樂檔；若位置參數是影片，會一併掃出畫面剪接點並算出"
             "各要挪多少秒。離拍子太遠的剪點不會硬挪（那會讓畫面與內容"
             "對不上）。輸出「檔名_節拍分析.txt」；門檻可於 config.json "
             "的 beatsync 調整。純人聲或環境音沒有穩定拍點時會據實回報。")
    parser.add_argument(
        "--music", metavar="配樂檔",
        help="搭配 --beatcheck 使用：要分析節拍的音樂檔；未指定時改為"
             "分析位置參數本身的音訊。")
    parser.add_argument(
        "--multilang", action="store_true",
        help="多語字幕包：把一份校對好的母帶字幕一次翻成多國語言，每個語言"
             "各輸出一個可直接上傳的「單語」SRT（如「影片.en.srt」）。"
             "YouTube 官方指出平均超過三分之二的觀看時間來自居住地區以外"
             "的觀眾。注意上傳用的字幕每個語言都必須是單語檔——既有的"
             "「字幕翻譯」產出的是給燒錄用的雙語字幕，拿去上傳英文觀眾"
             "每一句都會看到黏著的原文。需要 OpenAI API 金鑰（沿用轉寫"
             "設定的金鑰）；語言清單可於 config.json 的 multilang 調整。")
    parser.add_argument(
        "--languages", metavar="語言代碼",
        help="搭配 --multilang 使用：本次要翻的語言（逗號分隔，如 "
             "en,ja,ko），覆寫 config.json 的 multilang.languages。")
    parser.add_argument(
        "--shorts", action="store_true",
        help="自動把長片挑成多支直式短片（9:16）：沿用審片模組已經算好的"
             "精彩片段，規劃出彼此不重疊、長度落在平台可用範圍的段落，"
             "再逐段輸出「檔名_短片01.mp4」。太短的片段會沿講話段落邊界"
             "往外擴（不會從句子中間切），擴不到最短長度就放棄而不硬湊。"
             "本模式會先轉錄，可與 --thumbnails／--audiocheck 併用；"
             "支數與長度可於 config.json 的 clipplan 調整。")
    parser.add_argument(
        "--shorts-count", type=int, metavar="支數",
        help="搭配 --shorts 使用：本次要輸出幾支短片（覆寫 config.json 的"
             " clipplan.count，僅影響本次執行）。")
    parser.add_argument(
        "--termcheck", action="store_true",
        help="術語一致性檢查：找出同一個詞在同一支影片裡被寫成好幾種樣子"
             "（YouTube／Youtube／youtube、Anthropic／Anthropik）。語音辨識"
             "最會錯的就是專有名詞，而且會拿發音相近的詞去替換，導致同一個"
             "名字前後拼法不一致。輸出「檔名_術語一致性.txt」，並列出可以"
             "直接貼進「自動修正詞庫」的規則；門檻可於 config.json 的 "
             "termcheck 調整。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--termfix", action="store_true",
        help="搭配 --termcheck 使用：把有明確主流寫法的詞一鍵統一，另存"
             "「檔名_術語統一.srt」；原始檔不受影響。各種寫法出現次數"
             "一樣多時不會替你猜，會原樣保留並在報告中標示。")
    parser.add_argument(
        "--punctcheck", action="store_true",
        help="中文字幕標點規範健檢：抓出行尾那些沒有作用的逗號句號（斷行"
             "本身就已經表達停頓），輸出「檔名_標點規範.txt」。英文字幕"
             "不受影響。強度可於 config.json 的 punctstyle 調整。")
    parser.add_argument(
        "--punctfix", action="store_true",
        help="搭配 --punctcheck 使用：把標點規範化後另存「檔名_標點規範.srt」。")
    parser.add_argument(
        "--publishcheck", metavar="發佈資訊檔",
        help="發佈資訊健檢（免轉錄、免媒體）：讀入一個純文字檔，第一行為"
             "標題、其餘為說明欄；檢查標題 100 字元、說明欄 5000「位元組」"
             "（不是字數，中文一字佔 3 位元組）、hashtag 15 個上限與標籤"
             "500 字元預算。hashtag 超過 15 個時 YouTube 會忽略全部而且"
             "不給任何提示——這是最常見也最難自己發現的坑。輸出"
             "「檔名_發佈健檢.txt」；門檻可於 config.json 的 publishcheck "
             "調整。可搭配 --tags 一併檢查標籤欄位。")
    parser.add_argument(
        "--tags", metavar="標籤",
        help="搭配 --publishcheck 使用：以逗號分隔的標籤字串，一併檢查是否"
             "超過標籤欄位的總字元預算。")
    parser.add_argument(
        "--thumbcheck", action="store_true",
        help="封面健檢（免轉錄）：把要檢查的**封面圖片**直接當作位置參數傳入"
             "（可一次給多張），檢查它們在手機尺寸下還看不看得清楚。"
             "手機清單裡的縮圖只有約 200 像素寬，畫面太雜、對比太低、"
             "灰濛濛都會讓人直接滑過去。給多張時依綜合分數排序並指出"
             "該用哪一張，輸出「封面健檢.txt」；門檻可於 config.json 的"
             " thumbcheck 調整。")
    parser.add_argument(
        "--pacecheck", action="store_true",
        help="剪輯節奏健檢（免轉錄）：用畫面變化偵測把影片切成一個個鏡頭，"
             "抓出「畫面太久沒有變化」的段落並建議 B-roll／推鏡的插入時間點。"
             "與凍結畫面偵測是相反的性質——凍結看的是畫面完全靜止，"
             "這裡看的是雖然有動、卻久久沒有換過鏡頭。輸出"
             "「檔名_剪輯節奏.txt」；門檻可於 config.json 的 pacing 調整。")
    parser.add_argument(
        "--hookcheck", action="store_true",
        help="開場健檢：檢查影片開頭多久才進正題，抓出冗長的打招呼、自我介紹、"
             "頻道宣傳、無關閒聊與「一開場就要訂閱」——這些是觀眾在開頭"
             "幾秒內離開的主因。判斷依據是「扣掉開場套語後這句還剩多少"
             "實質內容」，因此「廢話不多說，今天要教大家…」會正確算成已"
             "進正題。輸出「檔名_開場健檢.txt」；套語可於 config.json 的"
             " hookcheck 增補（extra_filler_terms）與排除誤判（ignore_terms）。"
             "僅供自查，不自動改動內容。可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--jumpcut", action="store_true",
        help="自動跳剪：依產生（或 --subs 匯入）的字幕找出句間過長停頓，"
             "一次剪掉整支影片的停頓並輸出「檔名_跳剪.mp4」，同步匯出"
             "時間軸已對齊的字幕「檔名_跳剪.ext」；門檻依 config.json 的"
             "jumpcut 設定。可與一般轉錄／對齊模式或 --subs 併用"
             "（--review 等不產生字幕的模式無效果）；注意 --burn 燒錄的"
             "仍是原始（未跳剪）影片，兩者不會自動串接。")
    parser.add_argument(
        "--retakes", action="store_true",
        help="重複片段偵測：找出同一時間窗內文字高度相似的句子（同一句話"
             "講了好幾次），輸出候選清單「檔名_重複片段.txt」；預設只列出"
             "候選、不自動剪（假陽性風險比跳剪高，例如刻意重複的口號）。"
             "可與一般轉錄／對齊模式或 --subs 併用。")
    parser.add_argument(
        "--retakes-cut", action="store_true",
        help="搭配 --retakes 使用：偵測後直接剪掉全部候選重複片段（只保留"
             "每組最後一次），輸出「檔名_去重複.mp4」＋同步對齊的字幕；"
             "命令列無法逐項確認，請先用 --retakes 看過候選清單再決定是否"
             "加上此旗標。")
    return parser


def _apply_overrides(config: dict, args: argparse.Namespace) -> None:
    """把命令列旗標套進本次使用的設定（不寫回 config.json）。"""
    automation = config["automation"]
    if args.formats is not None:
        wanted = {item.strip().lower().lstrip(".")
                  for item in args.formats.split(",") if item.strip()}
        known = {ext.lstrip(".") for ext in EXPORT_FORMATS}
        unknown = wanted - known
        if unknown:
            raise SystemExit(f"不支援的匯出格式：{', '.join(sorted(unknown))}"
                             f"（可用：{', '.join(sorted(known))}）")
        for ext in known:
            automation[f"export_{ext}"] = ext in wanted
    if args.burn:
        automation["burn_video"] = True
    if args.no_burn:
        automation["burn_video"] = False
    if args.loudnorm:
        automation["loudnorm"] = True
    if args.no_loudnorm:
        automation["loudnorm"] = False
    if args.output_dir is not None:
        automation["output_dir"] = args.output_dir


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # 先前「自動安裝 ffmpeg」裝好的執行檔在此生效（不改動系統 PATH）。
    ensure_ffmpeg_on_path()
    config = load_config()
    _apply_overrides(config, args)

    def report(message, ratio=None):
        percent = f"{int(ratio * 100):3d}% " if ratio is not None else "     "
        print(f"{percent}{message}", flush=True)

    if args.publishcheck:
        # 發佈資訊健檢的輸入是「一份文字」而非媒體內容，與其他逐檔處理的
        # 模式結構不同，因此獨立成一個分支。
        # 位置參數若給了媒體檔，拿來取得影片長度（判斷該不該有章節）。
        media = next((f for f in args.files if os.path.exists(f)), "")
        results = _run_publishcheck(args.publishcheck, args.tags, config,
                                    report, media_path=media)
    elif args.thumbcheck:
        # 封面健檢的輸入是「圖片」而非影片內容，與其他逐檔處理的模式
        # 結構不同，因此獨立成一個分支。
        results = _run_thumbcheck(args.files, config, report)
    elif args.chaptercheck:
        # 章節健檢的輸入是「一份章節文字」而非媒體內容，媒體檔只用來取得
        # 影片長度，因此與其他逐檔處理的模式結構不同，獨立成一個分支。
        if len(args.files) != 1:
            raise SystemExit(
                "--chaptercheck 需搭配「剛好一個」媒體檔（用來取得影片長度，"
                "才能檢查最後一章的長度），目前給了 "
                f"{len(args.files)} 個檔案。")
        results = _run_chaptercheck(
            args.files[0], args.chaptercheck, config, report,
            do_fix=args.chapterfix)
    elif args.seriescheck:
        # 系列一致性是「整批比一批」，產出單一份跨檔報告，
        # 與其他逐檔處理的模式結構不同，因此獨立成一個分支。
        results = _run_seriescheck(args.files, config, report)
    elif args.subs:
        if len(args.files) != 1:
            raise SystemExit(
                "--subs 需搭配「剛好一個」媒體檔（跳過語音辨識，"
                "直接用既有字幕匯出／燒錄），目前給了 "
                f"{len(args.files)} 個檔案。")
        results = _run_subs_batch(args.files[0], args.subs, config, report)
    elif args.review or args.shorts:
        results = _run_review_batch(
            args.files, config, report,
            with_audiocheck=args.audiocheck,
            with_thumbnails=args.thumbnails,
            with_shorts=args.shorts,
            shorts_count=args.shorts_count)
    elif (args.audiocheck or args.thumbnails or args.audiofix
            or args.branding or args.videocheck or args.volumecheck
            or args.volumefix or args.audiovis or args.colorcheck
            or args.pacecheck or args.beatcheck):
        # 免轉錄的輕量工具模式：健檢、封面候選、音訊修復、品牌套版與
        # 節拍分析都只需 ffmpeg，不必先跑語音辨識。
        results = _run_tools_batch(
            args.files, config, report,
            do_audiocheck=args.audiocheck,
            do_thumbnails=args.thumbnails,
            do_audiofix=args.audiofix,
            do_branding=args.branding,
            do_videocheck=args.videocheck,
            do_volumecheck=args.volumecheck,
            do_volumefix=args.volumefix,
            do_audiovis=args.audiovis,
            do_colorcheck=args.colorcheck,
            do_pacecheck=args.pacecheck)
    else:
        results = run_batch(
            args.files, config, mode=args.mode, report=report)

    if args.jumpcut:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            try:
                new_paths = _export_jumpcut(
                    item["path"], cues, config, out_dir, formats, report)
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                report(f"{os.path.basename(item['path'])}：跳剪略過（{exc}）")
                continue
            item["result"]["exports"].extend(new_paths)

    if args.retakes:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        retake_settings = resolve_retake_settings(config)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            found = find_retakes(cues, retake_settings)
            report_text = format_retakes_report(found)
            report_path = unique_path(
                os.path.join(out_dir, f"{base}_重複片段.txt"))
            with open(report_path, "w", encoding="utf-8") as fp:
                fp.write(report_text)
            print(report_text, flush=True)
            item["result"]["exports"].append(report_path)
            if found and args.retakes_cut:
                try:
                    new_paths = _export_retakes(
                        item["path"], cues, found, config, out_dir, formats,
                        report)
                except (RuntimeError, ValueError, FileNotFoundError) as exc:
                    report(f"{os.path.basename(item['path'])}："
                          f"去重複略過（{exc}）")
                    continue
                item["result"]["exports"].extend(new_paths)

    if args.subcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            check_path = _export_subcheck(cues, config, out_dir, base)
            item["result"]["exports"].append(check_path)

    if args.synccheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        formats = enabled_export_formats(automation)
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].extend(_export_synccheck(
                    item["path"], cues, config, out_dir, base,
                    formats, args.syncfix))
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                report(f"{os.path.basename(item['path'])}："
                      f"同步檢查略過（{exc}）")

    if args.adcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            item["result"]["exports"].append(
                _export_adcheck(cues, config, out_dir, base))

    if args.preflight:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            path = item["path"]
            if not os.path.exists(path):
                continue
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            out_dir = out_dir_override or os.path.dirname(os.path.abspath(path))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            try:
                def progress(ratio, message):
                    report(message, ratio)
                result = run_preflight(path, cues or [], config,
                                       progress_cb=progress)
                text = format_preflight_report(result)
                out_path = unique_path(os.path.join(
                    out_dir, f"{base}_總體檢.txt"))
                with open(out_path, "w", encoding="utf-8") as fp:
                    fp.write(text)
                print(text, flush=True)
                if item.get("result"):
                    item["result"]["exports"].append(out_path)
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                report(f"{os.path.basename(path)}：總體檢略過（{exc}）")

    if args.legibility:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].append(
                    _export_legibility(item["path"], cues, config, out_dir,
                                       base))
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"字幕可讀性健檢略過（{exc}）")

    if args.endscreen:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            if not item["ok"]:
                continue
            # 這項不需要字幕：沒字幕的片尾本身就是「死寂片尾」的徵兆。
            cues = (item.get("result") or {}).get("cues") or []
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].append(
                    _export_endscreen(item["path"], cues, config, out_dir,
                                      base))
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"片尾空間健檢略過（{exc}）")

    if args.beatcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            if not item["ok"]:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].append(
                    _export_beatcheck(item["path"], args.music, config,
                                      out_dir, base, report))
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"節拍分析略過（{exc}）")

    if args.multilang:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            try:
                for path in _export_multilang(
                        item["path"], cues, config, out_dir,
                        args.languages, report):
                    item["result"]["exports"].append(path)
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"多語字幕包略過（{exc}）")

    if args.termcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                for path in _export_termcheck(cues, config, out_dir, base,
                                              args.termfix):
                    item["result"]["exports"].append(path)
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"術語一致性檢查略過（{exc}）")

    if args.punctcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                for path in _export_punctcheck(cues, config, out_dir, base,
                                               args.punctfix):
                    item["result"]["exports"].append(path)
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"標點規範健檢略過（{exc}）")

    if args.sponsorcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            try:
                item["result"]["exports"].append(
                    _export_sponsorcheck(item["path"], cues, config,
                                         out_dir, base))
            except (RuntimeError, ValueError) as exc:
                report(f"{os.path.basename(item['path'])}："
                       f"工商揭露健檢略過（{exc}）")

    if args.hookcheck:
        automation = config.get("automation", {})
        out_dir_override = (automation.get("output_dir") or "").strip()
        for item in results:
            cues = (item.get("result") or {}).get("cues") if item["ok"] else None
            if not cues:
                continue
            out_dir = out_dir_override or os.path.dirname(
                os.path.abspath(item["path"]))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(item["path"]))[0]
            item["result"]["exports"].append(
                _export_hookcheck(cues, config, out_dir, base))

    # 總結報告。
    lines = []
    failed = 0
    for item in results:
        if item["ok"]:
            outputs = list(item["result"]["exports"])
            if item["result"]["burned"]:
                outputs.append(item["result"]["burned"])
            lines.append(f"✔ {item['path']}")
            lines.extend(f"    → {path}" for path in outputs)
        else:
            failed += 1
            lines.append(f"✘ {item['path']}")
            # 翻譯成「原因＋解法」，取代原始技術訊息。
            lines.extend(f"    {line}"
                         for line in format_error_text(
                             item["error"]).splitlines())
    total = len(results)
    summary = f"共 {total} 個檔案，成功 {total - failed}、失敗 {failed}。"

    print("\n===== 執行結果 =====")
    for line in lines:
        print(line)
    print(summary)

    # 打包成無 console 的 exe 時（例如把檔案拖到 exe 圖示上執行），
    # 文字輸出不可見，改以視窗回報結果。
    if getattr(sys, "frozen", False):
        _show_result_window(summary, lines, failed)
    return 1 if failed else 0


def _export_audiocheck(path: str, config: dict, out_dir: str,
                       base: str) -> str:
    """對單檔跑音訊健檢並輸出報告文字檔，回傳報告路徑。"""
    result = run_audio_check(path, config)
    text = format_report(result, os.path.basename(path))
    check_path = unique_path(os.path.join(out_dir, f"{base}_音訊健檢.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_subcheck(cues: list, config: dict, out_dir: str, base: str) -> str:
    """對字幕清單跑閱讀速度／行數健檢並輸出報告文字檔，回傳報告路徑。"""
    result = analyze_cues(cues, resolve_subcheck_settings(config))
    text = format_subtitle_report(result)
    check_path = unique_path(os.path.join(out_dir, f"{base}_字幕健檢.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _run_publishcheck(text_path: str, tags: str, config: dict,
                      report, media_path: str = "") -> list:
    """
    發佈資訊健檢：第一行當標題、其餘當說明欄。

    回傳與其他批次模式同構的結果清單，供總結報告統一列印。
    """
    label = f"發佈資訊健檢（{os.path.basename(text_path)}）"
    try:
        report("讀取發佈資訊…", 0.0)
        with open(text_path, "r", encoding="utf-8") as fp:
            raw = fp.read()
        lines = raw.splitlines()
        title = lines[0].strip() if lines else ""
        description = "\n".join(lines[1:])

        report("檢查各項上限…", 0.4)
        settings = resolve_publishcheck_settings(config)
        result = analyze_publish(title, description, tags or "", settings)
        text = format_publish_report(result, settings)

        # 上限檢查（會不會被系統拒絕）之外，再看說明欄的**結構**寫得對不對。
        # 影片長度只用來判斷「長到該有章節了嗎」，沒給媒體檔就跳過那一項。
        report("檢查說明欄結構…", 0.7)
        duration = 0.0
        if media_path:
            try:
                duration = probe_duration(media_path)
            except Exception:
                duration = 0.0
        desc_settings = resolve_desccheck_settings(config)
        desc_result = analyze_description(description, duration, config)
        text = text + "\n\n" + format_desc_report(desc_result, desc_settings)
        print(text, flush=True)

        automation = config.get("automation", {})
        out_dir = (automation.get("output_dir") or "").strip() \
            or os.path.dirname(os.path.abspath(text_path))
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(text_path))[0]
        out_path = unique_path(os.path.join(out_dir, f"{base}_發佈健檢.txt"))
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        report("完成", 1.0)
        return [{"path": label, "ok": True, "error": None,
                 "result": {"exports": [out_path], "burned": None,
                            "cues": []}}]
    except Exception as exc:
        report(f"失敗：{exc}", 1.0)
        return [{"path": label, "ok": False, "result": None,
                 "error": str(exc)}]


def _run_thumbcheck(files: list, config: dict, report) -> list:
    """
    封面健檢：檢查一或多張封面圖，多張時依分數排序。

    回傳與其他批次模式同構的結果清單（單一項目代表整批），供總結報告
    統一列印。
    """
    label = f"封面健檢（{len(files)} 張）"
    try:
        def progress(ratio, message):
            report(message, ratio)

        settings = resolve_thumbcheck_settings(config)
        results = rank_thumbnails(files, config, progress_cb=progress)
        parts = [format_thumb_report(r, settings) for r in results]
        if len(results) > 1:
            parts.append(format_ranking_report(results, settings))
        text = "\n\n".join(parts)
        print(text, flush=True)

        automation = config.get("automation", {})
        out_dir = (automation.get("output_dir") or "").strip() \
            or os.path.dirname(os.path.abspath(files[0]))
        os.makedirs(out_dir, exist_ok=True)
        out_path = unique_path(os.path.join(out_dir, "封面健檢.txt"))
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return [{"path": label, "ok": True, "error": None,
                 "result": {"exports": [out_path], "burned": None,
                            "cues": []}}]
    except Exception as exc:
        report(f"失敗：{exc}", 1.0)
        return [{"path": label, "ok": False, "result": None,
                 "error": str(exc)}]


def _run_chaptercheck(media_path: str, chapter_path: str, config: dict,
                      report, do_fix: bool = False) -> list:
    """
    YouTube 章節健檢：檢查一份章節文字是否符合章節顯示規則。

    回傳與其他批次模式同構的結果清單，供總結報告統一列印。
    """
    label = f"章節健檢（{os.path.basename(chapter_path)}）"
    try:
        report("讀取章節文字…", 0.0)
        with open(chapter_path, "r", encoding="utf-8") as fp:
            raw = fp.read()
        settings = resolve_chaptercheck_settings(config)
        chapters, errors = parse_chapters(raw)

        report("取得影片長度…", 0.3)
        try:
            duration = probe_duration(media_path)
        except Exception:
            # 取不到長度不該讓整個健檢失敗，只是最後一章無法判斷長度。
            duration = None

        report("檢查章節規則…", 0.6)
        result = validate_chapters(chapters, duration, settings, errors)
        text = format_chapter_report(result, chapters=chapters)
        print(text, flush=True)

        automation = config.get("automation", {})
        out_dir = (automation.get("output_dir") or "").strip() \
            or os.path.dirname(os.path.abspath(chapter_path))
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(chapter_path))[0]
        out_path = unique_path(os.path.join(out_dir, f"{base}_章節健檢.txt"))
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        exports = [out_path]

        if do_fix and not result["ok"]:
            fixed, changes = fix_chapters(chapters, duration, settings,
                                          parse_errors=errors)
            after = validate_chapters(fixed, duration, settings)
            fixed_text = format_chapters_text(fixed)
            fix_path = unique_path(
                os.path.join(out_dir, f"{base}_章節修正.txt"))
            with open(fix_path, "w", encoding="utf-8") as fp:
                fp.write(fixed_text + ("\n" if fixed_text else ""))
            exports.append(fix_path)
            print(format_chapter_report(after, chapters=fixed,
                                        changes=changes), flush=True)

        report("完成", 1.0)
        return [{"path": label, "ok": True, "error": None,
                 "result": {"exports": exports, "burned": None, "cues": []}}]
    except Exception as exc:
        report(f"失敗：{exc}", 1.0)
        return [{"path": label, "ok": False, "result": None,
                 "error": str(exc)}]


def _run_seriescheck(files: list, config: dict, report) -> list:
    """
    系列一致性檢查：整批比一批，產出單一份跨檔報告。

    回傳與其他批次模式同構的結果清單（單一項目代表整批），供總結報告
    統一列印。
    """
    def progress(ratio, message):
        report(message, ratio)

    label = f"系列一致性檢查（{len(files)} 支影片）"
    try:
        result = analyze_series(files, config, progress_cb=progress)
        text = format_series_report(result)
        print(text, flush=True)
        automation = config.get("automation", {})
        out_dir = (automation.get("output_dir") or "").strip() \
            or os.path.dirname(os.path.abspath(files[0]))
        os.makedirs(out_dir, exist_ok=True)
        out_path = unique_path(os.path.join(out_dir, "系列一致性檢查.txt"))
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return [{"path": label, "ok": True, "error": None,
                 "result": {"exports": [out_path], "burned": None,
                            "cues": []}}]
    except Exception as exc:
        report(f"失敗：{exc}", 1.0)
        return [{"path": label, "ok": False, "result": None,
                 "error": str(exc)}]


def _export_synccheck(media_path: str, cues: list, config: dict, out_dir: str,
                      base: str, formats: list, do_fix: bool) -> list:
    """
    對單檔跑字幕與語音同步檢查，輸出報告；do_fix 時另存校正後的字幕。

    回傳輸出路徑清單。無音訊軌等無法檢查的情況由呼叫端攔截例外處理。
    """
    result = analyze_sync(media_path, cues, resolve_subsync_settings(config))
    text = format_sync_report(result)
    report_path = unique_path(os.path.join(out_dir, f"{base}_同步檢查.txt"))
    with open(report_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    exports = [report_path]

    if do_fix and result["kind"] in ("offset", "drift"):
        fixed = apply_sync_correction(cues, result["scale"], result["offset"])
        style = config.get("subtitle_style", {})
        for ext in formats or [".srt"]:
            out_path = unique_path(os.path.join(out_dir, f"{base}_同步校正{ext}"))
            export(fixed, out_path, style)
            exports.append(out_path)
    return exports


def _export_adcheck(cues: list, config: dict, out_dir: str, base: str) -> str:
    """對字幕清單跑廣告友善度自查並輸出報告文字檔，回傳報告路徑。"""
    result = scan_cues(cues, resolve_adfriendly_settings(config))
    text = format_adfriendly_report(result)
    check_path = unique_path(os.path.join(out_dir, f"{base}_廣告友善度.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_legibility(media_path: str, cues: list, config: dict,
                       out_dir: str, base: str) -> str:
    """對素材與字幕跑可讀性健檢並輸出報告文字檔，回傳報告路徑。"""
    settings = resolve_legibility_settings(config)
    style = config.get("subtitle_style", {})
    result = analyze_legibility(media_path, cues, style, config)
    text = format_legibility_report(result, settings)
    check_path = unique_path(os.path.join(out_dir, f"{base}_字幕可讀性.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_endscreen(media_path: str, cues: list, config: dict,
                      out_dir: str, base: str) -> str:
    """對素材跑片尾空間健檢並輸出報告文字檔，回傳報告路徑。"""
    settings = resolve_endscreen_settings(config)
    result = analyze_endscreen(media_path, cues, config)
    text = format_endscreen_report(result, settings)
    check_path = unique_path(os.path.join(out_dir, f"{base}_片尾空間.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_beatcheck(media_path: str, music_path, config: dict,
                      out_dir: str, base: str, report) -> str:
    """
    分析配樂節拍並把影片剪點對齊過去，輸出報告文字檔，回傳報告路徑。

    節拍偵測與對齊都交給 beatsync；畫面剪接點重用既有的
    pacing.detect_scene_changes，本函式不重新實作任何一邊。
    """
    from subtitle.media import has_video_stream
    from subtitle.pacing import detect_scene_changes, resolve_pacing_settings

    settings = resolve_beatsync_settings(config)
    target = music_path or media_path
    report(f"分析 {os.path.basename(target)} 的節拍…")
    result = analyze_beats(target, config)

    snapped = None
    # 有指定配樂、而且位置參數本身是影片時，才去掃畫面剪接點來對齊。
    if result["bpm"] and music_path and has_video_stream(media_path):
        report("掃描畫面剪接點…")
        cuts = detect_scene_changes(media_path, resolve_pacing_settings(config))
        if cuts:
            snapped = snap_times(cuts, result["beats"], settings["max_shift"])

    text = format_beat_report(result, snapped, settings)
    print(text, flush=True)
    check_path = unique_path(os.path.join(out_dir, f"{base}_節拍分析.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return check_path


def _export_multilang(media_path: str, cues: list, config: dict,
                      out_dir: str, languages_override, report) -> list:
    """
    把母帶字幕翻成多國語言，各自輸出單語 SRT，回傳產生的檔案路徑清單。

    翻譯本身呼叫既有的 translator（透過 multilang），本函式只負責
    挑語言、寫檔與回報；某一個語言失敗不會中斷其他語言。
    """
    from subtitle.exporter import export

    settings = resolve_multilang_settings(config)
    source_language = (config.get("transcription", {})
                       .get("language", "") or "").strip()
    # 有給 --languages 就以它為準，**即使是空字串**——使用者明講了空清單，
    # 靜靜退回設定檔的預設語言等於擅自替他決定要翻哪幾種、還要付 API 費用。
    languages = parse_languages(
        settings["languages"] if languages_override is None
        else languages_override,
        source_language=source_language,
        skip_source=settings["skip_source"])
    if not languages:
        print(format_pack_report({}, [], {}, {}), flush=True)
        return []

    api_key = (config.get("transcription", {}).get("api_key", "") or "").strip()
    if not api_key:
        raise RuntimeError(
            "多語字幕包需要 OpenAI API 金鑰（於「轉寫設定」填入）。")
    batch_size = resolve_translate_settings(config)["batch_size"]

    pack, paths, failed = {}, {}, {}
    for language in languages:
        try:
            report(f"翻譯成 {language}...")
            one = build_language_pack(
                cues, [language], api_key, batch_size=batch_size,
                dedupe=settings["dedupe"])
            pack[language] = one[language]
            target = pack_path(media_path, language, out_dir)
            export(pack[language], target, config.get("subtitle_style"))
            paths[language] = target
        except Exception as exc:      # 單一語言失敗不影響其他語言。
            failed[language] = str(exc)

    print(format_pack_report(pack, languages, paths, failed), flush=True)
    return list(paths.values())


def _export_shorts(media_path: str, items: list, words: list,
                   duration: float, config: dict, out_dir: str, base: str,
                   count_override: Optional[int], report, prefix: str = ""
                   ) -> list:
    """
    規劃並輸出多支直式短片，回傳產生的檔案路徑清單。

    選段完全交給 clipplan（沿講話段落邊界擴張、彼此不重疊、長度落在
    平台可用範圍），實際裁切重用既有的 shorts.cut_vertical_clip——
    本函式不重新實作任何一邊。
    """
    plan_settings = resolve_clipplan_settings(config)
    if count_override:
        plan_settings["count"] = max(int(count_override), 1)
    clips = plan_clips(items, plan_settings, media_duration=duration)

    text = format_clip_plan_report(clips, plan_settings)
    print(text, flush=True)
    plan_path = unique_path(os.path.join(out_dir, f"{base}_短片選段.txt"))
    with open(plan_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    paths = [plan_path]
    if not clips:
        return paths

    shorts_settings = resolve_shorts_settings(config)
    style = config.get("subtitle_style", {})
    seg_cfg = config.get("segmentation", {})
    loudnorm_target = (DEFAULT_TARGET_LUFS
                       if shorts_settings["loudnorm"] else None)
    total = len(clips)
    for index, clip in enumerate(clips, start=1):
        report(f"{prefix}輸出短片 {index}/{total}"
               f"（{clip['duration']:.0f} 秒）...")
        # 字幕從逐字時間軸重建，時間軸由輸出流程平移到片段起點。
        cues = []
        if shorts_settings["burn_subtitles"] and words:
            clip_words = [w for w in words
                          if w["end"] > clip["start"] - 0.05
                          and w["start"] < clip["end"] + 0.05]
            if clip_words:
                cues = build_cues_from_words(clip_words, seg_cfg)
        output = unique_path(
            os.path.join(out_dir, f"{base}_短片{index:02d}.mp4"))
        cut_vertical_clip(
            media_path, clip["start"], clip["end"], output,
            mode=shorts_settings["mode"],
            focus_x=shorts_settings["focus_x"],
            style=style, cues=cues,
            loudnorm_target=loudnorm_target,
            safe_zone_enabled=shorts_settings["safe_zone_enabled"],
            safe_zone_top=shorts_settings["safe_zone_top"],
            safe_zone_bottom=shorts_settings["safe_zone_bottom"],
            safe_zone_side=shorts_settings["safe_zone_side"])
        paths.append(output)
    return paths


def _export_termcheck(cues: list, config: dict, out_dir: str, base: str,
                      do_fix: bool = False) -> list:
    """
    對字幕清單跑術語一致性檢查並輸出報告，回傳產生的檔案路徑清單。

    加上 --termfix 時另外輸出統一寫法後的 SRT；沒有可統一的項目時
    不會產生空檔案，只如實回報。
    """
    from subtitle.exporter import export

    settings = resolve_termcheck_settings(config)
    result = analyze_terms(cues, config)
    text = format_term_report(result, settings)
    paths = []
    check_path = unique_path(os.path.join(out_dir, f"{base}_術語一致性.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    paths.append(check_path)

    if do_fix:
        choices = build_fix_choices(result.get("groups") or [])
        if not choices:
            print("（沒有可以安全統一的詞，未輸出統一版字幕）", flush=True)
        else:
            fixed, count = apply_term_fixes(cues, choices)
            srt_path = unique_path(
                os.path.join(out_dir, f"{base}_術語統一.srt"))
            export(fixed, srt_path, config.get("subtitle_style"))
            print(f"（已統一 {count} 處寫法 → {srt_path}）", flush=True)
            paths.append(srt_path)
    return paths


def _export_punctcheck(cues: list, config: dict, out_dir: str, base: str,
                       do_fix: bool = False) -> list:
    """
    對字幕清單跑中文標點規範健檢並輸出報告，回傳產生的檔案路徑清單。

    加上 --punctfix 時另外輸出規範化後的 SRT；沒有任何一句需要更動時
    不會產生空檔案，只如實回報。
    """
    from subtitle.exporter import export

    settings = resolve_punctstyle_settings(config)
    result = analyze_punctuation(cues, config)
    text = format_punct_report(result, settings)
    paths = []
    check_path = unique_path(os.path.join(out_dir, f"{base}_標點規範.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    paths.append(check_path)

    if do_fix:
        fixed, count = apply_punct_style(cues, settings)
        if not count:
            print("（沒有需要規範化的標點，未輸出規範版字幕）", flush=True)
        else:
            srt_path = unique_path(
                os.path.join(out_dir, f"{base}_標點規範.srt"))
            export(fixed, srt_path, config.get("subtitle_style"))
            print(f"（已規範化 {count} 句 → {srt_path}）", flush=True)
            paths.append(srt_path)
    return paths


def _export_sponsorcheck(media_path: str, cues: list, config: dict,
                         out_dir: str, base: str) -> str:
    """對字幕清單跑工商揭露健檢並輸出報告文字檔，回傳報告路徑。"""
    settings = resolve_sponsorcheck_settings(config)
    # 佔比要拿實際片長來算：字幕通常在片尾音樂之前就結束，
    # 用字幕末尾當片長會把佔比算得偏高。
    result = analyze_sponsor(cues, probe_duration(media_path), config)
    text = format_sponsor_report(result, settings)
    check_path = unique_path(os.path.join(out_dir, f"{base}_工商揭露.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_hookcheck(cues: list, config: dict, out_dir: str,
                      base: str) -> str:
    """對字幕清單跑開場健檢並輸出報告文字檔，回傳報告路徑。"""
    settings = resolve_hookcheck_settings(config)
    result = analyze_hook(cues, settings)
    text = format_hook_report(result, settings)
    check_path = unique_path(os.path.join(out_dir, f"{base}_開場健檢.txt"))
    with open(check_path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text, flush=True)
    return check_path


def _export_jumpcut(path: str, cues: list, config: dict, out_dir: str,
                    formats: list, report) -> list:
    """
    對單檔跑自動跳剪：輸出跳剪版影片＋時間軸已對齊的字幕，回傳輸出路徑清單。

    找不到可跳剪的停頓（節奏已經很緊湊）或觸發安全防呆時皆拋出例外，
    由呼叫端決定如何回報（單檔失敗不中斷整批）。
    """
    base = os.path.splitext(os.path.basename(path))[0]
    video_out = unique_path(os.path.join(
        out_dir, os.path.basename(suggest_jumpcut_output_path(path))))
    report(f"{os.path.basename(path)}：正在偵測停頓並跳剪...")
    result = apply_jumpcut(path, cues, video_out,
                           settings=resolve_jumpcut_settings(config))
    report(format_jumpcut_report(result))
    outputs = [video_out]
    for ext in (formats or [".srt"]):
        target = unique_path(os.path.join(out_dir, f"{base}_跳剪{ext}"))
        export(result["cues"], target, style=config.get("subtitle_style"))
        outputs.append(target)
    return outputs


def _export_retakes(path: str, cues: list, found: list, config: dict,
                    out_dir: str, formats: list, report) -> list:
    """
    對單檔剪掉全部偵測到的重複片段：輸出去重複版影片＋對齊後的字幕。

    找不到 ffmpeg、來源檔或觸發安全防呆時皆拋出例外，由呼叫端決定如何
    回報（單檔失敗不中斷整批）。
    """
    base = os.path.splitext(os.path.basename(path))[0]
    video_out = unique_path(os.path.join(
        out_dir, os.path.basename(suggest_retakes_output_path(path))))
    report(f"{os.path.basename(path)}：正在剪掉 {len(found)} 處重複片段...")
    result = apply_retake_removal(path, cues, found, video_out,
                                  settings=resolve_retake_settings(config))
    report(format_retake_removal_report(result))
    outputs = [video_out]
    for ext in (formats or [".srt"]):
        target = unique_path(os.path.join(out_dir, f"{base}_去重複{ext}"))
        export(result["cues"], target, style=config.get("subtitle_style"))
        outputs.append(target)
    return outputs


def _export_thumbnails(path: str, items, duration: float, config: dict,
                       out_dir: str, base: str) -> list:
    """對單檔擷取封面候選圖，回傳輸出路徑清單。"""
    results = generate_thumbnails(
        path, items, duration,
        output_paths=lambda rank: unique_path(
            os.path.join(out_dir, f"{base}_封面{rank:02d}.png")),
        settings=resolve_thumbnail_settings(config))
    return [item["path"] for item in results]


def _run_subs_batch(media_path: str, subs_path: str, config: dict,
                    report) -> list:
    """
    --subs 模式：讀入既有字幕檔，跳過轉錄，直接沿用自動化匯出／燒錄設定。

    回傳結構與 run_batch 相同（單一元素的清單），供 main() 的總結報告共用。
    """
    try:
        if not os.path.exists(media_path):
            raise FileNotFoundError(f"找不到檔案：{media_path}")
        automation = config.get("automation", {})
        if not enabled_export_formats(automation) \
                and not automation.get("burn_video"):
            raise ValueError("自動化輸出未勾選任何項目（匯出格式或燒錄影片）。")
        report(f"正在讀取字幕檔：{os.path.basename(subs_path)}...")
        loaded = load_subtitle_file(subs_path)
        cues = loaded["cues"]
        if loaded["skipped"]:
            report(f"已略過 {loaded['skipped']} 段無法解析的字幕區塊。")
        report(f"已讀入 {len(cues)} 句字幕（編碼：{loaded['encoding']}），"
              "開始匯出／燒錄...")
        exports, burned = export_and_burn(cues, media_path, config, report)
        report("完成", 1.0)
        return [{
            "path": media_path, "ok": True, "error": None,
            "result": {"cues": cues, "exports": exports, "burned": burned},
        }]
    except Exception as exc:  # 與其他批次模式一致：失敗時仍回傳同構結果。
        report(f"失敗：{exc}", 1.0)
        return [{"path": media_path, "ok": False, "result": None,
                 "error": str(exc)}]


def _run_tools_batch(files: list, config: dict, report,
                     do_audiocheck: bool = False,
                     do_thumbnails: bool = False,
                     do_audiofix: bool = False,
                     do_branding: bool = False,
                     do_videocheck: bool = False,
                     do_volumecheck: bool = False,
                     do_volumefix: bool = False,
                     do_audiovis: bool = False,
                     do_colorcheck: bool = False,
                     do_pacecheck: bool = False) -> list:
    """輕量工具批次（免轉錄）：音訊健檢與封面候選，回傳與 run_batch 同構的結果。"""
    automation = config.get("automation", {})
    results = []
    total = len(files)
    for index, path in enumerate(files):
        prefix = (f"[{index + 1}/{total}] {os.path.basename(path)}："
                  if total > 1 else "")
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到檔案：{path}")
            out_dir = (automation.get("output_dir") or "").strip() \
                or os.path.dirname(os.path.abspath(path))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            exports = []
            if do_audiocheck:
                report(f"{prefix}音訊健檢中...")
                exports.append(_export_audiocheck(path, config, out_dir, base))
            if do_videocheck:
                report(f"{prefix}影片畫質健檢中...")
                vc_text = format_video_report(run_video_check(path, config))
                if vc_text:
                    vc_path = unique_path(os.path.join(
                        out_dir, f"{base}_影片健檢.txt"))
                    with open(vc_path, "w", encoding="utf-8") as fp:
                        fp.write(vc_text)
                    print(vc_text, flush=True)
                    exports.append(vc_path)
                else:
                    report(f"{prefix}無影像串流，略過影片健檢。")
            if do_pacecheck:
                report(f"{prefix}分析剪輯節奏中...")
                try:
                    pace_result = analyze_pacing(path, config)
                    pace_text = format_pacing_report(
                        pace_result, resolve_pacing_settings(config))
                    pace_path = unique_path(os.path.join(
                        out_dir, f"{base}_剪輯節奏.txt"))
                    with open(pace_path, "w", encoding="utf-8") as fp:
                        fp.write(pace_text)
                    print(pace_text, flush=True)
                    exports.append(pace_path)
                except ValueError as exc:
                    report(f"{prefix}剪輯節奏健檢略過（{exc}）")
            if do_colorcheck:
                report(f"{prefix}分析畫面曝光與色調中...")
                try:
                    color_result = analyze_color(
                        path, resolve_colorcheck_settings(config))
                    color_text = format_color_report(color_result)
                    color_path = unique_path(os.path.join(
                        out_dir, f"{base}_色彩健檢.txt"))
                    with open(color_path, "w", encoding="utf-8") as fp:
                        fp.write(color_text)
                    print(color_text, flush=True)
                    exports.append(color_path)
                except ValueError:
                    report(f"{prefix}無影像串流，略過色彩健檢。")
            if do_thumbnails:
                report(f"{prefix}擷取封面候選中（整片均勻取樣）...")
                exports.extend(_export_thumbnails(
                    path, None, probe_duration(path), config, out_dir, base))
            if do_audiofix:
                report(f"{prefix}輸出音訊修復版中...")
                fix_out = unique_path(os.path.join(
                    out_dir, os.path.basename(suggest_output_path(path))))
                fix_audio(path, fix_out,
                          settings=resolve_audiofix_settings(config))
                exports.append(fix_out)
            if do_volumecheck or do_volumefix:
                report(f"{prefix}分析分段音量一致性中...")
                vol_result = analyze_volume_consistency(
                    path, resolve_volume_consistency_settings(config))
                if do_volumecheck:
                    vol_text = format_volume_consistency_report(vol_result)
                    vol_path = unique_path(os.path.join(
                        out_dir, f"{base}_音量一致性.txt"))
                    with open(vol_path, "w", encoding="utf-8") as fp:
                        fp.write(vol_text)
                    print(vol_text, flush=True)
                    exports.append(vol_path)
                if do_volumefix:
                    if vol_result.get("issues"):
                        report(f"{prefix}正在拉平 "
                              f"{len(vol_result['issues'])} 段音量落差...")
                        vol_out = unique_path(os.path.join(
                            out_dir, os.path.basename(
                                suggest_volume_output_path(path))))
                        fix_volume_consistency(path, vol_result, vol_out)
                        exports.append(vol_out)
                    else:
                        report(f"{prefix}未偵測到音量落差過大的段落，"
                              "略過音量拉平。")
            if do_branding:
                branding_settings = resolve_branding_settings(config)
                if (branding_settings["intro_path"]
                        or branding_settings["outro_path"]
                        or branding_settings["watermark_path"]):
                    report(f"{prefix}套用品牌套版中...")
                    brand_out = unique_path(os.path.join(
                        out_dir, os.path.basename(
                            suggest_branding_output_path(path))))
                    apply_branding(path, brand_out, settings=branding_settings)
                    exports.append(brand_out)
                else:
                    report(f"{prefix}尚未設定片頭／片尾／浮水印，略過品牌套版。")
            if do_audiovis:
                report(f"{prefix}正在產生視覺化影片...")
                vis_out = unique_path(os.path.join(
                    out_dir, os.path.basename(
                        suggest_audiovis_output_path(path))))
                render_audio_video(
                    path, vis_out,
                    settings=resolve_audiovis_settings(config))
                exports.append(vis_out)
            report(f"{prefix}完成", (index + 1) / total)
            results.append({
                "path": path, "ok": True, "error": None,
                "result": {"exports": exports, "burned": None, "cues": []},
            })
        except Exception as exc:  # 單檔失敗不中斷批次。
            results.append(
                {"path": path, "ok": False, "result": None, "error": str(exc)})
            report(f"{prefix}失敗：{exc}", (index + 1) / total)
    return results


def _run_review_batch(files: list, config: dict, report,
                      with_audiocheck: bool = False,
                      with_thumbnails: bool = False,
                      with_shorts: bool = False,
                      shorts_count: Optional[int] = None) -> list:
    """審片模式批次：逐檔轉錄、分析並輸出審片清單 CSV，回傳與 run_batch 同構的結果。"""
    automation = config.get("automation", {})
    settings = resolve_settings(config)
    results = []
    analyzed = []   # (素材名稱, items)——多檔時輸出跨檔彙總用
    last_out_dir = None
    total = len(files)
    for index, path in enumerate(files):
        prefix = f"[{index + 1}/{total}] {os.path.basename(path)}：" if total > 1 else ""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到檔案：{path}")
            report(f"{prefix}轉錄並分析中...", index / total if total > 1 else None)
            words = transcribe(path, config)
            duration = probe_duration(path)
            items = analyze(
                words, media_duration=duration,
                loudness=compute_loudness(
                    path, voice_band=settings["voice_band"]),
                settings=settings)
            out_dir = (automation.get("output_dir") or "").strip() \
                or os.path.dirname(os.path.abspath(path))
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            csv_path = unique_path(os.path.join(out_dir, f"{base}_審片清單.csv"))
            export_csv(items, csv_path)
            chapters = build_chapters(
                items,
                min_chapter_seconds=settings["chapter_min_seconds"],
                break_gap=settings["silence_gap"])
            html_path = unique_path(os.path.join(out_dir, f"{base}_審片報告.html"))
            export_html_report(items, html_path, source_name=os.path.basename(path),
                               media_duration=duration, chapters=chapters)
            # 發佈包：建議標題＋描述草稿＋標籤，上傳時直接取用。
            pack_path = unique_path(os.path.join(out_dir, f"{base}_發佈包.txt"))
            with open(pack_path, "w", encoding="utf-8") as fp:
                fp.write(build_publish_pack(
                    items, settings=resolve_publish_settings(config),
                    chapters=chapters, source_name=os.path.basename(path),
                    extra_words=settings["extra_excite_words"],
                    ad_breaks=suggest_ad_breaks(
                        items, duration,
                        settings=resolve_adbreak_settings(config))))
            exports = [csv_path, html_path, pack_path]
            if with_audiocheck:
                report(f"{prefix}音訊健檢中...")
                exports.append(_export_audiocheck(path, config, out_dir, base))
            if with_thumbnails:
                report(f"{prefix}擷取封面候選中（優先精彩段落）...")
                exports.extend(_export_thumbnails(
                    path, items, duration, config, out_dir, base))
            if with_shorts:
                exports.extend(_export_shorts(
                    path, items, words, duration, config, out_dir, base,
                    shorts_count, report, prefix))
            dropped = sum(1 for item in items if not item["keep"])
            report(f"{prefix}分析完成，共 {len(items)} 段（建議捨棄 {dropped} 段）",
                   (index + 1) / total)
            analyzed.append((os.path.basename(path), items))
            last_out_dir = out_dir
            results.append({
                "path": path, "ok": True, "error": None,
                "result": {"exports": exports, "burned": None, "cues": []},
            })
        except Exception as exc:  # 單檔失敗不中斷批次。
            results.append(
                {"path": path, "ok": False, "result": None, "error": str(exc)})
            report(f"{prefix}失敗：{exc}", (index + 1) / total)

    # 多檔審片時另輸出跨檔彙總：整批素材的精彩片段 Top N 一目瞭然。
    if len(analyzed) >= 2 and last_out_dir:
        try:
            top_n = settings["batch_top_n"]
            summary_csv = unique_path(
                os.path.join(last_out_dir, "審片彙總_精彩TopN.csv"))
            export_batch_csv(collect_highlights(analyzed, top_n), summary_csv)
            summary_html = unique_path(
                os.path.join(last_out_dir, "審片彙總.html"))
            export_batch_html(analyzed, summary_html, top_n)
            report(f"已輸出跨檔彙總（{len(analyzed)} 支素材、"
                   f"精彩片段前 {top_n} 段）：{summary_html}")
            for item in results:
                if item["ok"]:
                    item["result"]["exports"].extend(
                        [summary_csv, summary_html])
                    break
        except OSError as exc:
            report(f"跨檔彙總輸出失敗（不影響個別報告）：{exc}")
    return results


def _show_result_window(summary: str, lines: list, failed: int) -> None:
    """以訊息視窗顯示批次結果（無 console 環境用）；失敗時不中斷流程。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        show = messagebox.showwarning if failed else messagebox.showinfo
        show("批次處理結果", summary + "\n\n" + "\n".join(lines))
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
