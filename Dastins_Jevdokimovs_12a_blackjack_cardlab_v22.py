"""
CardLab - Blackjack Simulator  (v21)
Changes in this version:
  • Excel export rewritten with ZERO external dependencies — uses only Python's
    built-in zipfile module to write a valid .xlsx directly as compressed XML.
    No pip install needed. Works on any machine with Python 3.8+.
  • Full translation coverage — every label, button and UI text now updates
    live when language is switched between LV ↔ EN (Settings labels, checkbox,
    speed label, tab buttons, stats columns, auto tab, save buttons all covered)
  • SQLite save, mouse-wheel fix, stats column width fix from v19 retained.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import random
from typing import List
import os
import datetime
import threading
import queue
import multiprocessing as mp
import math
import sqlite3
import zipfile, xml.etree.ElementTree as _ET


def _get_downloads_dir():
    """Return the user's Downloads folder (cross-platform)."""
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(dl):
        dl = os.path.expanduser("~")   # fallback to home
    return dl


SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE WORKER HELPERS  (module-level — required for multiprocessing pickle)
# ──────────────────────────────────────────────────────────────────────────────

def _build_deck_tuples(num_decks: int):
    """Build a deck as a list of (value, is_ace) tuples — no Card objects."""
    out = []
    for _ in range(num_decks):
        for s in SUITS:
            for r in RANKS:
                v = 11 if r == "A" else (10 if r in "KQJ" else int(r))
                out.append((v, r == "A"))
    return out


def _build_strategy_arrays():
    """
    Precompute hard & soft strategy as flat int arrays.
    Index = total * 12 + upcard  (upcards 2-11)
    Actions: 0=Hit, 1=Stand, 2=Double
    """
    hard = [0] * (22 * 12)
    soft = [0] * (22 * 12)
    for total in range(5, 22):
        for up in range(2, 12):
            # Hard
            if total >= 17:
                a = 1
            elif 13 <= total <= 16:
                a = 1 if 2 <= up <= 6 else 0
            elif total == 12:
                a = 1 if 4 <= up <= 6 else 0
            elif total == 11:
                a = 2
            elif total == 10:
                a = 2 if 2 <= up <= 9 else 0
            elif total == 9:
                a = 2 if 3 <= up <= 6 else 0
            else:
                a = 0
            hard[total * 12 + up] = a
            # Soft
            if total >= 20:
                sa = 1
            elif total == 19:
                sa = 2 if up == 6 else 1
            elif total == 18:
                sa = 0 if up >= 9 else (2 if 3 <= up <= 6 else 1)
            elif total == 17:
                sa = 2 if 3 <= up <= 6 else 0
            elif total in (15, 16):
                sa = 2 if 4 <= up <= 6 else 0
            elif total in (13, 14):
                sa = 2 if 5 <= up <= 6 else 0
            else:
                sa = 0
            soft[total * 12 + up] = sa
    return hard, soft


# Pre-built at import time — subprocesses inherit these via fork/spawn
_DECK_TUPLES_CACHE: dict = {}   # num_decks → list of tuples
_HARD_ARR, _SOFT_ARR = _build_strategy_arrays()


def _get_deck_template(num_decks: int):
    if num_decks not in _DECK_TUPLES_CACHE:
        _DECK_TUPLES_CACHE[num_decks] = _build_deck_tuples(num_decks)
    return _DECK_TUPLES_CACHE[num_decks]


def _mp_worker(args):
    """
    Multiprocessing worker — runs a chunk of games with zero UI interaction.
    Returns (player_wins, dealer_wins, bot_wins_list, draws, games_done).

    Uses:
      • Tuple deck — avoids Card object overhead
      • Single shared working array with position tracking — reshuffle only
        every ~25 games (for 250 decks) instead of copy+shuffle every game
      • Flat int arrays for strategy — no dict lookups in inner loop
      • Inline hand-value — no function call overhead
    """
    (total_games, num_decks, num_bots, human,
     bot_hard_arrs, bot_soft_arrs, stop_val) = args

    template = _get_deck_template(num_decks)
    total_cards = len(template)
    # Worst case cards per game: 7 (dealer) + 7 (player) + 7*100 (bots) = 714
    BUFFER = max(800, num_bots * 8 + 50)

    working = list(template)
    random.shuffle(working)
    pos = 0

    pw = dw = draws = 0
    bw = [0] * num_bots
    # per-player accumulation: [win, lose, draw]
    player_counts = [0, 0, 0]
    bot_counts = [[0, 0, 0] for _ in range(num_bots)]

    HARD = _HARD_ARR
    SOFT = _SOFT_ARR

    for game in range(total_games):
        if stop_val[0]:
            break
        if pos + BUFFER > total_cards:
            random.shuffle(working)
            pos = 0

        p = pos
        d0 = working[p];  d1 = working[p+1];  p += 2
        if human:
            pc = [working[p], working[p+1]]; p += 2
        else:
            pc = None

        bots = []
        for i in range(num_bots):
            bots.append([working[p], working[p+1]]); p += 2
        pos = p

        # Upcard value (cap face cards at 10, ace = 11)
        up_raw = d1[0]
        up = up_raw if up_raw <= 11 else 10

        # ── Check dealer blackjack ──
        d_bj = (d0[0] + d1[0] == 21 and d0[1] != d1[1] or
                (d0[0] == 11 and d1[0] == 10) or (d0[0] == 10 and d1[0] == 11))
        # Accurate BJ check: 2 cards totalling 21
        dt_init = d0[0] + d1[0]
        da_init = int(d0[1]) + int(d1[1])
        _t = dt_init; _a = da_init
        while _t > 21 and _a: _t -= 10; _a -= 1
        d_bj = (_t == 21)

        if d_bj:
            if pc is not None:
                pt = pc[0][0] + pc[1][0]
                pa = int(pc[0][1]) + int(pc[1][1])
                while pt > 21 and pa: pt -= 10; pa -= 1
                if pt == 21:
                    draws += 1; player_counts[2] += 1
                else:
                    dw += 1; player_counts[1] += 1
            for i in range(num_bots):
                bt = bots[i][0][0] + bots[i][1][0]
                ba = int(bots[i][0][1]) + int(bots[i][1][1])
                while bt > 21 and ba: bt -= 10; ba -= 1
                if bt == 21:
                    draws += 1; bot_counts[i][2] += 1
                else:
                    dw += 1; bot_counts[i][1] += 1
        else:
            # ── Player plays basic strategy ──
            if pc is not None:
                tv = pc[0][0]+pc[1][0]; ta = int(pc[0][1])+int(pc[1][1])
                while tv > 21 and ta: tv -= 10; ta -= 1
                is_soft = ta > 0 and tv <= 21
                while tv < 21:
                    idx = min(max(tv, 5), 21) * 12 + up
                    act = (SOFT if is_soft else HARD)[idx]
                    if act == 1: break
                    c = working[pos]; pos += 1; pc.append(c)
                    tv += c[0]
                    if c[1]: ta += 1
                    while tv > 21 and ta: tv -= 10; ta -= 1
                    is_soft = ta > 0 and tv <= 21
                    if act == 2: break
                pv = tv
            else:
                pv = -1

            # ── Bots play their strategies ──
            bvals = []
            for i in range(num_bots):
                bc = bots[i]
                bh = bot_hard_arrs[i] if i < len(bot_hard_arrs) else HARD
                bs = bot_soft_arrs[i] if i < len(bot_soft_arrs) else SOFT
                tv = bc[0][0]+bc[1][0]; ta = int(bc[0][1])+int(bc[1][1])
                while tv > 21 and ta: tv -= 10; ta -= 1
                is_soft = ta > 0 and tv <= 21
                while tv < 21:
                    idx = min(max(tv, 5), 21) * 12 + up
                    act = (bs if is_soft else bh)[idx]
                    if act == 1: break
                    c = working[pos]; pos += 1; bc.append(c)
                    tv += c[0]
                    if c[1]: ta += 1
                    while tv > 21 and ta: tv -= 10; ta -= 1
                    is_soft = ta > 0 and tv <= 21
                    if act == 2: break
                bvals.append(tv)

            # ── Dealer plays ──
            dt = dt_init; da = da_init
            while dt > 21 and da: dt -= 10; da -= 1
            while dt < 17:
                c = working[pos]; pos += 1
                dt += c[0]
                if c[1]: da += 1
                while dt > 21 and da: dt -= 10; da -= 1

            # ── Outcomes ──
            if pc is not None:
                if pv > 21:   dw += 1; player_counts[1] += 1
                elif dt > 21 or pv > dt: pw += 1; player_counts[0] += 1
                elif pv < dt: dw += 1; player_counts[1] += 1
                else:         draws += 1; player_counts[2] += 1

            for i, bv in enumerate(bvals):
                if bv > 21:   dw += 1; bot_counts[i][1] += 1
                elif dt > 21 or bv > dt: bw[i] += 1; bot_counts[i][0] += 1
                elif bv < dt: dw += 1; bot_counts[i][1] += 1
                else:         draws += 1; bot_counts[i][2] += 1

    return pw, dw, list(bw), draws, game + 1, player_counts, bot_counts


def _strategy_to_arrays(strategy):
    """Convert a BotStrategy object to flat int arrays for subprocess use."""
    hard = [0] * (22 * 12)
    soft = [0] * (22 * 12)
    act_map = {'H': 0, 'S': 1, 'D': 2, 'R': 0}
    for total, row in strategy.hard.items():
        for up, act in row.items():
            if 2 <= up <= 11:
                hard[total * 12 + up] = act_map.get(act, 0)
    for total, row in strategy.soft.items():
        for up, act in row.items():
            if 2 <= up <= 11:
                soft[total * 12 + up] = act_map.get(act, 0)
    return hard, soft

# ──────────────────────────────────────────────────────────────────────────────
# LANGUAGE STRINGS
# ──────────────────────────────────────────────────────────────────────────────
LANG = {
    # ── Menu ──
    "menu_start":       {"lv": "▶   Sākt spēli",       "en": "▶   Start Game"},
    "menu_tutorial":    {"lv": "📖   Pamācība",          "en": "📖   Tutorial"},
    "menu_quit":        {"lv": "✕   Iziet",             "en": "✕   Quit"},
    "menu_subtitle":    {"lv": "Blackjack Simulator",   "en": "Blackjack Simulator"},

    # ── Top bar ──
    "exit_btn":         {"lv": "✕  Iziet",              "en": "✕  Exit"},

    # ── Tab names ──
    "tab_settings":     {"lv": "Iestat.",               "en": "Settings"},
    "tab_bots":         {"lv": "Boti",                  "en": "Bots"},
    "tab_stats":        {"lv": "Stats",                 "en": "Stats"},
    "tab_auto":         {"lv": "Auto",                  "en": "Auto"},

    # ── Settings tab ──
    "s_decks":          {"lv": "Kāršu kavu skaits  (maks. 250)",  "en": "Number of decks  (max 250)"},
    "s_bots":           {"lv": "Botu skaits  (maks. 100)",        "en": "Number of bots  (max 100)"},
    "s_your_name":      {"lv": "Tavs vārds",                      "en": "Your name"},
    "s_play_self":      {"lv": "Spēlēt pašam",                    "en": "Play yourself"},
    "s_anim_speed":     {"lv": "Animācijas ātrums",               "en": "Animation speed"},
    "s_restart":        {"lv": "🔄  Restartēt galdu",             "en": "🔄  Restart table"},
    "s_tutorial":       {"lv": "📖  Pamācība",                    "en": "📖  Tutorial"},
    "s_save_stats":     {"lv": "💾  Saglabāt .txt (Auto-replay)",  "en": "💾  Save .txt (Auto-replay)"},
    "s_save_sqlite":    {"lv": "🗄️  Saglabāt SQLite DB",          "en": "🗄️  Save to SQLite DB"},
    "s_save_excel":     {"lv": "📊  Saglabāt .xlsx (Auto-replay)", "en": "📊  Save .xlsx (Auto-replay)"},
    "d_sqlite_saved":   {"lv": "Saglabāts SQLite",                "en": "SQLite Saved"},
    "d_sqlite_msg":     {"lv": "SQLite datubāze saglabāta:\n",    "en": "SQLite database saved:\n"},
    "d_excel_saved":    {"lv": "Saglabāts Excel",                 "en": "Excel Saved"},
    "d_excel_msg":      {"lv": "Excel fails saglabāts:\n",        "en": "Excel file saved:\n"},
    "s_save_csv":       {"lv": "📋  Saglabāt .csv (Analīzei)",     "en": "📋  Save .csv (Analysis)"},
    "d_csv_saved":      {"lv": "Saglabāts CSV",                    "en": "CSV Saved"},
    "d_csv_msg":        {"lv": "CSV fails saglabāts:\n",           "en": "CSV file saved:\n"},
    "xl_summary":       {"lv": "Kopsavilkums",                    "en": "Summary"},
    "xl_gamelog":       {"lv": "Spēļu žurnāls",                   "en": "Game Log"},
    "xl_session":       {"lv": "Sesija",                          "en": "Session"},
    "xl_player":        {"lv": "Spēlētājs",                       "en": "Player"},
    "xl_strategy":      {"lv": "Stratēģija",                      "en": "Strategy"},
    "xl_wins":          {"lv": "Uzvaras",                         "en": "Wins"},
    "xl_losses":        {"lv": "Zaudējumi",                       "en": "Losses"},
    "xl_draws":         {"lv": "Neizšķirts",                      "en": "Draws"},
    "xl_total":         {"lv": "Kopā",                            "en": "Total"},
    "xl_winpct":        {"lv": "Uzv%",                            "en": "Win%"},
    "xl_game":          {"lv": "Spēle #",                         "en": "Game #"},
    "xl_result":        {"lv": "Rezultāts",                       "en": "Result"},
    "xl_saved_at":      {"lv": "Saglabāts",                       "en": "Saved at"},
    "xl_total_games":   {"lv": "Kopā spēles",                     "en": "Total games"},
    "xl_decks":         {"lv": "Kāršu kavas",                     "en": "Decks"},
    "xl_lang":          {"lv": "Valoda",                          "en": "Language"},

    # ── Bots tab ──
    "b_no_bots":        {"lv": "(Botu nav)",                      "en": "(No bots)"},

    # ── Stats tab ──
    "st_dealer":        {"lv": "Dealer: ",                        "en": "Dealer: "},
    "st_draws":         {"lv": "Neizšķirts: ",                    "en": "Draws: "},
    "st_player_col":    {"lv": "Spēlētājs",                       "en": "Player"},
    "st_win_col":       {"lv": "Uzv",                             "en": "Win"},
    "st_lose_col":      {"lv": "Zd",                              "en": "Ls"},
    "st_draw_col":      {"lv": "Nz",                              "en": "Dr"},
    "st_pct_col":       {"lv": "Uzv%",                            "en": "Win%"},
    "st_clear":         {"lv": "🗑  Notīrīt rezultātus",          "en": "🗑  Clear results"},
    "st_card_dist":     {"lv": "Kāršu sadalījums",               "en": "Card distribution"},

    # ── Auto tab ──
    "a_games":          {"lv": "Spēļu skaits  (maks. 100 000)",  "en": "Number of games  (max 100 000)"},
    "a_start":          {"lv": "▶▶  Sākt Auto-replay",           "en": "▶▶  Start Auto-replay"},
    "a_stop":           {"lv": "⏹  Apturēt",                     "en": "⏹  Stop"},

    # ── Game messages ──
    "g_dealer":         {"lv": "DEALER",                          "en": "DEALER"},
    "g_showing":        {"lv": "Showing: ",                       "en": "Showing: "},
    "g_total":          {"lv": "Total: ",                         "en": "Total: "},
    "g_hit":            {"lv": "Hit",                             "en": "Hit"},
    "g_stand":          {"lv": "Stand",                           "en": "Stand"},
    "g_double":         {"lv": "Double",                          "en": "Double"},
    "g_hint":           {"lv": "💡 Mājiena",                      "en": "💡 Hint"},
    "g_play_again":     {"lv": "▶  Spēlēt vēlreiz",              "en": "▶  Play Again"},
    "g_autoreplay_running": {"lv": "⚡ Auto-replay — skatiet progresu →",
                             "en": "⚡ Auto-replay — see progress →"},

    # ── Results ──
    "r_dealer_bj":      {"lv": "Dealer Blackjack!",              "en": "Dealer Blackjack!"},
    "r_draw":           {"lv": "Neizšķirts",                     "en": "Push"},
    "r_lose":           {"lv": "Zaudē",                          "en": "Lose"},
    "r_win":            {"lv": "Win",                            "en": "Win"},
    "r_bust":           {"lv": "Bust",                           "en": "Bust"},
    "r_push":           {"lv": "Push",                           "en": "Push"},
    "r_you":            {"lv": "Tu",                             "en": "You"},

    # ── Dialogs ──
    "d_error":          {"lv": "Kļūda",                          "en": "Error"},
    "d_invalid_settings": {"lv": "Nederīgi iestatījumi!",        "en": "Invalid settings!"},
    "d_max_decks":      {"lv": "Maksimālais kāršu kavu skaits ir 250!",
                         "en": "Maximum number of decks is 250!"},
    "d_max_bots":       {"lv": "Maksimālais botu skaits ir 100!", "en": "Maximum number of bots is 100!"},
    "d_max_ar":         {"lv": "Maksimālais auto-replay skaits ir 100 000!",
                         "en": "Maximum auto-replay count is 100 000!"},
    "d_invalid_games":  {"lv": "Ievadiet derīgu spēļu skaitu!",  "en": "Enter a valid game count!"},
    "d_reset_q":        {"lv": "Atiestatīt visus rezultātus?",   "en": "Reset all results?"},
    "d_reset_title":    {"lv": "Reset",                          "en": "Reset"},
    "d_reset_done":     {"lv": "Atiestatīts.",                   "en": "Reset."},
    "d_no_data":        {"lv": "Nav datu",                       "en": "No data"},
    "d_no_games":       {"lv": "Nav nevienas spēles!",           "en": "No games played yet!"},
    "d_saved":          {"lv": "Saglabāts",                      "en": "Saved"},
    "d_saved_msg":      {"lv": "Saglabāts:\n",                   "en": "Saved:\n"},

    # ── Strategy editor ──
    "se_hint_label":    {"lv": "Klikšķini šūnu lai mainītu  |  Klikšķini rindas/kolonnas etiķeti lai aizpildītu visu:",
                         "en": "Click cell to cycle  |  Click row/column label to fill entire row/col:"},
    "se_reset":         {"lv": "↩️ Pamata",                      "en": "↩️ Default"},
    "se_save":          {"lv": "💾 Saglabāt",                    "en": "💾 Save"},
    "se_load":          {"lv": "— Ielādēt —",                    "en": "— Load —"},
    "se_close":         {"lv": "✅ Aizvērt",                     "en": "✅ Close"},
    "se_pick_action":   {"lv": "Izvēlies darbību",               "en": "Pick action"},
    "se_fill_with":     {"lv": "Ar ko aizpildīt?",               "en": "Fill with?"},

    # ── Tutorial ──
    "t_prev":           {"lv": "◀ Iepriekšējā",                  "en": "◀ Previous"},
    "t_next":           {"lv": "Nākamā ▶",                       "en": "Next ▶"},
    "t_close":          {"lv": "✅ Aizvērt",                     "en": "✅ Close"},

    # ── Stats file ──
    "f_title":          {"lv": "CardLab — Blackjack statistika", "en": "CardLab — Blackjack statistics"},
    "f_saved_at":       {"lv": "Saglabāts:",                     "en": "Saved:"},
    "f_total_games":    {"lv": "Kopā spēles:",                   "en": "Total games:"},
    "f_player_info":    {"lv": "SPĒLĒTĀJU INFORMĀCIJA:",         "en": "PLAYER INFORMATION:"},
    "f_manual":         {"lv": "Manuāla (cilvēks)",              "en": "Manual (human)"},
    "f_strategy":       {"lv": "Stratēģija:",                    "en": "Strategy:"},
    "f_results_by":     {"lv": "REZULTĀTI PEC SPĒLĒTĀJA:",       "en": "RESULTS BY PLAYER:"},
    "f_name_col":       {"lv": "Vārds",                          "en": "Name"},
    "f_win_col":        {"lv": "Uzv",                            "en": "Win"},
    "f_lose_col":       {"lv": "Zaud",                           "en": "Lose"},
    "f_draw_col":       {"lv": "Neizš",                          "en": "Draw"},
    "f_winpct_col":     {"lv": "Uzv%",                           "en": "Win%"},
    "f_vs_dealer_col":  {"lv": "Pret dīl",                       "en": "Vs dealer"},
    "f_all":            {"lv": "VISI KOPĀ",                      "en": "TOTAL"},
    "f_dealer_sum":     {"lv": "DĪLERIS (kopsavilkums pret VISIEM spēlētājiem):",
                         "en": "DEALER (summary vs ALL players):"},
    "f_dealer_wins":    {"lv": "Dīlera uzvaras:",                "en": "Dealer wins:"},
    "f_dealer_loses":   {"lv": "Dīlera zaudējumi:",              "en": "Dealer losses:"},
    "f_dealer_draws":   {"lv": "Neizšķirts (push):",             "en": "Draws (push):"},
    "f_game_log":       {"lv": "SPĒĻU ŽURNĀLS (pa spēlei):",     "en": "GAME LOG (per game):"},
    "f_game":           {"lv": "Spēle",                          "en": "Game"},
    "f_no_log":         {"lv": "(Spēle-pa-spēlei žurnāls nav pieejams auto-replay režīmā)",
                         "en": "(Per-game log not available in auto-replay mode)"},
    "f_win_r":          {"lv": "Uzv",                            "en": "Win"},
    "f_lose_r":         {"lv": "Zaud",                           "en": "Lose"},
    "f_draw_r":         {"lv": "Neizš",                          "en": "Draw"},

    # ── Preset names (kept in Latvian/universal — only non-emoji part changes) ──
    "p_basic":          {"lv": "🎯 Pamata",                      "en": "🎯 Basic"},
    "p_aggressive":     {"lv": "🔥 Agresīvs",                   "en": "🔥 Aggressive"},
    "p_conservative":   {"lv": "🛡️ Konservatīvs",               "en": "🛡️ Conservative"},
    "p_cautious":       {"lv": "🐢 Piesardzīgs",                 "en": "🐢 Cautious"},
    "p_custom":         {"lv": "✏️ Custom",                      "en": "✏️ Custom"},

    # ── Auto-replay status ──
    "ar_games":         {"lv": " spēles...",                     "en": " games..."},
    "ar_done":          {"lv": "✔ Pabeigts!",                    "en": "✔ Done!"},
    "ar_stopped":       {"lv": "⏹ Apturēts",                    "en": "⏹ Stopped"},
    "ar_stopped_at":    {"lv": "⏹ Apturēts pie ",               "en": "⏹ Stopped at "},

    # ── Hint popup ──
    "h_title":          {"lv": "💡 Mājiena",                     "en": "💡 Hint"},
    "h_action_H":       {"lv": "Ņem karti (Hit)",               "en": "Take a card (Hit)"},
    "h_action_S":       {"lv": "Paliec (Stand)",                 "en": "Stay (Stand)"},
    "h_action_D":       {"lv": "Dubulto (Double)",               "en": "Double Down"},
    "h_action_R":       {"lv": "Padodies (Surrender)",           "en": "Surrender"},
    "h_vs":             {"lv": "pret dīlera",                    "en": "vs dealer"},
    "h_soft":           {"lv": "Mīkstā roka",                   "en": "Soft hand"},
    "h_hard":           {"lv": "Cietā roka",                    "en": "Hard hand"},

    # ── Tutorial window ──
    "tut_title":        {"lv": "📖 CardLab — Pamācība",           "en": "📖 CardLab — Tutorial"},
    "tut_prev":         {"lv": "◀ Iepriekšējā",                   "en": "◀ Previous"},
    "tut_next":         {"lv": "Nākamā ▶",                        "en": "Next ▶"},
    "tut_close":        {"lv": "✅ Aizvērt",                      "en": "✅ Close"},

    # ── Stats file save ──
    "s_save_autoplay_only": {"lv": "💾  Saglabāt (tikai Auto-replay)",
                              "en": "💾  Save (Auto-replay only)"},

    # ── Default player name ──
    "default_player":   {"lv": "Spēlētājs",                     "en": "Player"},
}

def T(key):
    """Return translated string for current language."""
    entry = LANG.get(key)
    if entry is None:
        return key
    return entry.get(_current_lang, entry.get("lv", key))

_current_lang = "lv"   # default language


# ──────────────────────────────────────────────────────────────────────────────
class Card:
    __slots__ = ("rank", "suit", "value", "_red")

    def __init__(self, rank, suit):
        self.rank  = rank
        self.suit  = suit
        self.value = self._get_value()
        self._red  = suit in ("♥", "♦")

    def _get_value(self):
        if self.rank == "A":   return 11
        if self.rank in "KQJ": return 10
        return int(self.rank)

    def is_red(self):
        return self._red


class Deck:
    def __init__(self, num_decks=6):
        self.num_decks = num_decks
        self.cards: List[Card] = []
        self.reset()

    def reset(self):
        self.cards = [Card(r, s)
                      for _ in range(self.num_decks)
                      for s in SUITS
                      for r in RANKS]
        random.shuffle(self.cards)

    def deal(self): return self.cards.pop()
    def cards_remaining(self): return len(self.cards)


class Hand:
    __slots__ = ("name", "cards")

    def __init__(self, name):
        self.name  = name
        self.cards: List[Card] = []

    def add_card(self, card): self.cards.append(card)

    def get_value(self):
        total = aces = 0
        for c in self.cards:
            total += c.value
            if c.rank == "A": aces += 1
        while total > 21 and aces:
            total -= 10; aces -= 1
        return total

    def _value_and_soft(self):
        """Single-pass helper returning (total, is_soft) — used internally."""
        total = aces = 0
        for c in self.cards:
            total += c.value
            if c.rank == "A": aces += 1
        adjusted = False
        while total > 21 and aces:
            total -= 10; aces -= 1; adjusted = True
        # soft = has at least one ace counted as 11
        soft = aces > 0 and total <= 21
        return total, soft

    def is_soft(self):
        _, s = self._value_and_soft()
        return s

    def is_blackjack(self): return len(self.cards) == 2 and self.get_value() == 21
    def is_bust(self):      return self.get_value() > 21
    def can_split(self):    return len(self.cards) == 2 and self.cards[0].rank == self.cards[1].rank


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURABLE STRATEGY TABLE
# ──────────────────────────────────────────────────────────────────────────────

# Dealer upcards as column indices: 2,3,4,5,6,7,8,9,10,A(11)
UPCARD_COLS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# Hard totals as row keys: 5-17+
HARD_ROWS = list(range(5, 22))   # 5..21

# Soft totals as row keys (the non-ace card value): A+2..A+9 → total 13..21
SOFT_ROWS = list(range(13, 22))  # 13..21  (soft 13 = A+2, soft 21 = A+10)

ACTION_CYCLE = ['H', 'S', 'D', 'R']   # R = Surrender (treated as H if not allowed)
ACTION_COLORS = {
    'H': '#27ae60',   # green
    'S': '#e74c3c',   # red
    'D': '#f1c40f',   # yellow
    'R': '#e67e22',   # orange
}

def _build_default_hard_table():
    """Returns dict: {hard_total: {upcard: action}}  matching basic strategy."""
    t = {}
    for total in HARD_ROWS:
        t[total] = {}
        for up in UPCARD_COLS:
            if total >= 17:
                a = 'S'
            elif 13 <= total <= 16:
                a = 'S' if 2 <= up <= 6 else 'H'
                if total in (15, 16) and up in (9, 10, 11):
                    a = 'R'
            elif total == 12:
                a = 'S' if 4 <= up <= 6 else 'H'
            elif total == 11:
                a = 'D'
            elif total == 10:
                a = 'D' if 2 <= up <= 9 else 'H'
            elif total == 9:
                a = 'D' if 3 <= up <= 6 else 'H'
            else:
                a = 'H'
            t[total][up] = a
    return t

def _build_default_soft_table():
    """Returns dict: {soft_total: {upcard: action}}  matching basic strategy."""
    t = {}
    for total in SOFT_ROWS:
        t[total] = {}
        for up in UPCARD_COLS:
            if total >= 20:
                a = 'S'
            elif total == 19:
                a = 'D' if up == 6 else 'S'
            elif total == 18:
                if up >= 9: a = 'H'
                elif 3 <= up <= 6: a = 'D'
                else: a = 'S'
            elif total == 17:
                a = 'D' if 3 <= up <= 6 else 'H'
            elif total in (15, 16):
                a = 'D' if 4 <= up <= 6 else 'H'
            elif total in (13, 14):
                a = 'D' if 5 <= up <= 6 else 'H'
            else:
                a = 'H'
            t[total][up] = a
    return t


class BotStrategy:
    """Per-bot configurable strategy table."""

    def __init__(self):
        self.hard = _build_default_hard_table()
        self.soft = _build_default_soft_table()

    def get_action(self, total, upcard, can_split, can_double, is_soft, hand):
        # Normalize upcard (Ace = 11)
        up = upcard
        if up > 11: up = 10  # face cards all = 10

        if is_soft and total in self.soft:
            raw = self.soft[total].get(up, 'H')
        else:
            # Clamp to table range
            key = min(max(total, 5), 21)
            raw = self.hard.get(key, {}).get(up, 'H')

        # If action is D but can't double → fall back to H
        if raw == 'D' and not can_double:
            return 'H'
        # If action is R (surrender) → treat as H (most games don't allow late surrender)
        if raw == 'R':
            return 'H'
        return raw

    def copy(self):
        """Deep copy for thread snapshot."""
        import copy
        s = BotStrategy.__new__(BotStrategy)
        s.hard = copy.deepcopy(self.hard)
        s.soft = copy.deepcopy(self.soft)
        return s


# ──────────────────────────────────────────────────────────────────────────────
# PRESET STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────

def _preset_names():
    return [T("p_basic"), T("p_aggressive"), T("p_conservative"), T("p_cautious"), T("p_custom")]

PRESET_NAMES = ["🎯 Pamata", "🔥 Agresīvs", "🛡️ Konservatīvs", "🐢 Piesardzīgs", "✏️ Custom"]

def _make_preset(name: str) -> BotStrategy:
    s = BotStrategy()  # starts as basic strategy
    if name == "🔥 Agresīvs":
        # Double on everything 9-11, hit aggressively (never stand below 18)
        for total in HARD_ROWS:
            for up in UPCARD_COLS:
                if 9 <= total <= 11:
                    s.hard[total][up] = 'D'
                elif total <= 17:
                    s.hard[total][up] = 'H'
                else:
                    s.hard[total][up] = 'S'
        for total in SOFT_ROWS:
            for up in UPCARD_COLS:
                if total <= 17:
                    s.soft[total][up] = 'D' if total >= 15 else 'H'
                else:
                    s.soft[total][up] = 'S'
    elif name == "🛡️ Konservatīvs":
        # Stand on anything 13+, double only on 10-11
        for total in HARD_ROWS:
            for up in UPCARD_COLS:
                if total >= 13:
                    s.hard[total][up] = 'S'
                elif total in (10, 11):
                    s.hard[total][up] = 'D'
                else:
                    s.hard[total][up] = 'H'
        for total in SOFT_ROWS:
            for up in UPCARD_COLS:
                s.soft[total][up] = 'S' if total >= 17 else 'H'
    elif name == "🐢 Piesardzīgs":
        # Never double, stand on 15+
        for total in HARD_ROWS:
            for up in UPCARD_COLS:
                s.hard[total][up] = 'S' if total >= 15 else 'H'
        for total in SOFT_ROWS:
            for up in UPCARD_COLS:
                s.soft[total][up] = 'S' if total >= 18 else 'H'
    # "🎯 Pamata" and "✏️ Custom" → keep default basic strategy
    return s


# ─── Global hint strategy (basic strategy, used for player hint button) ───────
# Pre-built singleton — avoids creating a new BotStrategy object on every call
_GLOBAL_STRATEGY = BotStrategy()   # initialised once after BotStrategy is defined

class Strategy:
    @staticmethod
    def get_action(total, upcard, can_split, can_double, is_soft, hand):
        return _GLOBAL_STRATEGY.get_action(total, upcard, can_split, can_double, is_soft, hand)


# ──────────────────────────────────────────────────────────────────────────────
# STRATEGY EDITOR WINDOW
# ──────────────────────────────────────────────────────────────────────────────

class StrategyEditorWindow:
    """
    Popup: full hard + soft strategy table.
    • Click cell → cycle H→S→D→R
    • Row label button → fill entire row with chosen action
    • Column header button → fill entire column with chosen action
    • Save/Load named strategies (persisted to disk via parent app)
    """

    def __init__(self, parent, bot_strategy: BotStrategy, bot_name: str,
                 app=None, on_close=None):
        self.strategy  = bot_strategy
        self.app       = app        # reference to BlackjackGUI for save/load
        self.on_close  = on_close
        self._btn_refs = {}         # (table_id, row_key, upcard) → Button

        self.win = tk.Toplevel(parent)
        self.win.title(f"⚙️ Stratēģija — {bot_name}")
        self.win.configure(bg="#1a1a2e")
        self.win.resizable(True, True)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self._build_ui()

    # ── build ──────────────────────────────────────
    def _build_ui(self):
        root = self.win

        # Legend
        leg = tk.Frame(root, bg="#1a1a2e")
        leg.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(leg, text="Klikšķini šūnu lai mainītu  |  Klikšķini rindas/kolonnas etiķeti lai aizpildītu visu:",
                 font=("Arial", 9), bg="#1a1a2e", fg="#a0a0c0").pack(side=tk.LEFT)
        for act, col in ACTION_COLORS.items():
            tk.Label(leg, text=act, font=("Arial", 9, "bold"),
                     bg=col, fg="white", padx=6, pady=1).pack(side=tk.RIGHT, padx=1)

        # Tables
        main = tk.Frame(root, bg="#1a1a2e")
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        hf = tk.LabelFrame(main, text="Hard", font=("Arial", 10, "bold"),
                            bg="#1a1a2e", fg="#f1c40f", padx=3, pady=3)
        hf.pack(side=tk.LEFT, padx=(0, 6), anchor=tk.N)
        self._build_table(hf, "hard", HARD_ROWS, self.strategy.hard)

        sf = tk.LabelFrame(main, text="Soft (A+)", font=("Arial", 10, "bold"),
                            bg="#1a1a2e", fg="#f1c40f", padx=3, pady=3)
        sf.pack(side=tk.LEFT, anchor=tk.N)
        self._build_table(sf, "soft", SOFT_ROWS, self.strategy.soft)

        # Bottom bar
        bot = tk.Frame(root, bg="#1a1a2e")
        bot.pack(fill=tk.X, padx=10, pady=(4, 8))

        tk.Button(bot, text="↩️ Pamata",
                  font=("Arial", 9, "bold"), bg="#8e44ad", fg="white",
                  padx=6, pady=4, bd=0, cursor="hand2",
                  command=self._reset).pack(side=tk.LEFT, padx=(0, 4))

        # Save section
        self._save_name = tk.StringVar()
        tk.Entry(bot, textvariable=self._save_name,
                 font=("Arial", 9), width=14,
                 bg="#1a4a20", fg="white", insertbackground="white",
                 ).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(bot, text="💾 Saglabāt",
                  font=("Arial", 9, "bold"), bg="#2980b9", fg="white",
                  padx=6, pady=4, bd=0, cursor="hand2",
                  command=self._save_strategy).pack(side=tk.LEFT, padx=(0, 4))

        # Load section
        self._load_var = tk.StringVar(value="— Ielādēt —")
        self._load_menu_btn = tk.OptionMenu(bot, self._load_var, "— Ielādēt —",
                                            command=self._load_strategy)
        self._load_menu_btn.config(font=("Arial", 9), bg="#1a4a20", fg="white",
                                   highlightthickness=0, bd=0, padx=4, pady=3, width=12)
        self._load_menu_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._refresh_load_menu()

        tk.Button(bot, text="✅ Aizvērt",
                  font=("Arial", 9, "bold"), bg="#27ae60", fg="white",
                  padx=6, pady=4, bd=0, cursor="hand2",
                  command=self._close).pack(side=tk.RIGHT)

    def _build_table(self, parent, table_id, row_keys, table_data):
        upcard_labels = ['2','3','4','5','6','7','8','9','10','A']

        # Blank corner
        tk.Label(parent, text="", bg="#1a1a2e", width=5).grid(row=0, column=0)

        # Column header buttons — click to fill whole column
        for ci, (ul, up) in enumerate(zip(upcard_labels, UPCARD_COLS)):
            btn = tk.Button(parent, text=ul, font=("Arial", 8, "bold"),
                            bg="#2c3e50", fg="#f1c40f", width=3, pady=1,
                            bd=0, cursor="hand2",
                            command=lambda tid=table_id, uc=up: self._fill_col(tid, uc))
            btn.grid(row=0, column=ci+1, padx=1, pady=1)

        for ri, row_key in enumerate(row_keys):
            # Row label button — click to fill whole row
            if table_id == "soft":
                lbl_text = f"A,{row_key-11}"
            else:
                lbl_text = str(row_key)
            row_btn = tk.Button(parent, text=lbl_text, font=("Arial", 8, "bold"),
                                bg="#2c3e50", fg="white", width=5, pady=1,
                                bd=0, cursor="hand2",
                                command=lambda tid=table_id, rk=row_key: self._fill_row(tid, rk))
            row_btn.grid(row=ri+1, column=0, padx=1, pady=1)

            for ci, up in enumerate(UPCARD_COLS):
                act = table_data.get(row_key, {}).get(up, 'H')
                btn = tk.Button(parent, text=act, font=("Arial", 8, "bold"),
                                bg=ACTION_COLORS.get(act, '#888'), fg="white",
                                width=3, pady=1, bd=0, cursor="hand2", relief=tk.FLAT)
                btn.grid(row=ri+1, column=ci+1, padx=1, pady=1)
                btn.config(command=lambda b=btn, tid=table_id, rk=row_key, uc=up:
                           self._cycle(b, tid, rk, uc))
                self._btn_refs[(table_id, row_key, up)] = btn

    def _cycle(self, btn, table_id, row_key, upcard):
        table = self.strategy.hard if table_id == "hard" else self.strategy.soft
        cur = table.get(row_key, {}).get(upcard, 'H')
        nxt = ACTION_CYCLE[(ACTION_CYCLE.index(cur) + 1) % len(ACTION_CYCLE)]
        table.setdefault(row_key, {})[upcard] = nxt
        btn.config(text=nxt, bg=ACTION_COLORS[nxt])

    def _fill_row(self, table_id, row_key):
        """Ask which action, then fill the whole row."""
        self._ask_action(lambda act: self._apply_fill_row(table_id, row_key, act))

    def _fill_col(self, table_id, upcard):
        self._ask_action(lambda act: self._apply_fill_col(table_id, upcard, act))

    def _ask_action(self, callback):
        """Small popup to pick H/S/D/R."""
        popup = tk.Toplevel(self.win)
        popup.title("Izvēlies darbību")
        popup.configure(bg="#1a1a2e")
        popup.resizable(False, False)
        tk.Label(popup, text="Ar ko aizpildīt?", font=("Arial", 10),
                 bg="#1a1a2e", fg="white").pack(padx=16, pady=(10, 6))
        row = tk.Frame(popup, bg="#1a1a2e")
        row.pack(padx=12, pady=(0, 12))
        labels = {'H': 'H  Hit', 'S': 'S  Stand', 'D': 'D  Double', 'R': 'R  Surrender'}
        for act in ACTION_CYCLE:
            tk.Button(row, text=labels[act], font=("Arial", 10, "bold"),
                      bg=ACTION_COLORS[act], fg="white", padx=10, pady=6, bd=0,
                      cursor="hand2",
                      command=lambda a=act: (popup.destroy(), callback(a))
                      ).pack(side=tk.LEFT, padx=3)

    def _apply_fill_row(self, table_id, row_key, act):
        table = self.strategy.hard if table_id == "hard" else self.strategy.soft
        table.setdefault(row_key, {})
        for up in UPCARD_COLS:
            table[row_key][up] = act
            btn = self._btn_refs.get((table_id, row_key, up))
            if btn:
                btn.config(text=act, bg=ACTION_COLORS[act])

    def _apply_fill_col(self, table_id, upcard, act):
        table = self.strategy.hard if table_id == "hard" else self.strategy.soft
        row_keys = HARD_ROWS if table_id == "hard" else SOFT_ROWS
        for rk in row_keys:
            table.setdefault(rk, {})[upcard] = act
            btn = self._btn_refs.get((table_id, rk, upcard))
            if btn:
                btn.config(text=act, bg=ACTION_COLORS[act])

    def _reset(self):
        if messagebox.askyesno("Reset", "Atjaunot uz pamata stratēģiju?", parent=self.win):
            self.strategy.hard = _build_default_hard_table()
            self.strategy.soft = _build_default_soft_table()
            for (tid, rk, uc), btn in self._btn_refs.items():
                table = self.strategy.hard if tid == "hard" else self.strategy.soft
                act = table.get(rk, {}).get(uc, 'H')
                btn.config(text=act, bg=ACTION_COLORS[act])

    def _save_strategy(self):
        name = self._save_name.get().strip()
        if not name:
            messagebox.showwarning("Kļūda", "Ievadi stratēģijas nosaukumu!", parent=self.win)
            return
        if self.app:
            self.app.saved_strategies[name] = self.strategy.copy()
            self.app._persist_saved_strategies()
            self._refresh_load_menu()
            messagebox.showinfo("Saglabāts", f'Stratēģija "{name}" saglabāta!', parent=self.win)

    def _load_strategy(self, name):
        if not self.app or name == "— Ielādēt —":
            return
        s = self.app.saved_strategies.get(name)
        if not s:
            return
        import copy
        self.strategy.hard = copy.deepcopy(s.hard)
        self.strategy.soft = copy.deepcopy(s.soft)
        for (tid, rk, uc), btn in self._btn_refs.items():
            table = self.strategy.hard if tid == "hard" else self.strategy.soft
            act = table.get(rk, {}).get(uc, 'H')
            btn.config(text=act, bg=ACTION_COLORS[act])
        self._load_var.set("— Ielādēt —")

    def _refresh_load_menu(self):
        menu = self._load_menu_btn["menu"]
        menu.delete(0, tk.END)
        menu.add_command(label="— Ielādēt —",
                         command=lambda: self._load_var.set("— Ielādēt —"))
        if self.app:
            for name in self.app.saved_strategies:
                menu.add_command(label=name,
                                 command=lambda n=name: self._load_strategy(n))

    def _close(self):
        if self.on_close:
            self.on_close()
        self.win.destroy()


# ──────────────────────────────────────────────────────────────────────────────
def _compute_scale(total_players):
    """
    Return (scale_factor, max_per_row).
    ≤10 players  → scale=1.0, per_row=8
    11-18 players→ scale shrinks linearly (min 1/3), per_row grows
    """
    if total_players <= 10:
        return 1.0, 8
    # How many extra beyond 10
    extra = total_players - 10
    # Each extra player reduces scale by 0.05, floored at 1/3
    scale = max(1 / 3, 1.0 - extra * 0.05)
    # Allow more per row as cards shrink (inversely)
    per_row = min(16, int(8 / scale))
    return scale, per_row


# ──────────────────────────────────────────────────────────────────────────────
# TUTORIAL WINDOW
# ──────────────────────────────────────────────────────────────────────────────

TUTORIAL_SECTIONS = {
    "lv": [
        ("🃏 Blackjack pamati", """Mērķis: dabūt roku tuvāku 21 nekā dīlerim, nepārsniedzot to.

• Kārtis 2–10 vērtību = nominālvērtība
• J, Q, K = 10 punkti
• Ass (A) = 11 vai 1 — automātiski izvēlas labāko

Dīleris vienmēr ņem kārti, kamēr ir < 17. No 17 vienmēr stāv.

Blackjack = Ass + 10-vērtības kārts pirmajās 2 kārtīs."""),

        ("🎮 Spēles vadība", """Hit — ņem vēl vienu kārti.
Stand — apstāties ar pašreizējo roku.
Double Down — dubulto likmi, ņem tieši 1 kārti, tad automātiski Stand.
💡 Hint — parāda ko ieteiktu pamata stratēģija.

Kārtis tiek dalītas animēti. Pēc spēles nospiedi
"Spēlēt vēlreiz" lai sāktu nākamo raundi."""),

        ("🤖 Boti un stratēģijas", """Botu skaitu maini ar "Botu skaits" spinner sānjoslā (0–100).

Katram botam var piešķirt stratēģiju:
  🎯 Pamata    — klasiskā basic strategy (optimāla)
  🔥 Agresīvs  — double gandrīz visur, hit agresīvi
  🛡️ Konservatīvs — stand no 13+
  🐢 Piesardzīgs  — stand no 15+, nekad nedoubles
  ✏️ Custom    — pilnīgi pielāgojama tabula

Nospiedi ✏️ blakus dropdownam, lai atvērtu tabulas redaktoru."""),

        ("✏️ Stratēģijas redaktors", """Redaktorā redzama pilna Hard + Soft tabula.

Katru šūnu noklikšķini lai mainītu: H → S → D → R → H
  H = Hit       S = Stand
  D = Double    R = Surrender (→ Hit)

Ātrās pogas:
  Rindas pogas  — uzstāda visu rindu uzreiz (H/S/D)
  Kolonnas pogas — uzstāda visu kolonnu uzreiz

Saglabāt stratēģiju: ievadi nosaukumu laukā apakšā
un nospied "💾 Saglabāt". Stratēģija paliek starp sesijām."""),

        ("📊 Auto-replay", """Auto-replay ļauj simulēt tūkstošiem spēļu sekundēs.

1. Ievadi spēļu skaitu laukā "Spēļu skaits"
2. Nospied "▶▶ Sākt Auto"
3. Skaties progress bārā
4. Nospied "⏹ Stop" lai apturētu jebkurā brīdī

Rezultāti tiek atjaunoti reāllaikā — var redzēt
uzvaru procentus katram botam ar katru stratēģiju."""),

        ("💾 Statistikas saglabāšana", """Nospied "💾 Saglabāt" sānjoslā.

Fails tiek saglabāts Lejupielāžu mapē un satur:
  • Katra spēlētāja vārds un stratēģija
  • Uzvaras / Zaudējumi / Neizšķirts skaits
  • Uzvaru procents pret dīleri
  • Kopsavilkums: visi spēlētāji pret dīleri
  • Detalizēts spēle-pa-spēlei žurnāls

Tikai Auto-replay spēles tiek saglabātas failā."""),

        ("✏️ Pārsaukt spēlētājus", """Sānjoslā sadaļā "⚙️ Iestatījumi" ir nosaukumu lauki.

Cilvēka spēlētāja vārds: mainiet laukā "Tavs vārds:".
Botu vārdi: katram botam ir savs nosaukuma lauks.

Vārdi parādās:
  • Uz galda pie katras rokas
  • Rezultātu sadaļā sānjoslā
  • Saglabātajā statistikas failā"""),
    ],
    "en": [
        ("🃏 Blackjack Basics", """Goal: get a hand closer to 21 than the dealer without going over.

• Cards 2–10 = face value
• J, Q, K = 10 points
• Ace (A) = 11 or 1 — chosen automatically for the best total

Dealer always hits until reaching 17, then always stands.

Blackjack = Ace + any 10-value card in the first 2 cards."""),

        ("🎮 Game Controls", """Hit — take another card.
Stand — keep your current hand.
Double Down — double your bet, take exactly 1 card, then auto-Stand.
💡 Hint — shows what basic strategy recommends.

Cards are dealt with animation. After the round press
"Play Again" to start the next hand."""),

        ("🤖 Bots & Strategies", """Change the number of bots with the "Number of bots" spinner (0–100).

Each bot can be assigned a strategy:
  🎯 Basic       — classic basic strategy (optimal)
  🔥 Aggressive  — doubles almost everywhere, hits aggressively
  🛡️ Conservative — stands from 13+
  🐢 Cautious    — stands from 15+, never doubles
  ✏️ Custom      — fully customisable table

Press ✏️ next to the dropdown to open the table editor."""),

        ("✏️ Strategy Editor", """The editor shows the full Hard + Soft strategy table.

Click any cell to cycle: H → S → D → R → H
  H = Hit       S = Stand
  D = Double    R = Surrender (→ Hit)

Quick-fill buttons:
  Row buttons    — set the entire row at once (H/S/D)
  Column buttons — set the entire column at once

Save a strategy: type a name in the field at the bottom
and press "💾 Save". The strategy persists between sessions."""),

        ("📊 Auto-replay", """Auto-replay lets you simulate thousands of games in seconds.

1. Enter the number of games in "Number of games"
2. Press "▶▶ Start Auto-replay"
3. Watch the progress bar
4. Press "⏹ Stop" to stop at any time

Results update in real-time — you can see win percentages
for each bot with each strategy."""),

        ("💾 Saving Statistics", """Press "💾 Save" in the sidebar.

Files are saved to your Downloads folder and contain:
  • Each player's name and strategy
  • Win / Loss / Draw counts
  • Win percentage vs dealer
  • Summary: all players vs dealer
  • Detailed game-by-game log

Only Auto-replay games are saved to file."""),

        ("✏️ Renaming Players", """Name fields are in the sidebar under "⚙️ Settings".

Human player name: change in the "Your name" field.
Bot names: each bot has its own name field.

Names appear:
  • On the table next to each hand
  • In the stats section of the sidebar
  • In the saved statistics file"""),
    ],
}


class TutorialWindow:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title(T("tut_title"))
        self.win.geometry("620x520")
        self.win.configure(bg="#1a1a2e")
        self.win.resizable(True, True)
        self._page = 0
        self._build()

    def _sections(self):
        lang = _current_lang if _current_lang in TUTORIAL_SECTIONS else "lv"
        return TUTORIAL_SECTIONS[lang]

    def _build(self):
        w = self.win

        # Top nav tabs
        self.tab_frame = tk.Frame(w, bg="#0d0d1f")
        self.tab_frame.pack(fill=tk.X)
        self.tab_btns = []
        for i, (title, _) in enumerate(self._sections()):
            short = title.split(" ", 1)[0]  # just emoji
            b = tk.Button(self.tab_frame, text=short, font=("Arial", 14),
                          bg="#0d0d1f", fg="#a0a0c0", bd=0, padx=10, pady=6,
                          cursor="hand2", command=lambda ii=i: self._goto(ii))
            b.pack(side=tk.LEFT)
            self.tab_btns.append(b)

        # Content area
        self.title_lbl = tk.Label(w, text="", font=("Arial", 16, "bold"),
                                  bg="#1a1a2e", fg="#667eea")
        self.title_lbl.pack(pady=(14, 4), padx=20, anchor=tk.W)

        self.text_lbl = tk.Label(w, text="", font=("Arial", 11),
                                 bg="#1a1a2e", fg="#d0d0e0",
                                 justify=tk.LEFT, anchor=tk.NW,
                                 wraplength=560)
        self.text_lbl.pack(padx=24, pady=4, fill=tk.BOTH, expand=True, anchor=tk.W)

        # Bottom nav
        nav = tk.Frame(w, bg="#1a1a2e")
        nav.pack(fill=tk.X, padx=16, pady=12)
        self.prev_btn = tk.Button(nav, text=T("tut_prev"), font=("Arial", 10, "bold"),
                                  bg="#444", fg="white", bd=0, padx=10, pady=6,
                                  cursor="hand2", command=self._prev)
        self.prev_btn.pack(side=tk.LEFT)
        self.page_lbl = tk.Label(nav, text="", font=("Arial", 10),
                                 bg="#1a1a2e", fg="#888")
        self.page_lbl.pack(side=tk.LEFT, padx=12)
        self.next_btn = tk.Button(nav, text=T("tut_next"), font=("Arial", 10, "bold"),
                                  bg="#667eea", fg="white", bd=0, padx=10, pady=6,
                                  cursor="hand2", command=self._next)
        self.next_btn.pack(side=tk.LEFT)
        tk.Button(nav, text=T("tut_close"), font=("Arial", 10, "bold"),
                  bg="#27ae60", fg="white", bd=0, padx=10, pady=6,
                  cursor="hand2", command=self.win.destroy).pack(side=tk.RIGHT)

        self._goto(0)

    def _goto(self, page):
        self._page = page
        secs = self._sections()
        title, body = secs[page]
        self.title_lbl.config(text=title)
        self.text_lbl.config(text=body)
        self.page_lbl.config(text=f"{page+1} / {len(secs)}")
        # Highlight active tab
        for i, b in enumerate(self.tab_btns):
            b.config(bg="#667eea" if i == page else "#0d0d1f",
                     fg="white" if i == page else "#a0a0c0")
        self.prev_btn.config(state=tk.NORMAL if page > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if page < len(secs)-1 else tk.DISABLED)

    def _prev(self): self._goto(self._page - 1)
    def _next(self): self._goto(self._page + 1)


# ──────────────────────────────────────────────────────────────────────────────
class BlackjackGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🃏 CardLab - Blackjack Simulator")
        self.root.geometry("1450x920")
        self.root.minsize(1200, 800)

        # Language
        self._lang = tk.StringVar(value="lv")

        # Settings vars
        self.num_decks   = tk.IntVar(value=6)
        self.num_bots    = tk.IntVar(value=1)
        self.anim_speed  = tk.IntVar(value=300)   # ms base
        self.human_plays = tk.BooleanVar(value=True)  # human player on/off

        # Auto-replay
        self.autoreplay_count      = tk.IntVar(value=10)
        self._autoreplay_remaining = 0
        self._autoreplay_running   = False
        self._autoreplay_total     = 0
        self._ar_per_player: dict  = {}
        self._ar_batch_size        = 50          # kept for UI spinbox compat
        self._ar_thread: threading.Thread | None = None
        self._ar_stop_event        = threading.Event()
        self._ar_queue: queue.Queue = queue.Queue()  # thread → UI messages

        # Game state
        self.deck   = None
        self.dealer = None
        self.player = None   # may be None if human_plays=False
        self.bots:  List[Hand] = []
        self.playing = False

        # Per-bot strategy tables (grown dynamically as bots are added)
        self.bot_strategies: List[BotStrategy] = []
        self._bot_preset_vars: List[tk.StringVar] = []

        # Player names (index 0 = human player, 1+ = bots)
        self.player_name   = tk.StringVar(value=T("default_player"))
        self.bot_names:  List[tk.StringVar] = []   # populated in _refresh_bot_strategy_buttons

        # Saved custom strategies: {name: BotStrategy}
        self.saved_strategies: dict = {}
        self._load_saved_strategies()

        # Stats
        self.player_wins = 0
        self.dealer_wins = 0
        self.bot_wins:  List[int] = []
        self.draws       = 0
        self.game_log    = []
        self.game_number = 0

        # UI colours  (v10 — clean dark theme)
        self.bg_menu   = "#0f1117"
        self.bg_table  = "#1a2332"
        self.felt      = "#1e3a2f"
        self.card_bg   = "#ffffff"
        self.accent    = "#4f8ef7"
        self.accent2   = "#7c5cbf"
        self.gold      = "#f0b429"
        self.danger    = "#e05252"
        self.success   = "#3dca7a"
        self.sb_bg     = "#111827"
        self.sb_tab_bg = "#1f2937"
        self.text_dim  = "#6b7280"

        # Layout refs (populated in create_player_frames)
        self.player_frame       = None
        self.player_cards_frame = None
        self.player_value_label = None
        self.bot_frames      = []
        self.bot_cards_frames= []
        self.bot_value_labels= []

        self.create_menu_screen()

    # ──────────────────────────────────────────────
    # LANGUAGE TOGGLE
    # ──────────────────────────────────────────────
    def _set_language(self, lang: str):
        global _current_lang
        _current_lang = lang
        self._lang.set(lang)

        # Menu: safe to destroy and recreate (no game state lives there)
        if hasattr(self, 'menu_frame') and self.menu_frame.winfo_exists():
            self.menu_frame.destroy()
            del self.menu_frame
            self.create_menu_screen()
            return

        # Game screen: ONLY update widget text — never destroy or recreate frames
        for entry in getattr(self, '_lang_widgets', []):
            try:
                if len(entry) == 3:
                    # Tab button: (widget, key, icon) — keep icon prefix
                    widget, key, icon = entry
                    if widget.winfo_exists():
                        widget.config(text=f"{icon}\n{T(key)}")
                else:
                    widget, key = entry
                    if widget.winfo_exists():
                        widget.config(text=T(key))
            except Exception:
                pass

        # Update lang-toggle button highlights in the game screen
        for code, btn in getattr(self, '_lang_btn_refs', []):
            try:
                if btn.winfo_exists():
                    btn.config(
                        relief=tk.SUNKEN if code == lang else tk.FLAT,
                        bg="#2a2a3a" if code == lang else self.bg_table)
            except Exception:
                pass

        # Refresh stats labels (dealer/draws text includes translated prefix)
        if hasattr(self, 'dealer_wins_label'):
            try:
                self.update_stats()
            except Exception:
                pass

    def _make_lang_toggle(self, parent, bg):
        """Language buttons 🇱🇻 / EN. Saves refs so _set_language can update them."""
        frame = tk.Frame(parent, bg=bg)
        refs = []
        for code, label in [("lv", "🇱🇻"), ("en", "EN")]:
            btn = tk.Button(
                frame, text=label, font=("Arial", 12, "bold"),
                bg=bg, fg="white", bd=0, padx=6, pady=2,
                cursor="hand2", relief=tk.FLAT,
                activebackground=bg,
                command=lambda l=code: self._set_language(l))
            btn.pack(side=tk.LEFT, padx=1)
            if self._lang.get() == code:
                btn.config(relief=tk.SUNKEN, bg="#2a2a3a")
            refs.append((code, btn))
        if bg == self.bg_table:
            self._lang_btn_refs = refs
        return frame

    def _register_lang(self, widget, key: str):
        """Register a widget so _set_language() can update its text."""
        if not hasattr(self, '_lang_widgets'):
            self._lang_widgets = []
        self._lang_widgets.append((widget, key))

    # ──────────────────────────────────────────────
    # MENU
    # ──────────────────────────────────────────────
    def create_menu_screen(self):
        self.menu_frame = tk.Frame(self.root, bg=self.bg_menu)
        self.menu_frame.pack(fill=tk.BOTH, expand=True)

        # Language toggle — top-right corner
        lang_bar = tk.Frame(self.menu_frame, bg=self.bg_menu)
        lang_bar.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=10)
        self._make_lang_toggle(lang_bar, self.bg_menu).pack()

        # Center column
        center = tk.Frame(self.menu_frame, bg=self.bg_menu)
        center.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        tk.Label(center, text="♠", font=("Arial", 72), bg=self.bg_menu,
                 fg=self.accent).pack(pady=(0, 0))
        tk.Label(center, text="CardLab", font=("Georgia", 48, "bold"),
                 bg=self.bg_menu, fg="white").pack()
        tk.Label(center, text=T("menu_subtitle"), font=("Arial", 15),
                 bg=self.bg_menu, fg=self.text_dim).pack(pady=(2, 48))

        def menu_btn(key, color, cmd):
            tk.Button(center, text=T(key), font=("Arial", 14, "bold"),
                      bg=color, fg="white", padx=0, pady=14,
                      bd=0, cursor="hand2", width=22,
                      activebackground=color, relief=tk.FLAT,
                      command=cmd).pack(pady=6, fill=tk.X)

        menu_btn("menu_start",    self.accent,  self.start_game)
        menu_btn("menu_tutorial", self.accent2, self.open_tutorial)
        menu_btn("menu_quit",     self.danger,  self.root.quit)

    def start_game(self):
        self.menu_frame.destroy()
        del self.menu_frame
        self.root.configure(bg=self.bg_table)
        self.root.after(80, self.create_game_screen)

    # ──────────────────────────────────────────────
    # GAME SCREEN
    # ──────────────────────────────────────────────
    def create_game_screen(self):
        # Fresh widget registry for this screen
        self._lang_widgets = []
        self._lang_btn_refs = []

        self.game_frame = tk.Frame(self.root, bg=self.bg_table)
        self.game_frame.pack(fill=tk.BOTH, expand=True)

        # ── Left: play area ──
        self.table_frame = tk.Frame(self.game_frame, bg=self.bg_table)
        self.table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Right: tabbed panel ──
        self._build_tabbed_panel()

        # ── Top bar ──
        top_bar = tk.Frame(self.table_frame, bg=self.bg_table)
        top_bar.pack(fill=tk.X, padx=16, pady=(10, 0))

        tk.Label(top_bar, text="♠  CardLab", font=("Arial", 16, "bold"),
                 bg=self.bg_table, fg="white").pack(side=tk.LEFT)

        top_right = tk.Frame(top_bar, bg=self.bg_table)
        top_right.pack(side=tk.RIGHT)

        # Language toggle — rightmost item
        self._make_lang_toggle(top_right, self.bg_table).pack(side=tk.LEFT, padx=(0, 8))

        # Deck counter pill
        deck_pill = tk.Frame(top_right, bg="#253347", padx=10, pady=3)
        deck_pill.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(deck_pill, text="🃏", font=("Arial", 10),
                 bg="#253347", fg=self.text_dim).pack(side=tk.LEFT)
        self.deck_count_label = tk.Label(deck_pill, text="—",
                                         font=("Arial", 11, "bold"),
                                         bg="#253347", fg=self.gold)
        self.deck_count_label.pack(side=tk.LEFT, padx=(4, 0))

        exit_btn = tk.Button(top_right, text=T("exit_btn"), font=("Arial", 10, "bold"),
                  bg=self.danger, fg="white", padx=12, pady=5,
                  bd=0, cursor="hand2", relief=tk.FLAT,
                  command=self.exit_game)
        exit_btn.pack(side=tk.LEFT)
        self._register_lang(exit_btn, "exit_btn")

        # ── Scrollable felt area (dealer + players) ──
        scroll_outer = tk.Frame(self.table_frame, bg=self.felt)
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 0))

        scroll_canvas = tk.Canvas(scroll_outer, bg=self.felt, highlightthickness=0)
        v_scroll = tk.Scrollbar(scroll_outer, orient=tk.VERTICAL,
                                command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        felt_area = tk.Frame(scroll_canvas, bg=self.felt)
        felt_win = scroll_canvas.create_window((0, 0), window=felt_area, anchor="nw")

        def _on_felt_configure(e):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        felt_area.bind("<Configure>", _on_felt_configure)

        def _on_canvas_resize(e):
            scroll_canvas.itemconfig(felt_win, width=e.width)
        scroll_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(e):
            scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        def _on_mousewheel_linux(e):
            scroll_canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        scroll_canvas.bind_all("<Button-4>", _on_mousewheel_linux)
        scroll_canvas.bind_all("<Button-5>", _on_mousewheel_linux)

        # Store felt scroll handlers so tabs can restore them
        self._felt_scroll_fn     = _on_mousewheel
        self._felt_scroll_linux  = _on_mousewheel_linux
        self._felt_canvas        = scroll_canvas

        # Dealer zone
        dealer_zone = tk.Frame(felt_area, bg=self.felt)
        dealer_zone.pack(pady=(14, 6))

        dealer_header = tk.Frame(dealer_zone, bg=self.felt)
        dealer_header.pack()
        _dlbl = tk.Label(dealer_header, text=T("g_dealer"), font=("Arial", 11, "bold"),
                 bg=self.felt, fg="#9ca3af")
        _dlbl.pack(side=tk.LEFT, padx=6)
        self._register_lang(_dlbl, "g_dealer")
        self.dealer_value_label = tk.Label(dealer_header, text="",
                                           font=("Arial", 11, "bold"),
                                           bg=self.felt, fg=self.gold)
        self.dealer_value_label.pack(side=tk.LEFT)

        self.dealer_frame = tk.Frame(dealer_zone, bg=self.felt)
        self.dealer_frame.pack()
        self.dealer_cards_frame = tk.Frame(self.dealer_frame, bg=self.felt)
        self.dealer_cards_frame.pack(pady=6)

        # Divider
        tk.Frame(felt_area, bg="#2d4a3a", height=1).pack(fill=tk.X, padx=30, pady=2)

        # Players zone
        self.players_area = tk.Frame(felt_area, bg=self.felt)
        self.players_area.pack(fill=tk.BOTH, expand=True, pady=4)



        # ── Bottom controls bar ──
        ctrl_bar = tk.Frame(self.table_frame, bg=self.bg_table)
        ctrl_bar.pack(fill=tk.X, padx=16, pady=(0, 8))

        # Result label
        self.result_label = tk.Label(ctrl_bar, text="",
                                     font=("Arial", 14, "bold"),
                                     bg=self.bg_table, fg=self.gold,
                                     wraplength=700, justify=tk.CENTER)
        self.result_label.pack(pady=(6, 4))

        # Action buttons row
        btn_row = tk.Frame(ctrl_bar, bg=self.bg_table)
        btn_row.pack()

        def abtn(key, color, cmd, width=10):
            b = tk.Button(btn_row, text=T(key), font=("Arial", 12, "bold"),
                             bg=color, fg="white", width=width,
                             pady=9, bd=0, cursor="hand2", relief=tk.FLAT,
                             activebackground=color, command=cmd)
            self._register_lang(b, key)
            return b

        self.hit_btn    = abtn("g_hit",    self.success, self.hit,        8)
        self.stand_btn  = abtn("g_stand",  self.danger,  self.stand,      8)
        self.double_btn = abtn("g_double", "#d97706",    self.double_down, 8)
        self.hint_btn   = abtn("g_hint",   "#4b5563",    self.show_hint,   8)

        for b in (self.hit_btn, self.stand_btn, self.double_btn, self.hint_btn):
            b.pack(side=tk.LEFT, padx=4)

        self.replay_btn = tk.Button(ctrl_bar, text=T("g_play_again"),
                                    font=("Arial", 12, "bold"),
                                    bg=self.accent, fg="white",
                                    padx=24, pady=9, bd=0, cursor="hand2",
                                    relief=tk.FLAT, command=self.new_round)
        self._register_lang(self.replay_btn, "g_play_again")

        self.autoreplay_status = tk.Label(ctrl_bar, text="",
                                          font=("Arial", 10),
                                          bg=self.bg_table, fg="#60a5fa")
        self.autoreplay_status.pack(pady=(2, 0))

        self.new_round()

    # ──────────────────────────────────────────────
    # TABBED PANEL  — fully scrollable tabs
    # ──────────────────────────────────────────────
    def _build_tabbed_panel(self):
        """Right-hand tabbed panel: Settings / Bots / Stats / Auto — all scrollable."""
        PANEL_W = 285

        outer = tk.Frame(self.game_frame, bg=self.sb_bg, width=PANEL_W)
        outer.pack(side=tk.RIGHT, fill=tk.Y)
        outer.pack_propagate(False)

        # Tab strip
        tab_strip = tk.Frame(outer, bg=self.sb_tab_bg)
        tab_strip.pack(fill=tk.X)

        # Content area — holds one scrollable canvas per tab
        content = tk.Frame(outer, bg=self.sb_bg)
        content.pack(fill=tk.BOTH, expand=True)

        # Stable internal IDs — never translated, used as dict keys throughout
        TAB_IDS = ["settings", "bots", "stats", "auto"]
        TAB_ICONS = ["⚙", "🤖", "🏆", "⚡"]
        TAB_KEYS = ["tab_settings", "tab_bots", "tab_stats", "tab_auto"]

        self._tab_frames       = {}   # id → inner Frame
        self._tab_scroll_outer = {}   # id → outer Frame
        self._tab_buttons      = {}   # id → Button
        self._active_tab       = tk.StringVar(value=TAB_IDS[0])

        def _make_scrollable_tab(name):
            """Create a canvas+scrollbar wrapper; return the inner content Frame."""
            wrap = tk.Frame(content, bg=self.sb_bg)
            self._tab_scroll_outer[name] = wrap

            canvas = tk.Canvas(wrap, bg=self.sb_bg, highlightthickness=0,
                               width=PANEL_W - 18)
            vsb = tk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview)
            canvas.configure(yscrollcommand=vsb.set)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            inner = tk.Frame(canvas, bg=self.sb_bg, padx=10, pady=8)
            win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_inner_configure(e, c=canvas):
                c.configure(scrollregion=c.bbox("all"))
            def _on_canvas_resize(e, c=canvas, w=win_id):
                c.itemconfig(w, width=e.width)

            inner.bind("<Configure>", _on_inner_configure)
            canvas.bind("<Configure>", _on_canvas_resize)

            # Mouse-wheel scroll — bind/unbind on hover over this tab canvas
            def _scroll(e, c=canvas):
                if e.delta:
                    c.yview_scroll(int(-1 * (e.delta / 120)), "units")
                elif e.num == 4:
                    c.yview_scroll(-1, "units")
                elif e.num == 5:
                    c.yview_scroll(1, "units")

            def _bind_wheel(c=canvas, sc=_scroll):
                c.bind_all("<MouseWheel>",  sc)
                c.bind_all("<Button-4>",    sc)
                c.bind_all("<Button-5>",    sc)

            def _unbind_wheel(c=canvas):
                # Restore felt-area wheel bindings
                if hasattr(self, '_felt_scroll_fn'):
                    c.bind_all("<MouseWheel>",  self._felt_scroll_fn)
                    c.bind_all("<Button-4>",     self._felt_scroll_linux)
                    c.bind_all("<Button-5>",     self._felt_scroll_linux)
                else:
                    c.unbind_all("<MouseWheel>")
                    c.unbind_all("<Button-4>")
                    c.unbind_all("<Button-5>")

            wrap._bind_wheel   = _bind_wheel
            wrap._unbind_wheel = _unbind_wheel
            return inner

        for tab_id in TAB_IDS:
            inner = _make_scrollable_tab(tab_id)
            self._tab_frames[tab_id] = inner

        def switch_tab(tab_id):
            self._active_tab.set(tab_id)
            for tid, wrap in self._tab_scroll_outer.items():
                if tid == tab_id:
                    wrap.pack(fill=tk.BOTH, expand=True)
                    wrap._bind_wheel()
                else:
                    wrap._unbind_wheel()
                    wrap.pack_forget()
            for tid, b in self._tab_buttons.items():
                active = (tid == tab_id)
                b.config(bg=self.sb_bg if active else self.sb_tab_bg,
                         fg="white" if active else self.text_dim)

        # Tab buttons — keyed by stable ID, text updated by language system
        for tab_id, icon, key in zip(TAB_IDS, TAB_ICONS, TAB_KEYS):
            b = tk.Button(tab_strip, text=f"{icon}\n{T(key)}",
                          font=("Arial", 8, "bold"),
                          bg=self.sb_tab_bg, fg=self.text_dim,
                          bd=0, padx=0, pady=8, cursor="hand2",
                          relief=tk.FLAT, activebackground=self.sb_bg,
                          command=lambda tid=tab_id: switch_tab(tid))
            b.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._tab_buttons[tab_id] = b
            self._register_lang(b, key)  # will update text=T(key) — loses icon prefix
            # Override: register a custom updater that keeps the icon
            self._lang_widgets[-1] = (b, key, icon)  # store icon too

        # Populate each tab using stable IDs
        self._build_tab_settings(self._tab_frames["settings"])
        self._build_tab_bots    (self._tab_frames["bots"])
        self._build_tab_stats   (self._tab_frames["stats"])
        self._build_tab_auto    (self._tab_frames["auto"])

        switch_tab(TAB_IDS[0])

    # ── helpers ──
    def _sb_label(self, parent, text, small=False):
        tk.Label(parent, text=text, font=("Arial", 9 if small else 10),
                 bg=self.sb_bg, fg="#9ca3af", anchor=tk.W).pack(fill=tk.X, pady=(6, 1))

    def _sb_sep(self, parent):
        tk.Frame(parent, bg="#1f2937", height=1).pack(fill=tk.X, pady=6)

    def _sb_btn(self, parent, text, color, cmd, pady=6):
        tk.Button(parent, text=text, font=("Arial", 10, "bold"),
                  bg=color, fg="white", bd=0, pady=pady,
                  cursor="hand2", relief=tk.FLAT, activebackground=color,
                  command=cmd).pack(fill=tk.X, pady=(3, 0))

    # ── Settings tab ──
    def _build_tab_settings(self, f):
        # All labels stored so _set_language can update them
        _lbl_decks = tk.Label(f, text=T("s_decks"), font=("Arial", 9),
                              bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _lbl_decks.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_lbl_decks, "s_decks")
        tk.Spinbox(f, from_=1, to=250, textvariable=self.num_decks,
                   font=("Arial", 11), width=6,
                   bg="#1f2937", fg="white", insertbackground="white",
                   buttonbackground="#374151").pack(anchor=tk.W)

        _lbl_bots = tk.Label(f, text=T("s_bots"), font=("Arial", 9),
                             bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _lbl_bots.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_lbl_bots, "s_bots")
        tk.Spinbox(f, from_=0, to=100, textvariable=self.num_bots,
                   font=("Arial", 11), width=6,
                   bg="#1f2937", fg="white", insertbackground="white",
                   buttonbackground="#374151").pack(anchor=tk.W)

        _lbl_name = tk.Label(f, text=T("s_your_name"), font=("Arial", 9),
                             bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _lbl_name.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_lbl_name, "s_your_name")
        tk.Entry(f, textvariable=self.player_name,
                 font=("Arial", 10), bg="#1f2937", fg="white",
                 insertbackground="white", relief=tk.FLAT,
                 bd=4).pack(fill=tk.X)

        # Human toggle — Checkbutton with lang support
        chk_row = tk.Frame(f, bg=self.sb_bg)
        chk_row.pack(fill=tk.X, pady=(8, 0))
        self._play_self_chk = tk.Checkbutton(chk_row, text=T("s_play_self"),
                       variable=self.human_plays,
                       font=("Arial", 10), bg=self.sb_bg, fg="white",
                       selectcolor="#374151", activebackground=self.sb_bg,
                       command=self._on_human_toggle)
        self._play_self_chk.pack(side=tk.LEFT)
        self._register_lang(self._play_self_chk, "s_play_self")

        self._sb_sep(f)

        _lbl_speed = tk.Label(f, text=T("s_anim_speed"), font=("Arial", 9),
                              bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _lbl_speed.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_lbl_speed, "s_anim_speed")
        speed_row = tk.Frame(f, bg=self.sb_bg)
        speed_row.pack(fill=tk.X)
        self._speed_label = tk.Label(speed_row, text=f"{self.anim_speed.get()}ms",
                                     font=("Arial", 9), bg=self.sb_bg,
                                     fg=self.success, width=5)
        self._speed_label.pack(side=tk.RIGHT)
        tk.Scale(speed_row, variable=self.anim_speed,
                 from_=10, to=1500, orient=tk.HORIZONTAL,
                 bg=self.sb_bg, fg="white", troughcolor="#374151",
                 highlightthickness=0, bd=0, length=150, showvalue=False,
                 command=lambda v: self._speed_label.config(text=f"{v}ms")
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._sb_sep(f)

        # Restart and tutorial buttons — registered for lang update
        _restart_btn = tk.Button(f, text=T("s_restart"), font=("Arial", 10, "bold"),
                  bg="#374151", fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground="#374151",
                  command=self._restart_table)
        _restart_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_restart_btn, "s_restart")

        _tutorial_btn = tk.Button(f, text=T("s_tutorial"), font=("Arial", 10, "bold"),
                  bg=self.accent2, fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground=self.accent2,
                  command=self.open_tutorial)
        _tutorial_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_tutorial_btn, "s_tutorial")

        self._sb_sep(f)

        # Save to TXT file (autoplay only)
        _save_file_btn = tk.Button(f, text=T("s_save_stats"), font=("Arial", 10, "bold"),
                  bg="#7c5cbf", fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground="#7c5cbf",
                  command=self.save_stats_to_file)
        _save_file_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_save_file_btn, "s_save_stats")

        # Save to SQLite
        _save_sqlite_btn = tk.Button(f, text=T("s_save_sqlite"), font=("Arial", 10, "bold"),
                  bg="#1a6b4a", fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground="#1a6b4a",
                  command=self.save_stats_to_sqlite)
        _save_sqlite_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_save_sqlite_btn, "s_save_sqlite")

        # Save to Excel
        _save_excel_btn = tk.Button(f, text=T("s_save_excel"), font=("Arial", 10, "bold"),
                  bg="#1d6a9a", fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground="#1d6a9a",
                  command=self.save_stats_to_excel)
        _save_excel_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_save_excel_btn, "s_save_excel")

        # Save to CSV
        _save_csv_btn = tk.Button(f, text=T("s_save_csv"), font=("Arial", 10, "bold"),
                  bg="#5a7a3a", fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground="#5a7a3a",
                  command=self.save_stats_to_csv)
        _save_csv_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_save_csv_btn, "s_save_csv")

        self.save_status_label = tk.Label(f, text="", font=("Arial", 8),
                                          bg=self.sb_bg, fg=self.success, wraplength=230)
        self.save_status_label.pack(anchor=tk.W, pady=(3, 0))

    # ── Bots tab ──
    def _build_tab_bots(self, f):
        self._bot_strat_buttons_frame = tk.Frame(f, bg=self.sb_bg)
        self._bot_strat_buttons_frame.pack(fill=tk.X, expand=True)

    # ── Stats tab ──
    def _build_tab_stats(self, f):
        # ── Summary row: Dealer / Draws ──
        summary = tk.Frame(f, bg=self.sb_bg)
        summary.pack(fill=tk.X)

        self.dealer_wins_label = tk.Label(summary, text=T("st_dealer") + "0",
                                          font=("Arial", 10, "bold"),
                                          bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        self.dealer_wins_label.pack(fill=tk.X)
        self.draws_label = tk.Label(summary, text=T("st_draws") + "0",
                                    font=("Arial", 9),
                                    bg=self.sb_bg, fg=self.text_dim, anchor=tk.W)
        self.draws_label.pack(fill=tk.X)

        self._sb_sep(f)

        # ── Column headers ──
        hdr = tk.Frame(f, bg="#1f2937")
        hdr.pack(fill=tk.X, pady=(0, 2))
        _player_col_lbl = tk.Label(hdr, text=T("st_player_col"), font=("Arial", 8, "bold"),
                 bg="#1f2937", fg="#9ca3af", anchor=tk.W, width=10)
        _player_col_lbl.grid(row=0, column=0, sticky="w", padx=(4,2))
        self._register_lang(_player_col_lbl, "st_player_col")
        for ci, (key, col_w) in enumerate([("st_win_col", 6), ("st_lose_col", 6), ("st_draw_col", 6), ("st_pct_col", 6)]):
            _col_lbl = tk.Label(hdr, text=T(key), font=("Arial", 8, "bold"),
                     bg="#1f2937", fg="#9ca3af", width=col_w, anchor=tk.E
                     )
            _col_lbl.grid(row=0, column=ci+1, sticky="e", padx=1)
            self._register_lang(_col_lbl, key)

        # ── Human player row ──
        self._stats_player_row = self._make_stats_row(f)

        # ── Bot rows container (rebuilt on new_round) ──
        self._stats_bots_frame = tk.Frame(f, bg=self.sb_bg)
        self._stats_bots_frame.pack(fill=tk.X)
        self._stats_bot_rows: list = []   # list of (name_lbl, win_lbl, lose_lbl, draw_lbl, pct_lbl)

        self._sb_sep(f)

        # ── Card distribution ──
        _card_dist_lbl = tk.Label(f, text=T("st_card_dist"), font=("Arial", 9),
                 bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _card_dist_lbl.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_card_dist_lbl, "st_card_dist")
        self.card_stats_frame = tk.Frame(f, bg=self.sb_bg)
        self.card_stats_frame.pack(fill=tk.X)

        self._sb_sep(f)
        _clear_btn = tk.Button(f, text=T("st_clear"), font=("Arial", 10, "bold"),
                  bg=self.danger, fg="white", bd=0, pady=5,
                  cursor="hand2", relief=tk.FLAT, activebackground=self.danger,
                  command=self.reset_stats)
        _clear_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_clear_btn, "st_clear")

    def _make_stats_row(self, parent, name="—"):
        """Create one W/L/D/% row, return tuple of labels."""
        row = tk.Frame(parent, bg=self.sb_bg)
        row.pack(fill=tk.X, pady=1)
        name_lbl = tk.Label(row, text=name, font=("Arial", 8, "bold"),
                             bg=self.sb_bg, fg="white", anchor=tk.W, width=10)
        name_lbl.grid(row=0, column=0, sticky="w", padx=(2, 2))
        win_lbl  = tk.Label(row, text="0", font=("Arial", 8),
                             bg=self.sb_bg, fg=self.success, width=6, anchor=tk.E)
        win_lbl.grid(row=0, column=1, sticky="e", padx=1)
        lose_lbl = tk.Label(row, text="0", font=("Arial", 8),
                             bg=self.sb_bg, fg=self.danger, width=6, anchor=tk.E)
        lose_lbl.grid(row=0, column=2, sticky="e", padx=1)
        draw_lbl = tk.Label(row, text="0", font=("Arial", 8),
                             bg=self.sb_bg, fg=self.text_dim, width=6, anchor=tk.E)
        draw_lbl.grid(row=0, column=3, sticky="e", padx=1)
        pct_lbl  = tk.Label(row, text="—%", font=("Arial", 8),
                             bg=self.sb_bg, fg=self.gold, width=6, anchor=tk.E)
        pct_lbl.grid(row=0, column=4, sticky="e", padx=(1, 4))
        return (name_lbl, win_lbl, lose_lbl, draw_lbl, pct_lbl)

    def _refresh_stats_bot_rows(self):
        """Rebuild bot rows in Stats tab to match current bot count."""
        frame = self._stats_bots_frame
        for w in frame.winfo_children():
            w.destroy()
        self._stats_bot_rows = []
        n = max(len(self.bot_wins), self.num_bots.get())
        for i in range(n):
            bname = (self.bot_names[i].get().strip()
                     if i < len(self.bot_names) else "") or f"Bot {i+1}"
            row_lbls = self._make_stats_row(frame, bname)
            self._stats_bots_frame.pack_configure(fill=tk.X)
            self._stats_bot_rows.append(row_lbls)

    # ── Auto tab ──
    def _build_tab_auto(self, f):
        _a_games_lbl = tk.Label(f, text=T("a_games"), font=("Arial", 9),
                 bg=self.sb_bg, fg="#9ca3af", anchor=tk.W)
        _a_games_lbl.pack(fill=tk.X, pady=(6, 1))
        self._register_lang(_a_games_lbl, "a_games")
        tk.Spinbox(f, from_=1, to=100000, textvariable=self.autoreplay_count,
                   font=("Arial", 11), width=12,
                   bg="#1f2937", fg="white", insertbackground="white",
                   buttonbackground="#374151").pack(anchor=tk.W, pady=(0, 6))

        _start_btn = tk.Button(f, text=T("a_start"), font=("Arial", 10, "bold"),
                  bg=self.accent, fg="white", bd=0, pady=8,
                  cursor="hand2", relief=tk.FLAT, activebackground=self.accent,
                  command=self.start_autoreplay)
        _start_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_start_btn, "a_start")

        _stop_btn = tk.Button(f, text=T("a_stop"), font=("Arial", 10, "bold"),
                  bg=self.danger, fg="white", bd=0, pady=6,
                  cursor="hand2", relief=tk.FLAT, activebackground=self.danger,
                  command=self.stop_autoreplay)
        _stop_btn.pack(fill=tk.X, pady=(3, 0))
        self._register_lang(_stop_btn, "a_stop")

        pb_frame = tk.Frame(f, bg=self.sb_bg)
        pb_frame.pack(fill=tk.X, pady=(10, 0))
        self._progressbar = ttk.Progressbar(pb_frame, orient=tk.HORIZONTAL,
                                            mode="determinate", length=230)
        self._progressbar.pack(fill=tk.X)
        self._progress_lbl = tk.Label(pb_frame, text="", font=("Arial", 9),
                                      bg=self.sb_bg, fg="#60a5fa")
        self._progress_lbl.pack(anchor=tk.W, pady=(3, 0))

    # ──────────────────────────────────────────────
    # SIDEBAR (legacy alias — no longer used, kept for compat)
    # ──────────────────────────────────────────────
    def _build_sidebar(self):
        pass  # replaced by _build_tabbed_panel

    def _on_human_toggle(self):
        pass  # just a visual toggle; applied on next round via _apply_settings

    def _refresh_bot_strategy_buttons(self):
        """Rebuild the per-bot name + preset selector rows in the sidebar."""
        frame = self._bot_strat_buttons_frame
        for w in frame.winfo_children():
            w.destroy()

        n = max(len(self.bots), self.num_bots.get())
        if n == 0:
            tk.Label(frame, text=T("b_no_bots"), font=("Arial", 9),
                     bg=self.sb_bg, fg=self.text_dim).pack(anchor=tk.W)
            return

        # Ensure strategies and preset trackers exist
        while len(self.bot_strategies) < n:
            self.bot_strategies.append(BotStrategy())
        while len(self._bot_preset_vars) < n:
            self._bot_preset_vars.append(tk.StringVar(value="🎯 Pamata"))
        while len(self.bot_names) < n:
            self.bot_names.append(tk.StringVar(value=f"Bot {len(self.bot_names)+1}"))

        for i in range(n):
            # Separator between bots
            if i > 0:
                tk.Frame(frame, bg="#1f2937", height=1).pack(fill=tk.X, pady=4)

            # Bot name row
            name_row = tk.Frame(frame, bg=self.sb_bg)
            name_row.pack(fill=tk.X, pady=(4, 1))
            tk.Label(name_row, text=f"#{i+1}", font=("Arial", 8, "bold"),
                     bg=self.sb_bg, fg=self.gold, width=3).pack(side=tk.LEFT)
            tk.Entry(name_row, textvariable=self.bot_names[i],
                     font=("Arial", 9), width=14,
                     bg="#1f2937", fg="white", insertbackground="white",
                     relief=tk.FLAT, bd=3).pack(side=tk.LEFT)

            # Strategy row
            strat_row = tk.Frame(frame, bg=self.sb_bg)
            strat_row.pack(fill=tk.X, pady=(2, 0))

            var = self._bot_preset_vars[i]
            menu = tk.OptionMenu(strat_row, var, *PRESET_NAMES,
                                 command=lambda val, ii=i: self._apply_preset(ii, val))
            menu.config(font=("Arial", 8), bg="#1f2937", fg="white",
                        activebackground="#374151", activeforeground="white",
                        highlightthickness=0, bd=0, padx=2, pady=2, width=13)
            menu["menu"].config(bg="#1f2937", fg="white", font=("Arial", 9),
                                activebackground=self.accent)
            menu.pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Button(strat_row, text="✏️", font=("Arial", 9),
                      bg=self.accent2, fg="white", padx=5, pady=2,
                      bd=0, cursor="hand2", relief=tk.FLAT,
                      command=lambda ii=i: self._open_strategy_editor(ii)
                      ).pack(side=tk.LEFT, padx=(3, 0))

    def _apply_preset(self, bot_index: int, preset_name: str):
        """Apply a named preset to a bot's strategy."""
        while len(self.bot_strategies) <= bot_index:
            self.bot_strategies.append(BotStrategy())
        if preset_name != "✏️ Custom":
            self.bot_strategies[bot_index] = _make_preset(preset_name)

    def _open_strategy_editor(self, bot_index: int):
        """Open the full strategy editor popup for the given bot."""
        while len(self.bot_strategies) <= bot_index:
            self.bot_strategies.append(BotStrategy())
        # Switch preset label to Custom
        if hasattr(self, '_bot_preset_vars') and bot_index < len(self._bot_preset_vars):
            self._bot_preset_vars[bot_index].set("✏️ Custom")
        StrategyEditorWindow(
            self.root,
            self.bot_strategies[bot_index],
            f"Bot {bot_index + 1}",
            app=self,
            on_close=lambda: None
        )


    def _restart_table(self):
        try:
            d = self.num_decks.get()
            b = self.num_bots.get()
            if d < 1 or b < 0: raise ValueError
        except Exception:
            messagebox.showerror(T("d_error"), T("d_invalid_settings"))
            return
        if d > 250:
            messagebox.showerror(T("d_error"), T("d_max_decks"))
            self.num_decks.set(250)
            return
        if b > 100:
            messagebox.showerror(T("d_error"), T("d_max_bots"))
            self.num_bots.set(100)
            return
        self._autoreplay_running = False
        self._autoreplay_remaining = 0
        self.new_round()

    # ──────────────────────────────────────────────
    # PLAYER LAYOUT  (adaptive scaling)
    # ──────────────────────────────────────────────
    def create_player_frames(self):
        for w in self.players_area.winfo_children():
            w.destroy()

        self.bot_frames       = []
        self.bot_cards_frames = []
        self.bot_value_labels = []
        self.player_frame       = None
        self.player_cards_frame = None
        self.player_value_label = None

        human     = self.human_plays.get()
        num_bots  = self.num_bots.get()
        total     = (1 if human else 0) + num_bots

        scale, per_row = _compute_scale(total)

        # Derived sizes
        card_w  = max(22, int(62  * scale))
        card_h  = max(32, int(92  * scale))
        card_fs = max(7,  int(20  * scale))
        frame_px= max(2,  int(8   * scale))
        frame_py= max(2,  int(6   * scale))
        name_fs = max(7,  int(13  * scale))
        val_fs  = max(6,  int(11  * scale))

        all_slots = []
        if human:
            all_slots.append("player")
        for i in range(num_bots):
            all_slots.append(f"bot_{i}")

        rows = [all_slots[i:i+per_row] for i in range(0, len(all_slots), per_row)]

        for row_slots in rows:
            row_frame = tk.Frame(self.players_area, bg=self.felt)
            row_frame.pack(pady=4)

            for slot in row_slots:
                if slot == "player":
                    self.player_frame = tk.Frame(
                        row_frame, bg=self.felt,
                        highlightbackground=self.accent,
                        highlightthickness=2,
                        padx=frame_px, pady=frame_py)
                    self.player_frame.pack(side=tk.LEFT, padx=6)

                    pname = self.player_name.get().strip() or "Spēlētājs"
                    tk.Label(self.player_frame, text=pname,
                             font=("Arial", name_fs, "bold"),
                             bg=self.felt, fg=self.accent).pack(pady=1)

                    self.player_value_label = tk.Label(
                        self.player_frame, text="",
                        font=("Arial", val_fs), bg=self.felt, fg="#d1d5db")
                    self.player_value_label.pack()

                    self.player_cards_frame = tk.Frame(self.player_frame, bg=self.felt)
                    self.player_cards_frame.pack(pady=2)

                    self.player_cards_frame._cw = card_w
                    self.player_cards_frame._ch = card_h
                    self.player_cards_frame._cfs= card_fs

                else:
                    idx = int(slot.split("_")[1])
                    bf = tk.Frame(row_frame, bg=self.felt,
                                  highlightbackground=self.gold,
                                  highlightthickness=2,
                                  padx=frame_px, pady=frame_py)
                    bf.pack(side=tk.LEFT, padx=6)

                    bname = (self.bot_names[idx].get().strip()
                             if idx < len(self.bot_names) else "") or f"Bot {idx+1}"
                    tk.Label(bf, text=bname,
                             font=("Arial", name_fs, "bold"),
                             bg=self.felt, fg=self.gold).pack(pady=1)

                    bvl = tk.Label(bf, text="",
                                   font=("Arial", val_fs), bg=self.felt, fg="#d1d5db")
                    bvl.pack()

                    bcf = tk.Frame(bf, bg=self.felt)
                    bcf.pack(pady=2)
                    bcf._cw  = card_w
                    bcf._ch  = card_h
                    bcf._cfs = card_fs

                    self.bot_frames.append(bf)
                    self.bot_cards_frames.append(bcf)
                    self.bot_value_labels.append(bvl)

        # Store scale for dealer cards (always full-size)
        self.dealer_cards_frame._cw  = 62
        self.dealer_cards_frame._ch  = 92
        self.dealer_cards_frame._cfs = 20

    # ──────────────────────────────────────────────
    # CARD DRAWING & ANIMATION
    # ──────────────────────────────────────────────
    def _card_size(self, frame):
        """Get card dimensions from parent frame metadata."""
        w   = getattr(frame, '_cw',  62)
        h   = getattr(frame, '_ch',  92)
        fs  = getattr(frame, '_cfs', 20)
        return w, h, fs

    def _animate_card_in(self, frame, label, final_text, final_color, fs, callback=None):
        """
        4-step flip:  back  →  half-visible  →  blur  →  front
        Delay between each step = max(12, speed // 5)
        """
        speed = self.anim_speed.get()
        step_delay = max(12, speed // 5)

        steps  = ["🂠",    "▓▓",    "░░",    final_text]
        colors = ["#6a0dad", "#a080c0", "#c0b0d0", final_color]
        fss    = [fs,       fs-2,    fs-1,    fs]

        def do_step(i=0):
            if not frame.winfo_exists():
                return
            label.config(text=steps[i], fg=colors[i],
                         font=("Arial", max(6, fss[i]), "bold"))
            if i < len(steps) - 1:
                frame.after(step_delay, lambda: do_step(i + 1))
            else:
                if callback:
                    frame.after(step_delay, callback)
        do_step()

    def draw_card_animated(self, card: Card, parent_frame, hidden=False, callback=None):
        # During autoreplay skip animation entirely for maximum speed
        if self._autoreplay_running:
            self.draw_card(card, parent_frame, hidden=hidden)
            if callback:
                parent_frame.after(1, callback)
            return

        w, h, fs = self._card_size(parent_frame)

        cf = tk.Frame(parent_frame, bg=self.card_bg,
                      width=w, height=h,
                      highlightbackground="#777",
                      highlightthickness=1)
        cf.pack(side=tk.LEFT, padx=max(1, w // 15))
        cf.pack_propagate(False)

        if hidden:
            lbl = tk.Label(cf, text="🂠",
                           font=("Arial", fs, "bold"),
                           bg=self.card_bg, fg="#6a0dad")
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            cf._hidden_label = lbl
            cf._card = card
            cf._fs   = fs
            speed = self.anim_speed.get()
            if callback:
                cf.after(max(10, speed // 3), callback)
        else:
            text  = f"{card.rank}{card.suit}"
            color = "#e74c3c" if card.is_red() else "#2c3e50"
            lbl = tk.Label(cf, text="🂠",
                           font=("Arial", fs, "bold"),
                           bg=self.card_bg, fg="#6a0dad")
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self._animate_card_in(cf, lbl, text, color, fs, callback)

        return cf

    def reveal_card_frame(self, cf):
        if not hasattr(cf, '_hidden_label') or not hasattr(cf, '_card'):
            return
        card  = cf._card
        fs    = getattr(cf, '_fs', 20)
        text  = f"{card.rank}{card.suit}"
        color = "#e74c3c" if card.is_red() else "#2c3e50"
        if self._autoreplay_running:
            cf._hidden_label.config(text=text, fg=color,
                                    font=("Arial", fs, "bold"))
        else:
            self._animate_card_in(cf, cf._hidden_label, text, color, fs)

    def draw_card(self, card: Card, parent_frame, hidden=False):
        """Instant (non-animated) draw."""
        w, h, fs = self._card_size(parent_frame)
        cf = tk.Frame(parent_frame, bg=self.card_bg,
                      width=w, height=h,
                      highlightbackground="#777",
                      highlightthickness=1)
        cf.pack(side=tk.LEFT, padx=max(1, w // 15))
        cf.pack_propagate(False)

        text  = "🂠" if hidden else f"{card.rank}{card.suit}"
        color = ("#6a0dad" if hidden
                 else ("#e74c3c" if card.is_red() else "#2c3e50"))
        tk.Label(cf, text=text, font=("Arial", fs, "bold"),
                 bg=self.card_bg, fg=color).place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        if hidden:
            cf._hidden_label = cf.winfo_children()[-1]
            cf._card = card
            cf._fs   = fs

    # ──────────────────────────────────────────────
    # DISPLAY UPDATE
    # ──────────────────────────────────────────────
    def clear_cards(self):
        for w in self.dealer_cards_frame.winfo_children(): w.destroy()
        if self.player_cards_frame:
            for w in self.player_cards_frame.winfo_children(): w.destroy()
        for bcf in self.bot_cards_frames:
            for w in bcf.winfo_children(): w.destroy()

    def update_display(self, hide_dealer=False):
        self.clear_cards()
        if hide_dealer and len(self.dealer.cards) >= 2:
            self.draw_card(self.dealer.cards[0], self.dealer_cards_frame, hidden=True)
            self.draw_card(self.dealer.cards[1], self.dealer_cards_frame)
            for c in self.dealer.cards[2:]:
                self.draw_card(c, self.dealer_cards_frame)
            self.dealer_value_label.config(text=T("g_showing") + str(self.dealer.cards[1].value))
        else:
            for c in self.dealer.cards:
                self.draw_card(c, self.dealer_cards_frame)
            self.dealer_value_label.config(text=T("g_total") + str(self.dealer.get_value()))

        if self.player and self.player_cards_frame:
            for c in self.player.cards:
                self.draw_card(c, self.player_cards_frame)
            if self.player_value_label:
                self.player_value_label.config(text=T("g_total") + str(self.player.get_value()))

        for i, bot in enumerate(self.bots):
            if i < len(self.bot_cards_frames):
                for c in bot.cards:
                    self.draw_card(c, self.bot_cards_frames[i])
            if i < len(self.bot_value_labels):
                self.bot_value_labels[i].config(text=T("g_total") + str(bot.get_value()))

        self.update_deck_counter()

    def update_deck_counter(self):
        if self.deck:
            self.deck_count_label.config(text=str(self.deck.cards_remaining()))
            self.update_card_stats()

    def update_card_stats(self):
        if not self.deck: return
        for w in self.card_stats_frame.winfo_children(): w.destroy()
        vc = {}
        for c in self.deck.cards:
            vc[c.value] = vc.get(c.value, 0) + 1
        total = len(self.deck.cards)
        if not total: return
        for val in sorted(vc):
            pct = vc[val] / total * 100
            row = tk.Frame(self.card_stats_frame, bg=self.sb_bg)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=f"{val}:", font=("Arial", 9),
                     bg=self.sb_bg, fg="#9ca3af", width=3, anchor=tk.W).pack(side=tk.LEFT)
            # Mini bar
            bar_outer = tk.Frame(row, bg="#1f2937", height=8, width=80)
            bar_outer.pack(side=tk.LEFT, padx=4, pady=2)
            bar_outer.pack_propagate(False)
            bar_w = max(2, int(pct / 100 * 80))
            tk.Frame(bar_outer, bg=self.accent, width=bar_w).pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(row, text=f"{pct:.0f}%", font=("Arial", 8),
                     bg=self.sb_bg, fg=self.success, width=4, anchor=tk.E).pack(side=tk.RIGHT)

    # ──────────────────────────────────────────────
    # ACTIVE PLAYER HIGHLIGHT
    # ──────────────────────────────────────────────
    def set_active_player(self, idx):
        if self.player_frame:
            self.player_frame.config(highlightbackground=self.accent, highlightthickness=2)
        for bf in self.bot_frames:
            bf.config(highlightbackground=self.gold, highlightthickness=2)
        self.dealer_frame.config(highlightbackground="#4b5563", highlightthickness=2)

        if idx == -1 and self.player_frame:
            self.player_frame.config(highlightbackground=self.success, highlightthickness=3)
        elif idx is None:
            self.dealer_frame.config(highlightbackground=self.success, highlightthickness=3)
        elif isinstance(idx, int) and 0 <= idx < len(self.bot_frames):
            self.bot_frames[idx].config(highlightbackground=self.success, highlightthickness=3)

    def update_bot_wins_labels(self):
        """Refresh the Stats tab bot rows to match current bot list."""
        self._refresh_stats_bot_rows()
        self.update_stats()

    # ──────────────────────────────────────────────
    # NEW ROUND  (animated deal OR silent autoreplay)
    # ──────────────────────────────────────────────
    def new_round(self):
        self.playing = True
        self.result_label.config(text="")
        self.replay_btn.pack_forget()

        self.deck   = Deck(self.num_decks.get())
        self.dealer = Hand("Dealer")
        human       = self.human_plays.get()
        self.player = Hand("Player") if human else None
        num_bots    = self.num_bots.get()
        self.bots   = [Hand(f"Bot {i+1}") for i in range(num_bots)]

        while len(self.bot_wins) < num_bots:
            self.bot_wins.append(0)
        # Ensure a strategy exists for every bot
        while len(self.bot_strategies) < num_bots:
            self.bot_strategies.append(BotStrategy())
        self._refresh_bot_strategy_buttons()

        # Always use animated path (autoreplay bypasses new_round entirely)
        self._run_round_animated(human, num_bots)

    def _run_round_animated(self, human, num_bots):
        """Normal animated deal path."""
        self.create_player_frames()
        self.update_bot_wins_labels()

        # Build interleaved deal sequence
        interleaved = []
        for slot_type in ("first", "second"):
            if human:
                interleaved.append(("player", slot_type))
            for i in range(num_bots):
                interleaved.append((f"bot_{i}", slot_type))
            interleaved.append(("dealer", slot_type))

        cards_to_deal = []
        for slot, _ in interleaved:
            card = self.deck.deal()
            if slot == "player":
                self.player.cards.append(card)
            elif slot == "dealer":
                self.dealer.cards.append(card)
            else:
                self.bots[int(slot.split("_")[1])].cards.append(card)
            is_hidden = (slot == "dealer" and len(self.dealer.cards) == 1)
            cards_to_deal.append((slot, card, is_hidden))

        # Clear UI
        self.clear_cards()
        self.dealer_value_label.config(text="")
        if self.player_value_label:
            self.player_value_label.config(text="")
        for lbl in self.bot_value_labels:
            lbl.config(text="")
        self.update_deck_counter()

        def deal_next(i=0):
            if i >= len(cards_to_deal):
                self._finish_deal_setup()
                return
            slot, card, hidden = cards_to_deal[i]
            if slot == "player":
                frame = self.player_cards_frame
            elif slot == "dealer":
                frame = self.dealer_cards_frame
            else:
                frame = self.bot_cards_frames[int(slot.split("_")[1])]
            self.draw_card_animated(card, frame, hidden=hidden,
                                    callback=lambda: deal_next(i + 1))

        deal_next()

    def _finish_deal_setup(self):
        if self.player and self.player_value_label:
            self.player_value_label.config(text=f"Total: {self.player.get_value()}")
        for i, lbl in enumerate(self.bot_value_labels):
            lbl.config(text=f"Total: {self.bots[i].get_value()}")
        if len(self.dealer.cards) >= 2:
            self.dealer_value_label.config(
                text=f"Showing: {self.dealer.cards[1].value}")
        self.update_deck_counter()

        human = self.human_plays.get()
        if human:
            self.set_active_player(-1)
            self.enable_buttons()
            if self.dealer.is_blackjack():
                self.dealer_blackjack()
            elif self.player.is_blackjack():
                self.result_label.config(text="Tu: Blackjack! (Auto-stand)")
                self.stand()
        else:
            # No human — bots play immediately
            self.disable_buttons()
            self.play_bots_sequentially()

    # ──────────────────────────────────────────────
    # BUTTONS
    # ──────────────────────────────────────────────
    def enable_buttons(self):
        if not self.human_plays.get():
            self.disable_buttons()
            return
        self.hit_btn.config(state=tk.NORMAL)
        self.stand_btn.config(state=tk.NORMAL)
        self.hint_btn.config(state=tk.NORMAL)
        self.double_btn.config(
            state=tk.NORMAL if self.player and len(self.player.cards) == 2
            else tk.DISABLED)

    def disable_buttons(self):
        for b in (self.hit_btn, self.stand_btn, self.double_btn, self.hint_btn):
            b.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────
    # PLAYER ACTIONS
    # ──────────────────────────────────────────────
    def hit(self):
        if not self.playing or not self.player: return
        card = self.deck.deal()
        self.player.cards.append(card)
        self.draw_card_animated(card, self.player_cards_frame)
        if self.player_value_label:
            self.player_value_label.config(text=f"Total: {self.player.get_value()}")
        self.update_deck_counter()
        self.set_active_player(-1)
        if self.player.is_bust():
            self.result_label.config(text="Bust! Tu pārsniedzi 21!")
            self.disable_buttons()
            self.root.after(self._speed() + 200, self.play_bots_sequentially)
        elif self.player.get_value() == 21:
            self.stand()
        else:
            self.double_btn.config(state=tk.DISABLED)

    def stand(self):
        if not self.playing: return
        self.disable_buttons()
        self.play_bots_sequentially()

    def double_down(self):
        if not self.playing or not self.player or len(self.player.cards) != 2: return
        card = self.deck.deal()
        self.player.cards.append(card)
        self.draw_card_animated(card, self.player_cards_frame)
        if self.player_value_label:
            self.player_value_label.config(text=f"Total: {self.player.get_value()}")
        self.update_deck_counter()
        self.disable_buttons()
        self.root.after(self._speed() + 200, self.play_bots_sequentially)

    def show_hint(self):
        if not self.playing or not self.player or len(self.dealer.cards) < 2: return
        upcard   = self.dealer.cards[1].value
        total    = self.player.get_value()
        can_dbl  = len(self.player.cards) == 2
        action   = Strategy.get_action(total, upcard, self.player.can_split(),
                                       can_dbl, self.player.is_soft(), self.player)
        hints = {'H': '💡 Hit', 'S': '💡 Stand', 'D': '💡 Double Down', 'SP': '💡 Split'}
        messagebox.showinfo("Padoms", hints.get(action, '?'))

    # ──────────────────────────────────────────────
    # BOT PLAY
    # ──────────────────────────────────────────────
    def _speed(self):
        return max(10, self.anim_speed.get())

    def play_bots_sequentially(self, bot_index=0):
        if bot_index >= len(self.bots):
            self.root.after(self._speed() // 2, self.dealer_play_animated)
            return
        self.set_active_player(bot_index)
        if self.bots[bot_index].is_blackjack():
            self.root.after(self._speed(), lambda: self.play_bots_sequentially(bot_index + 1))
            return
        self.bot_play_animated(bot_index)

    def bot_play_animated(self, bot_index):
        bot = self.bots[bot_index]

        def make_move():
            if not self.playing: return
            total = bot.get_value()
            if total >= 21:
                self.root.after(self._speed() // 2,
                                lambda: self.play_bots_sequentially(bot_index + 1))
                return
            upcard   = self.dealer.cards[1].value
            can_dbl  = len(bot.cards) == 2
            # Use this bot's personal strategy table
            strat = (self.bot_strategies[bot_index]
                     if bot_index < len(self.bot_strategies)
                     else BotStrategy())
            action   = strat.get_action(total, upcard, False, can_dbl,
                                        bot.is_soft(), bot)
            if action == 'S':
                self.root.after(self._speed() // 2,
                                lambda: self.play_bots_sequentially(bot_index + 1))
            elif action in ('H', 'D'):
                card = self.deck.deal()
                bot.cards.append(card)
                frame = self.bot_cards_frames[bot_index]

                # Capture action NOW with default arg to avoid closure bug
                def _after(captured_action=action):
                    if captured_action == 'D' or bot.get_value() > 21:
                        self.root.after(self._speed() // 2,
                                        lambda: self.play_bots_sequentially(bot_index + 1))
                    else:
                        self.root.after(self._speed() // 2, make_move)

                self.draw_card_animated(card, frame, callback=_after)
                if bot_index < len(self.bot_value_labels):
                    self.bot_value_labels[bot_index].config(
                        text=f"Total: {bot.get_value()}")
                self.update_deck_counter()
                self.set_active_player(bot_index)
            else:
                self.root.after(self._speed() // 2,
                                lambda: self.play_bots_sequentially(bot_index + 1))

        self.root.after(self._speed() // 2, make_move)

    # ──────────────────────────────────────────────
    # DEALER PLAY
    # ──────────────────────────────────────────────
    def dealer_play_animated(self):
        if not self.playing: return
        self.disable_buttons()
        self.set_active_player(None)

        # Reveal hidden card
        for hf in self.dealer_cards_frame.winfo_children():
            if hasattr(hf, '_hidden_label'):
                self.reveal_card_frame(hf)

        self.dealer_value_label.config(text=T("g_total") + str(self.dealer.get_value()))

        def dealer_hit():
            if not self.playing: return
            if self.dealer.get_value() < 17:
                card = self.deck.deal()
                self.dealer.cards.append(card)

                def _after_dealer():
                    self.dealer_value_label.config(
                        text=T("g_total") + str(self.dealer.get_value()))
                    self.root.after(self._speed(), dealer_hit)

                self.draw_card_animated(card, self.dealer_cards_frame,
                                        callback=_after_dealer)
                self.update_deck_counter()
                self.set_active_player(None)
            else:
                self.root.after(self._speed() // 2, self.evaluate_results)

        self.root.after(self._speed(), dealer_hit)

    # ──────────────────────────────────────────────
    # EVALUATE
    # ──────────────────────────────────────────────
    def dealer_blackjack(self):
        self.update_display(hide_dealer=False)
        self.disable_buttons()
        parts = [T("r_dealer_bj")]
        game_entry = {}

        if self.player:
            if self.player.is_blackjack():
                parts.append(f"{T('r_you')}: {T('r_draw')}"); self.draws += 1
                game_entry["Player"] = "draw"
            else:
                parts.append(f"{T('r_you')}: {T('r_lose')}"); self.dealer_wins += 1
                game_entry["Player"] = "lose"

        for i, bot in enumerate(self.bots):
            nm = f"Bot {i+1}"
            if bot.is_blackjack():
                parts.append(f"{nm}: {T('r_draw')}"); self.draws += 1
                game_entry[nm] = "draw"
            else:
                parts.append(f"{nm}: {T('r_lose')}"); self.dealer_wins += 1
                game_entry[nm] = "lose"

        self.result_label.config(text="  |  ".join(parts))
        self._log_game(game_entry)
        self.update_stats()
        self.playing = False
        self._round_ended()

    def evaluate_results(self):
        dv = self.dealer.get_value()
        results = []
        game_entry = {}

        def outcome(pval, name, bot_idx=None):
            if pval > 21:
                results.append(f"{name}: {T('r_bust')}"); self.dealer_wins += 1
                return "lose"
            if dv > 21:
                results.append(f"{name}: {T('r_win')}")
                if bot_idx is None: self.player_wins += 1
                elif bot_idx < len(self.bot_wins): self.bot_wins[bot_idx] += 1
                return "win"
            if pval > dv:
                results.append(f"{name}: {T('r_win')}")
                if bot_idx is None: self.player_wins += 1
                elif bot_idx < len(self.bot_wins): self.bot_wins[bot_idx] += 1
                return "win"
            if pval < dv:
                results.append(f"{name}: {T('r_lose')}"); self.dealer_wins += 1
                return "lose"
            results.append(f"{name}: {T('r_push')}"); self.draws += 1
            return "draw"

        if self.player:
            game_entry["Player"] = outcome(self.player.get_value(), T("r_you"))
        for i, bot in enumerate(self.bots):
            game_entry[f"Bot {i+1}"] = outcome(bot.get_value(), f"Bot {i+1}", i)

        self.result_label.config(text="  |  ".join(results))
        self._log_game(game_entry)
        self.update_stats()
        self.playing = False
        self.set_active_player(999)
        self._round_ended()

    def _round_ended(self):
        """Called after a normal (non-autoreplay) round finishes."""
        self.update_stats()
        self.replay_btn.pack(pady=5)

    # ──────────────────────────────────────────────
    # AUTO-REPLAY  (threaded — UI never freezes)
    # ──────────────────────────────────────────────
    def start_autoreplay(self):
        try:
            n = self.autoreplay_count.get()
            if n < 1: raise ValueError
        except Exception:
            messagebox.showerror(T("d_error"), T("d_invalid_games"))
            return
        if n > 100_000:
            messagebox.showerror(T("d_error"), T("d_max_ar"))
            self.autoreplay_count.set(100_000)
            return

        # Stop any previous run
        self._ar_stop_event.set()
        if self._ar_thread and self._ar_thread.is_alive():
            self._ar_thread.join(timeout=2)

        self._ar_stop_event.clear()
        self._autoreplay_total     = n
        self._autoreplay_remaining = n
        self._autoreplay_running   = True
        self._ar_per_player        = {}
        while not self._ar_queue.empty():
            try: self._ar_queue.get_nowait()
            except: pass

        self._progressbar["maximum"] = 100
        self._progressbar["value"]   = 0
        self._progress_lbl.config(text=f"0 / {n:,}  (0.0%)")
        self.autoreplay_status.config(text=f"⚡ {n:,}{T('ar_games')}")
        self.result_label.config(text=T("g_autoreplay_running"))
        self.replay_btn.pack_forget()
        self.disable_buttons()

        # Snapshot settings — convert BotStrategy objects to flat arrays
        num_bots  = self.num_bots.get()
        num_decks = self.num_decks.get()
        human     = self.human_plays.get()

        bot_hard_arrs = []
        bot_soft_arrs = []
        for i in range(num_bots):
            strat = (self.bot_strategies[i].copy()
                     if i < len(self.bot_strategies) else BotStrategy())
            h, s = _strategy_to_arrays(strat)
            bot_hard_arrs.append(h)
            bot_soft_arrs.append(s)

        settings = {
            "n": n,
            "num_decks": num_decks,
            "num_bots": num_bots,
            "human": human,
            "bot_hard_arrs": bot_hard_arrs,
            "bot_soft_arrs": bot_soft_arrs,
        }

        self._ar_thread = threading.Thread(
            target=self._autoreplay_coordinator,
            args=(settings,),
            daemon=True
        )
        self._ar_thread.start()
        self.root.after(200, self._ar_poll_queue)

    def _autoreplay_coordinator(self, settings: dict):
        """
        Runs in a background thread. Splits work across CPU cores using
        multiprocessing.Pool, collects results, and pushes progress to UI queue.
        Never touches tkinter widgets.
        """
        n           = settings["n"]
        num_decks   = settings["num_decks"]
        num_bots    = settings["num_bots"]
        human       = settings["human"]
        bot_hard    = settings["bot_hard_arrs"]
        bot_soft    = settings["bot_soft_arrs"]

        # Use a shared-memory flag list so workers can be signalled
        # (multiprocessing.Value would need manager; use simple list with pool.terminate)
        stop_val = [False]

        # Split into chunks — one per CPU core, minimum chunk=1
        num_cores = max(1, mp.cpu_count())
        chunk     = max(1, n // num_cores)
        # Last chunk gets remainder
        chunks    = [chunk] * (num_cores - 1) + [n - chunk * (num_cores - 1)]
        chunks    = [c for c in chunks if c > 0]

        worker_args = [
            (c, num_decks, num_bots, human, bot_hard, bot_soft, stop_val)
            for c in chunks
        ]

        pool = None
        try:
            pool = mp.Pool(processes=len(chunks))
            async_result = pool.map_async(_mp_worker, worker_args)
            pool.close()

            # Poll for completion, checking stop event
            while not async_result.ready():
                if self._ar_stop_event.is_set():
                    stop_val[0] = True
                    pool.terminate()
                    pool.join()
                    self._ar_queue.put({
                        "done": n, "total": n,
                        "player_wins": 0, "dealer_wins": 0,
                        "bot_wins": [0]*num_bots, "draws": 0,
                        "per_player": {},
                        "finished": True, "stopped": True,
                    })
                    return
                async_result.wait(timeout=0.2)
                # Push intermediate "still running" progress ping
                # (we can't get partial results from pool.map — send a heartbeat)
                self._ar_queue.put({"heartbeat": True, "total": n})

            results = async_result.get()
            pool.join()

        except Exception as e:
            if pool:
                try: pool.terminate(); pool.join()
                except: pass
            self._ar_queue.put({
                "done": 0, "total": n,
                "player_wins": 0, "dealer_wins": 0,
                "bot_wins": [0]*num_bots, "draws": 0,
                "per_player": {}, "finished": True, "stopped": True,
                "error": str(e),
            })
            return

        # Merge results from all workers
        pw = dw = draws = 0
        bw = [0] * num_bots
        pc = [0, 0, 0]
        bc = [[0, 0, 0] for _ in range(num_bots)]
        done = 0

        for r in results:
            r_pw, r_dw, r_bw, r_draws, r_done, r_pc, r_bc = r
            pw    += r_pw
            dw    += r_dw
            draws += r_draws
            done  += r_done
            for i in range(3): pc[i] += r_pc[i]
            for i in range(min(num_bots, len(r_bw))):
                bw[i] += r_bw[i]
            for i in range(min(num_bots, len(r_bc))):
                for j in range(3): bc[i][j] += r_bc[i][j]

        # Build per_player dict
        per_player = {}
        if human:
            per_player["Player"] = {"win": pc[0], "lose": pc[1], "draw": pc[2]}
        for i in range(num_bots):
            per_player[f"Bot {i+1}"] = {
                "win":  bc[i][0], "lose": bc[i][1], "draw": bc[i][2]
            }

        self._ar_queue.put({
            "done":        done,
            "total":       n,
            "player_wins": pw,
            "dealer_wins": dw,
            "bot_wins":    bw,
            "draws":       draws,
            "per_player":  per_player,
            "finished":    True,
            "stopped":     self._ar_stop_event.is_set(),
        })

    def _ar_poll_queue(self):
        """
        Called from the main thread every 200ms.
        The coordinator either sends heartbeats (during computation) or
        a single final result message when done.
        Never blocks.
        """
        try:
            msg = None
            while True:
                try:
                    msg = self._ar_queue.get_nowait()
                except queue.Empty:
                    break

            if msg:
                if msg.get("heartbeat"):
                    # Still running — animate progress bar
                    total = msg["total"]
                    cur = self._progressbar["value"]
                    # Pulse the bar forward slightly so it doesn't look frozen
                    self._progressbar["value"] = min(95.0, cur + 1.0)
                    self.autoreplay_status.config(
                        text=f"⚡ {T('ar_games').strip()}…")
                elif msg.get("finished"):
                    done  = msg["done"]
                    total = msg["total"]
                    pct   = min(100.0, done / max(total, 1) * 100)

                    self._progressbar["value"] = pct
                    self._progress_lbl.config(text=f"{done:,} / {total:,}  ({pct:.1f}%)")
                    self.autoreplay_status.config(text=f"⚡ {done:,} / {total:,}")

                    self.player_wins = msg["player_wins"]
                    self.dealer_wins = msg["dealer_wins"]
                    self.draws       = msg["draws"]
                    bw = msg["bot_wins"]
                    for i, w in enumerate(bw):
                        while len(self.bot_wins) <= i: self.bot_wins.append(0)
                        self.bot_wins[i] = w
                    self._ar_per_player = msg.get("per_player", {})
                    self.game_number    = done
                    self.update_stats()

                    self._autoreplay_running = False
                    self._progressbar["value"] = 100
                    if msg.get("stopped"):
                        self._progress_lbl.config(text=T("ar_stopped_at") + f"{done:,}")
                        self.autoreplay_status.config(text=T("ar_stopped"))
                    else:
                        self._progress_lbl.config(text=f"✔ {total:,} / {total:,}  (100.0%)")
                        self.autoreplay_status.config(text=T("ar_done"))
                    if msg.get("error"):
                        messagebox.showerror(T("d_error"), msg["error"])
                    self.replay_btn.pack(pady=5)
                    return  # stop polling

        except Exception:
            pass

        if self._autoreplay_running or (self._ar_thread and self._ar_thread.is_alive()):
            self.root.after(200, self._ar_poll_queue)

    def stop_autoreplay(self):
        """Signal the worker thread to stop."""
        self._ar_stop_event.set()
        self._autoreplay_running = False
        # UI will update on next poll tick when it sees "stopped"

    # ──────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────
    def update_stats(self):
        pname = self.player_name.get() or T("default_player")
        self.dealer_wins_label.config(text=T("st_dealer") + str(self.dealer_wins))
        self.draws_label.config(text=T("st_draws") + str(self.draws))

        def pct(w, total):
            return f"{w/total*100:.0f}%" if total > 0 else "—%"

        # Human player row
        if hasattr(self, '_stats_player_row'):
            n_lbl, w_lbl, l_lbl, d_lbl, p_lbl = self._stats_player_row
            n_lbl.config(text=(pname[:11] + "…") if len(pname) > 12 else pname)
            # derive losses from dealer wins minus bot losses (approximate) — use game_log or ar_per_player
            if self._ar_per_player and "Player" in self._ar_per_player:
                pp = self._ar_per_player["Player"]
                pw, pl, pd_ = pp.get("win",0), pp.get("lose",0), pp.get("draw",0)
            else:
                # Reconstruct from game_log
                pw = pl = pd_ = 0
                for e in self.game_log:
                    r = e["results"].get("Player")
                    if r == "win":  pw += 1
                    elif r == "lose": pl += 1
                    elif r == "draw": pd_ += 1
                if pw == 0 and pl == 0 and pd_ == 0:
                    pw = self.player_wins
            tot = pw + pl + pd_
            w_lbl.config(text=str(pw))
            l_lbl.config(text=str(pl))
            d_lbl.config(text=str(pd_))
            p_lbl.config(text=pct(pw, tot))

        # Bot rows
        if hasattr(self, '_stats_bot_rows'):
            for i, row_lbls in enumerate(self._stats_bot_rows):
                n_lbl, w_lbl, l_lbl, d_lbl, p_lbl = row_lbls
                bname = (self.bot_names[i].get().strip()
                         if i < len(self.bot_names) else "") or f"Bot {i+1}"
                n_lbl.config(text=(bname[:11] + "…") if len(bname) > 12 else bname)

                key = f"Bot {i+1}"
                if self._ar_per_player and key in self._ar_per_player:
                    pp = self._ar_per_player[key]
                    bw, bl, bd_ = pp.get("win",0), pp.get("lose",0), pp.get("draw",0)
                else:
                    bw = self.bot_wins[i] if i < len(self.bot_wins) else 0
                    bl = bd_ = 0
                    for e in self.game_log:
                        r = e["results"].get(key)
                        if r == "lose":  bl += 1
                        elif r == "draw": bd_ += 1

                tot = bw + bl + bd_
                w_lbl.config(text=str(bw))
                l_lbl.config(text=str(bl))
                d_lbl.config(text=str(bd_))
                p_lbl.config(text=pct(bw, tot))

    def reset_stats(self):
        if messagebox.askyesno(T("d_reset_title"), T("d_reset_q")):
            self.player_wins = 0
            self.dealer_wins = 0
            self.bot_wins    = [0] * len(self.bot_wins)
            self.draws       = 0
            self.game_log    = []
            self.game_number = 0
            self._ar_per_player = {}
            self.update_stats()
            self.save_status_label.config(text=T("d_reset_done"))

    def _log_game(self, entry: dict):
        """Log a game result (normal play only — autoreplay uses thread-local counters)."""
        self.game_number += 1
        self.game_log.append({"game": self.game_number, "results": entry})

    def save_stats_to_file(self):
        """Save Auto-replay statistics to a .txt file in Downloads. Resets stats after saving."""
        if not self._ar_per_player:
            messagebox.showinfo(T("d_no_data"),
                                {"lv": "Nav Auto-replay spēļu! Vispirms palaid Auto-replay.",
                                 "en": "No Auto-replay games! Run Auto-replay first."
                                 }.get(_current_lang, "No Auto-replay games!"))
            return

        fname = f"cardlab_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fpath = os.path.join(_get_downloads_dir(), fname)

        human_name = self.player_name.get().strip() or T("default_player")
        bot_name_list = []
        for i in range(max(len(self.bot_wins), self.num_bots.get())):
            n = (self.bot_names[i].get().strip()
                 if i < len(self.bot_names) else "") or f"Bot {i+1}"
            bot_name_list.append(n)

        bot_strat_names = []
        for i in range(len(bot_name_list)):
            if hasattr(self, '_bot_preset_vars') and i < len(self._bot_preset_vars):
                bot_strat_names.append(self._bot_preset_vars[i].get())
            else:
                bot_strat_names.append(T("p_basic"))

        # Remap auto-replay internal keys to display names
        raw = self._ar_per_player
        per_player = {}
        for key, counts in raw.items():
            if key == "Player":
                display = human_name
            elif key.startswith("Bot "):
                idx = int(key.split(" ")[1]) - 1
                display = bot_name_list[idx] if idx < len(bot_name_list) else key
            else:
                display = key
            per_player[display] = counts

        def pct(val, total):
            return f"{val/total*100:.1f}%" if total > 0 else "—"

        def sep(ch="─", n=68):
            return ch * n

        lines = [
            "╔══════════════════════════════════════════════════════════════════════╗",
            f"║         {T('f_title'):<62}║",
            "╚══════════════════════════════════════════════════════════════════════╝",
            f"  {T('f_saved_at')}  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  {T('f_total_games')} {self.game_number:,}",
            "",
        ]

        lines.append(sep("─"))
        lines.append(f"  {T('f_player_info')}")
        lines.append(sep("─"))
        if self.human_plays.get() or self.player_wins > 0:
            lines.append(f"  {human_name:<18}  {T('f_strategy')} {T('f_manual')}")
        for i, bname in enumerate(bot_name_list):
            strat = bot_strat_names[i] if i < len(bot_strat_names) else "—"
            lines.append(f"  {bname:<18}  {T('f_strategy')} {strat}")
        lines.append("")

        lines.append(sep("─"))
        lines.append(f"  {T('f_results_by')}")
        lines.append(sep("─"))
        col = f"  {T('f_name_col'):<18} {T('f_win_col'):>6} {T('f_lose_col'):>6} {T('f_draw_col'):>6} {T('f_winpct_col'):>7} {T('f_vs_dealer_col'):>9}"
        lines.append(col)
        lines.append(f"  {sep('-', 56)}")

        all_wins = all_loses = all_draws = 0
        for display, counts in per_player.items():
            w = counts.get("win", 0)
            l = counts.get("lose", 0)
            d = counts.get("draw", 0)
            t = w + l + d
            all_wins  += w; all_loses += l; all_draws += d
            vs_dealer = f"{pct(w, t)} {T('f_win_r')}"
            lines.append(f"  {display:<18} {w:>6} {l:>6} {d:>6} {pct(w,t):>7} {vs_dealer:>9}")

        lines.append(f"  {sep('-', 56)}")
        all_t = all_wins + all_loses + all_draws
        lines.append(f"  {T('f_all'):<18} {all_wins:>6} {all_loses:>6} {all_draws:>6} {pct(all_wins,all_t):>7}")

        lines += ["", sep("─"), f"  {T('f_dealer_sum')}", sep("─")]
        d_wins = all_loses; d_loses = all_wins; d_draws = all_draws
        d_total = d_wins + d_loses + d_draws
        lines.append(f"  {T('f_dealer_wins'):<22} {d_wins:>6}  ({pct(d_wins, d_total)})")
        lines.append(f"  {T('f_dealer_loses'):<22} {d_loses:>6}  ({pct(d_loses, d_total)})")
        lines.append(f"  {T('f_dealer_draws'):<22} {d_draws:>6}  ({pct(d_draws, d_total)})")
        lines.append("")
        lines.append(f"  ({T('f_no_log')})")
        lines.append("")
        lines.append(sep("="))

        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            # ── Reset all stats after saving ──
            self.player_wins = 0
            self.dealer_wins = 0
            self.bot_wins    = [0] * len(self.bot_wins)
            self.draws       = 0
            self.game_log    = []
            self.game_number = 0
            self._ar_per_player = {}
            self.update_stats()
            self.save_status_label.config(text=f"✔ {fname}")
            messagebox.showinfo(T("d_saved"), T("d_saved_msg") + fpath)
        except Exception as ex:
            messagebox.showerror(T("d_error"), str(ex))

    def save_stats_to_csv(self):
        """Eksportē Auto-replay statistiku uz .csv failu Lejupielāžu mapē.
        CSV satur vienu rindu uz spēlētāju ar: vārds, stratēģija, uzvaras, zaudējumi,
        neizšķirts, kopā, uzv%. Ideāli piemērots korelācijas analīzei Bruno kalkulatorā."""
        if not self._ar_per_player:
            messagebox.showinfo(T("d_no_data"),
                                {"lv": "Nav Auto-replay spēļu! Vispirms palaid Auto-replay.",
                                 "en": "No Auto-replay games! Run Auto-replay first."
                                 }.get(_current_lang, "No Auto-replay games!"))
            return

        import csv as _csv

        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"cardlab_stats_{ts}.csv"
        fpath = os.path.join(_get_downloads_dir(), fname)

        human_name    = self.player_name.get().strip() or T("default_player")
        bot_name_list = []
        for i in range(max(len(self.bot_wins), self.num_bots.get())):
            n = (self.bot_names[i].get().strip()
                 if i < len(self.bot_names) else "") or f"Bot {i+1}"
            bot_name_list.append(n)

        bot_strat_names = []
        for i in range(len(bot_name_list)):
            if hasattr(self, "_bot_preset_vars") and i < len(self._bot_preset_vars):
                bot_strat_names.append(self._bot_preset_vars[i].get())
            else:
                bot_strat_names.append(T("p_basic"))

        def resolve_key(key):
            if key == "Player":
                return human_name
            if key.startswith("Bot "):
                idx = int(key.split(" ")[1]) - 1
                return bot_name_list[idx] if idx < len(bot_name_list) else key
            return key

        per_player = {resolve_key(k): v for k, v in self._ar_per_player.items()}

        strat_map = {}
        if self.human_plays.get() or self.player_wins > 0:
            strat_map[human_name] = T("f_manual")
        for i, bn in enumerate(bot_name_list):
            strat_map[bn] = bot_strat_names[i] if i < len(bot_strat_names) else ""

        try:
            with open(fpath, "w", newline="", encoding="utf-8") as csvfile:
                writer = _csv.writer(csvfile)

                # Header row
                writer.writerow([
                    "Speletajs", "Strategija",
                    "Uzvaras", "Zaudejumi", "Neizskirts", "Kopa",
                    "Uzv_procenti",
                    "Dealeris_uzvaras", "Neizskirts_kopa",
                    "Spelu_skaits", "Datums"
                ])

                ts_display = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                total_games = self.game_number

                for pname, counts in per_player.items():
                    w  = counts.get("win",  0)
                    l  = counts.get("lose", 0)
                    d  = counts.get("draw", 0)
                    t  = w + l + d
                    pct = round(w / t * 100, 2) if t > 0 else 0.0
                    writer.writerow([
                        pname,
                        strat_map.get(pname, ""),
                        w, l, d, t,
                        pct,
                        self.dealer_wins,
                        self.draws,
                        total_games,
                        ts_display
                    ])

            self.save_status_label.config(text=f"CSV")
            messagebox.showinfo(T("d_csv_saved"), T("d_csv_msg") + fpath)

        except Exception as ex:
            messagebox.showerror(T("d_error"), str(ex))

    def save_stats_to_sqlite(self):
        """Save current statistics to a SQLite database file."""
        if not self.game_log and not self._ar_per_player and self.game_number == 0:
            messagebox.showinfo(T("d_no_data"), T("d_no_games"))
            return

        db_path = os.path.join(_get_downloads_dir(), "cardlab_stats.db")
        session_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        human_name = self.player_name.get().strip() or T("default_player")
        bot_name_list = []
        for i in range(max(len(self.bot_wins), self.num_bots.get())):
            n = (self.bot_names[i].get().strip()
                 if i < len(self.bot_names) else "") or f"Bot {i+1}"
            bot_name_list.append(n)

        bot_strat_names = []
        for i in range(len(bot_name_list)):
            if hasattr(self, '_bot_preset_vars') and i < len(self._bot_preset_vars):
                bot_strat_names.append(self._bot_preset_vars[i].get())
            else:
                bot_strat_names.append(T("p_basic"))

        # Build per_player dict (same logic as save_stats_to_file)
        if self._ar_per_player:
            raw = self._ar_per_player
            per_player = {}
            for key, counts in raw.items():
                if key == "Player":
                    display = human_name
                elif key.startswith("Bot "):
                    idx = int(key.split(" ")[1]) - 1
                    display = bot_name_list[idx] if idx < len(bot_name_list) else key
                else:
                    display = key
                per_player[display] = counts
        else:
            per_player = {}
            for e in self.game_log:
                for key, result in e["results"].items():
                    if key == "Player":
                        display = human_name
                    elif key.startswith("Bot "):
                        idx = int(key.split(" ")[1]) - 1
                        display = bot_name_list[idx] if idx < len(bot_name_list) else key
                    else:
                        display = key
                    per_player.setdefault(display, {"win": 0, "lose": 0, "draw": 0})
                    per_player[display][result] = per_player[display].get(result, 0) + 1

        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Sessions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    saved_at TEXT,
                    total_games INTEGER,
                    num_decks INTEGER,
                    language TEXT
                )""")

            # Player stats table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    player_name TEXT,
                    strategy TEXT,
                    wins INTEGER,
                    losses INTEGER,
                    draws INTEGER,
                    win_pct REAL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )""")

            # Game log table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS game_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    game_number INTEGER,
                    player_name TEXT,
                    result TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )""")

            # Insert session
            cur.execute(
                "INSERT INTO sessions (saved_at, total_games, num_decks, language) VALUES (?,?,?,?)",
                (session_ts, self.game_number, self.num_decks.get(), _current_lang))
            session_id = cur.lastrowid

            # Insert player stats
            strat_map = {}
            if self.human_plays.get() or self.player_wins > 0:
                strat_map[human_name] = T("f_manual")
            for i, bname in enumerate(bot_name_list):
                strat_map[bname] = bot_strat_names[i] if i < len(bot_strat_names) else "—"

            for pname, counts in per_player.items():
                w = counts.get("win", 0)
                l = counts.get("lose", 0)
                d = counts.get("draw", 0)
                t = w + l + d
                pct_val = round(w / t * 100, 1) if t > 0 else 0.0
                strat = strat_map.get(pname, "—")
                cur.execute(
                    "INSERT INTO player_stats (session_id, player_name, strategy, wins, losses, draws, win_pct) VALUES (?,?,?,?,?,?,?)",
                    (session_id, pname, strat, w, l, d, pct_val))

            # Insert game log entries
            for e in self.game_log:
                for key, result in e["results"].items():
                    if key == "Player":
                        display = human_name
                    elif key.startswith("Bot "):
                        idx = int(key.split(" ")[1]) - 1
                        display = bot_name_list[idx] if idx < len(bot_name_list) else key
                    else:
                        display = key
                    cur.execute(
                        "INSERT INTO game_log (session_id, game_number, player_name, result) VALUES (?,?,?,?)",
                        (session_id, e["game"], display, result))

            conn.commit()
            conn.close()

            self.save_status_label.config(text=f"✔ SQLite")
            messagebox.showinfo(T("d_sqlite_saved"), T("d_sqlite_msg") + db_path)
        except Exception as ex:
            messagebox.showerror(T("d_error"), str(ex))

    def save_stats_to_excel(self):
        """Export Auto-replay stats to .xlsx in Downloads — pure stdlib, no pip needed.
        Stats summary on top, full game-by-game log below. Resets stats after saving."""
        if not self._ar_per_player:
            messagebox.showinfo(T("d_no_data"),
                                {"lv": "Nav Auto-replay spēļu! Vispirms palaid Auto-replay.",
                                 "en": "No Auto-replay games! Run Auto-replay first."
                                 }.get(_current_lang, "No Auto-replay games!"))
            return

        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"cardlab_stats_{ts}.xlsx"
        fpath = os.path.join(_get_downloads_dir(), fname)

        human_name    = self.player_name.get().strip() or T("default_player")
        bot_name_list = []
        for i in range(max(len(self.bot_wins), self.num_bots.get())):
            n = (self.bot_names[i].get().strip()
                 if i < len(self.bot_names) else "") or f"Bot {i+1}"
            bot_name_list.append(n)
        bot_strat_names = []
        for i in range(len(bot_name_list)):
            if hasattr(self, '_bot_preset_vars') and i < len(self._bot_preset_vars):
                bot_strat_names.append(self._bot_preset_vars[i].get())
            else:
                bot_strat_names.append(T("p_basic"))

        def resolve_key(key):
            if key == "Player": return human_name
            if key.startswith("Bot "):
                idx = int(key.split(" ")[1]) - 1
                return bot_name_list[idx] if idx < len(bot_name_list) else key
            return key

        # Always from _ar_per_player (autoplay only)
        per_player = {resolve_key(k): v for k, v in self._ar_per_player.items()}

        strat_map = {}
        if self.human_plays.get() or self.player_wins > 0:
            strat_map[human_name] = T("f_manual")
        for i, bn in enumerate(bot_name_list):
            strat_map[bn] = bot_strat_names[i] if i < len(bot_strat_names) else u"\u2014"

        result_lbl = {"win": T("f_win_r"), "lose": T("f_lose_r"), "draw": T("f_draw_r")}

        # ═══════════════════════════════════════════════════════════
        # Pure-stdlib .xlsx writer  (an .xlsx is a ZIP of XML parts)
        # ═══════════════════════════════════════════════════════════
        def _esc(s):
            return (str(s).replace("&","&amp;").replace("<","&lt;")
                    .replace(">","&gt;").replace('"',"&quot;"))

        def col_letter(n):
            s = ""
            while n:
                n, r = divmod(n - 1, 26)
                s = chr(65 + r) + s
            return s

        def cref(row, col): return f"{col_letter(col)}{row}"

        _ss, _ss_map = [], {}
        def si(text):
            t = str(text)
            if t not in _ss_map:
                _ss_map[t] = len(_ss); _ss.append(t)
            return _ss_map[t]

        # Style indices:
        # 0=normal  1=hdr(navy/white/bold)  2=bold  3=pct%
        # 4=win-green  5=lose-red  6=draw-yellow  7=alt-row  8=total-hdr
        # 9=section-hdr(dark-grey bg)  10=title
        def c_str(ref, val, s=0):
            return f'<c r="{ref}" t="s" s="{s}"><v>{si(val)}</v></c>'
        def c_num(ref, val, s=0):
            return f'<c r="{ref}" s="{s}"><v>{val}</v></c>'
        def c_fml(ref, fml, s=0):
            return f'<c r="{ref}" s="{s}"><f>{_esc(fml)}</f></c>'
        def rowx(ri, cells, ht=None):
            h = f' ht="{ht}" customHeight="1"' if ht else ""
            return f'<row r="{ri}"{h}>{"".join(cells)}</row>'

        # ── Single sheet: stats on top, log below ──
        def build_main_sheet():
            rows = []
            # ── Section A: Title ──
            rows.append(rowx(1, [c_str("A1", "CardLab \u2014 Blackjack Statistics", 10)], ht=30))
            rows.append(rowx(2, [c_str("A2", f"{T('xl_saved_at')}: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 2)]))
            rows.append(rowx(3, [c_str("A3", f"{T('xl_total_games')}: {self.game_number:,}", 2)]))
            rows.append(rowx(4, []))   # spacer

            # ── Section B: Summary header ──
            sum_hdrs = [T("xl_player"), T("xl_strategy"),
                        T("xl_wins"), T("xl_losses"), T("xl_draws"),
                        T("xl_total"), T("xl_winpct")]
            rows.append(rowx(5, [c_str(cref(5,i+1), h, 1) for i,h in enumerate(sum_hdrs)], ht=18))

            # ── Section B: Data rows ──
            ds = 6
            for ri2, (pname, counts) in enumerate(per_player.items()):
                w = counts.get("win",0); l = counts.get("lose",0); d = counts.get("draw",0)
                t = w+l+d; r = ds+ri2; s = 7 if ri2%2 else 0
                cells = [c_str(cref(r,1), pname, s),
                         c_str(cref(r,2), strat_map.get(pname,"\u2014"), s),
                         c_num(cref(r,3), w, s), c_num(cref(r,4), l, s),
                         c_num(cref(r,5), d, s), c_num(cref(r,6), t, s),
                         c_fml(cref(r,7), f"C{r}/F{r}" if t else "0", 3)]
                rows.append(rowx(r, cells))

            # ── Section B: Totals row ──
            n = len(per_player); tr = ds+n; r1 = ds; r2 = ds+n-1
            tc = [c_str(cref(tr,1), T("xl_total"), 8), c_str(cref(tr,2), "", 8),
                  c_fml(cref(tr,3), f"SUM(C{r1}:C{r2})" if n else "0", 8),
                  c_fml(cref(tr,4), f"SUM(D{r1}:D{r2})" if n else "0", 8),
                  c_fml(cref(tr,5), f"SUM(E{r1}:E{r2})" if n else "0", 8),
                  c_fml(cref(tr,6), f"SUM(F{r1}:F{r2})" if n else "0", 8),
                  c_fml(cref(tr,7), f"C{tr}/F{tr}" if n else "0", 8)]
            rows.append(rowx(tr, tc, ht=18))

            # ── Spacer rows ──
            sep1 = tr + 1
            sep2 = tr + 2
            rows.append(rowx(sep1, []))
            rows.append(rowx(sep2, []))

            # ── Section C: Game Log header (note: auto-replay has no per-game log) ──
            log_start = tr + 3
            log_hdr_label = {"lv": "SPĒĻU ŽURNĀLS — Auto-replay kopsavilkums",
                              "en": "GAME LOG — Auto-replay summary"}.get(_current_lang, T("xl_gamelog"))
            rows.append(rowx(log_start, [c_str(cref(log_start,1), log_hdr_label, 9)], ht=18))

            # Auto-replay stores totals, not individual game records.
            # Show per-player breakdown in log section.
            log_hdrs = [T("xl_player"), T("xl_strategy"),
                        T("xl_wins"), T("xl_losses"), T("xl_draws"),
                        T("xl_total"), T("xl_winpct")]
            lh_row = log_start + 1
            rows.append(rowx(lh_row, [c_str(cref(lh_row,i+1), h, 1) for i,h in enumerate(log_hdrs)], ht=18))

            for ri2, (pname, counts) in enumerate(per_player.items()):
                w = counts.get("win",0); l = counts.get("lose",0); d = counts.get("draw",0)
                t = w+l+d; r = lh_row+1+ri2; s = 4 if (w >= l and w >= d) else (5 if l > w and l >= d else 6)
                cells = [c_str(cref(r,1), pname, 0),
                         c_str(cref(r,2), strat_map.get(pname,"\u2014"), 0),
                         c_num(cref(r,3), w, 4 if s==4 else 0),
                         c_num(cref(r,4), l, 5 if s==5 else 0),
                         c_num(cref(r,5), d, 0),
                         c_num(cref(r,6), t, 0),
                         c_fml(cref(r,7), f"C{r}/F{r}" if t else "0", 3)]
                rows.append(rowx(r, cells))

            # Note about per-game log
            note_row = lh_row + 1 + len(per_player) + 1
            note_txt = {"lv": "\u26a0 Auto-replay neglabā atsevišķas spēles — tikai kopsavilkumu.",
                        "en": "\u26a0 Auto-replay does not store individual games \u2014 summary only."
                       }.get(_current_lang, "")
            rows.append(rowx(note_row, [c_str(cref(note_row,1), note_txt, 2)]))

            # Column widths
            col_widths = [24, 22, 10, 10, 10, 10, 10]
            cols = "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
                           for i,w in enumerate(col_widths))
            merge = (f'<mergeCells count="2">'
                     f'<mergeCell ref="A1:G1"/>'
                     f'<mergeCell ref="A{log_start}:G{log_start}"/>'
                     f'</mergeCells>')
            return f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData>{merge}'

        def ws_xml(inner):
            return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheetView workbookViewId="0" showGridLines="0"/>'
                    + inner + '</worksheet>')

        def wb_xml(names):
            sheets = "".join(f'<sheet name="{_esc(n)}" sheetId="{i+1}" r:id="rId{i+1}"/>'
                             for i,n in enumerate(names))
            return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    f'<sheets>{sheets}</sheets></workbook>')

        def wb_rels_xml(n):
            rels = "".join(
                f'<Relationship Id="rId{i+1}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{i+1}.xml"/>' for i in range(n))
            rels += (f'<Relationship Id="rId{n+1}" '
                     'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
                     'Target="sharedStrings.xml"/>'
                     f'<Relationship Id="rId{n+2}" '
                     'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                     'Target="styles.xml"/>')
            return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + rels + '</Relationships>')

        def ss_xml():
            items = "".join(
                f'<si><t xml:space="preserve">{_esc(s)}</t></si>' for s in _ss)
            return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                    f' count="{len(_ss)}" uniqueCount="{len(_ss)}">{items}</sst>')

        STYLES = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="5">'
              '<font><sz val="10"/><name val="Arial"/></font>'
              '<font><sz val="10"/><b/><color rgb="FFFFFFFF"/><name val="Arial"/></font>'
              '<font><sz val="10"/><b/><name val="Arial"/></font>'
              '<font><sz val="14"/><b/><color rgb="FF1F3864"/><name val="Arial"/></font>'
              '<font><sz val="10"/><i/><color rgb="FF888888"/><name val="Arial"/></font>'
            '</fonts>'
            '<fills count="10">'
              '<fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFEBF1F8"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFFFEB9C"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFEBF1F8"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FF2D3748"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/></patternFill></fill>'
            '</fills>'
            '<borders count="2">'
              '<border><left/><right/><top/><bottom/></border>'
              '<border>'
                '<left style="thin"><color rgb="FFB0B0B0"/></left>'
                '<right style="thin"><color rgb="FFB0B0B0"/></right>'
                '<top style="thin"><color rgb="FFB0B0B0"/></top>'
                '<bottom style="thin"><color rgb="FFB0B0B0"/></bottom>'
              '</border>'
            '</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="11">'
              '<xf numFmtId="0"  fontId="0" fillId="0" borderId="0" xfId="0"/>'                                     # 0 normal
              '<xf numFmtId="0"  fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'  # 1 hdr
              '<xf numFmtId="0"  fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'                       # 2 bold
              '<xf numFmtId="10" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'  # 3 pct
              '<xf numFmtId="0"  fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'           # 4 win
              '<xf numFmtId="0"  fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'           # 5 lose
              '<xf numFmtId="0"  fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'           # 6 draw
              '<xf numFmtId="0"  fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>'       # 7 alt
              '<xf numFmtId="0"  fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center"/></xf>'  # 8 total-hdr
              '<xf numFmtId="0"  fontId="1" fillId="8" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'  # 9 section-hdr dark
              '<xf numFmtId="0"  fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>'                       # 10 title
            '</cellXfs>'
            '</styleSheet>')

        CONTENT_TYPES = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml"  ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml"          ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml"     ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '<Override PartName="/xl/styles.xml"            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>')

        ROOT_RELS = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>')

        try:
            name = T("xl_summary")
            sheet = ws_xml(build_main_sheet())
            shared = ss_xml()

            with zipfile.ZipFile(fpath, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("[Content_Types].xml",           CONTENT_TYPES)
                zf.writestr("_rels/.rels",                   ROOT_RELS)
                zf.writestr("xl/workbook.xml",               wb_xml([name]))
                zf.writestr("xl/_rels/workbook.xml.rels",    wb_rels_xml(1))
                zf.writestr("xl/styles.xml",                 STYLES)
                zf.writestr("xl/sharedStrings.xml",          shared)
                zf.writestr("xl/worksheets/sheet1.xml",      sheet)

            # ── Reset all stats after saving ──
            self.player_wins = 0
            self.dealer_wins = 0
            self.bot_wins    = [0] * len(self.bot_wins)
            self.draws       = 0
            self.game_log    = []
            self.game_number = 0
            self._ar_per_player = {}
            self.update_stats()

            self.save_status_label.config(text="✔ Excel")
            messagebox.showinfo(T("d_excel_saved"), T("d_excel_msg") + fpath)
        except Exception as ex:
            messagebox.showerror(T("d_error"), str(ex))

    # ──────────────────────────────────────────────
    # EXIT
    # ──────────────────────────────────────────────
    def exit_game(self):
        self._autoreplay_running = False
        self.game_frame.destroy()
        del self.game_frame
        self.root.configure(bg=self.bg_menu)
        self.create_menu_screen()

    def open_tutorial(self):
        TutorialWindow(self.root)

    # ──────────────────────────────────────────────
    # STRATEGY PERSISTENCE
    # ──────────────────────────────────────────────
    _STRAT_FILE = os.path.join(os.path.expanduser("~"), "cardlab_strategies.txt")

    def _load_saved_strategies(self):
        """Load saved strategies from disk. Format: NAME|hard_csv|soft_csv"""
        self.saved_strategies = {}
        if not os.path.exists(self._STRAT_FILE):
            return
        try:
            with open(self._STRAT_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("|")
                    if len(parts) != 3:
                        continue
                    name, hard_s, soft_s = parts
                    s = BotStrategy()
                    # hard: row;row;... each row = "total:up=act,up=act,..."
                    for row_s in hard_s.split(";"):
                        if ":" not in row_s: continue
                        tot_s, cells = row_s.split(":", 1)
                        tot = int(tot_s)
                        s.hard[tot] = {}
                        for cell in cells.split(","):
                            if "=" not in cell: continue
                            u, a = cell.split("=")
                            s.hard[tot][int(u)] = a
                    for row_s in soft_s.split(";"):
                        if ":" not in row_s: continue
                        tot_s, cells = row_s.split(":", 1)
                        tot = int(tot_s)
                        s.soft[tot] = {}
                        for cell in cells.split(","):
                            if "=" not in cell: continue
                            u, a = cell.split("=")
                            s.soft[tot][int(u)] = a
                    self.saved_strategies[name] = s
        except Exception:
            pass

    def _persist_saved_strategies(self):
        """Save all named strategies to disk."""
        try:
            lines = ["# CardLab saved strategies"]
            for name, s in self.saved_strategies.items():
                hard_parts = []
                for tot, row in s.hard.items():
                    cells = ",".join(f"{u}={a}" for u, a in sorted(row.items()))
                    hard_parts.append(f"{tot}:{cells}")
                soft_parts = []
                for tot, row in s.soft.items():
                    cells = ",".join(f"{u}={a}" for u, a in sorted(row.items()))
                    soft_parts.append(f"{tot}:{cells}")
                lines.append(f"{name}|{';'.join(hard_parts)}|{';'.join(soft_parts)}")
            with open(self._STRAT_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
def main():
    # Required for multiprocessing on Windows (freeze_support for PyInstaller too)
    mp.freeze_support()
    root = tk.Tk()
    app = BlackjackGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()