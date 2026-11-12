import io
import re
import pdfplumber
import pandas as pd
import numpy as np
import streamlit as st

st.set_page_config(page_title="SA Racing Wizard", layout="wide")

st.title("South African Horseracing Prediction Engine")
st.caption("Supports BOTH 4Racing ComputaForm (Vaal, Turffontein, KZN) and Race Coast (Cape Town, EC) PDFs.")

uploaded_pdf = st.file_uploader("Upload South African ComputaForm / Race Coast PDF", type=["pdf"])

c1, c2, c3, c4, c5 = st.columns(5)
w_speed = c1.slider("Speed & Weight", 0.0, 1.0, 0.35, 0.05)
w_class = c2.slider("Class & MR Drop", 0.0, 1.0, 0.25, 0.05)
w_form = c3.slider("Form & Fitness", 0.0, 1.0, 0.20, 0.05)
w_draw = c4.slider("Draw Bias", 0.0, 1.0, 0.10, 0.05)
w_gear = c5.slider("Gear Upgrades", 0.0, 1.0, 0.10, 0.05)


def parse_4racing_computaform(pdf):
    runners = []
    meeting_title = "4Racing ComputaForm Meeting"
    seen_races = set()

    # Summary row pattern on race header pages:
    # e.g. "2 532 PITERAQ 14-0-2-4 43% R98,800 R7,057 4Bf 60 2 F Bronkhorst 5.7% R Danielson 23.8% 74 70 ... 7-2"
    row_re = re.compile(
        r"^(?P<No>\d{1,2})\s+"
        r"(?:(?P<L3>[0-9pq]+)\s+)?"
        r"(?P<Horse>[A-Z0-9\'\-\’]+(?:\s+[A-Z0-9\'\-\’]+)*?)\s+"
        r"(?P<Runs>\d+)-(?P<Wins>\d+)-(?P<Places2>\d+)-(?P<Places3>\d+)\s+"
        r"(?P<F3>\d+)%\s+"
        r"R(?P<Earn>[\d,]+)\s+"
        r"R(?P<AveEarn>[\d,]+)\s+"
        r"\d[A-Za-z]{1,3}\s+"
        r"(?P<Wt>\d{2}(?:\.\d)?)(?:-\d\.\d|\+\d\.\d)?\s+"
        r"(?P<Draw>\d{1,2})\s+"
        r".*?"
        r"(?P<HMR>\d{2,3}|--)\s+"
        r"(?P<CMR>\d{2,3}|--)\s+"
        r"(?P<Comment>.*?)\s+"
        r"(?P<OddsNum>\d+)-(?P<OddsDen>\d+)$"
    )

    for page_idx, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if page_idx == 0:
            for ln in lines:
                if "TAB " in ln or "TURFFONTEIN" in ln or "VAAL" in ln or "GREYVILLE" in ln or "SCOTTSVILLE" in ln:
                    meeting_title = ln
                    break

        # Detect 4Racing Race Summary Page (contains "No L3 Name R-1-2-3")
        if "No L3 Name R-1-2-3" not in text:
            continue

        # Ignore the "HOW TO READ COMPUTAFORM" sample page at the very end
        if "COMPUTAFORM AT A GLANCE" in text or "HOW TO READ" in text:
            continue

        dist_match = re.search(r"\b(\d{4})m\b", text)
        race_dist = int(dist_match.group(1)) if dist_match else 1200

        ref_match = re.search(r"Race Ref:\s*(\d+)", text)
        race_ref = ref_match.group(1) if ref_match else str(page_idx)
        if race_ref in seen_races:
            continue
        seen_races.add(race_ref)
        current_race = len(seen_races)

        # Extract CF Ratings & Speed Ratings lookup maps from the page
        cf_map = {}
        sp_map = {}
        for ln in lines:
            m_rate = re.match(r"^(\d{1,2})\s+([A-Za-z\s\'\-\’]+?)\s+(\d{2,3})\b", ln)
            if m_rate:
                h_key = m_rate.group(2).strip().upper()
                val = float(m_rate.group(3))
                if h_key not in cf_map:
                    cf_map[h_key] = val
                elif h_key not in sp_map:
                    sp_map[h_key] = val

        for ln in lines:
            rm = row_re.match(ln)
            if rm:
                horse_name = rm.group("Horse").strip().upper()
                runs = int(rm.group("Runs"))
                wins = int(rm.group("Wins"))
                places = int(rm.group("Places2")) + int(rm.group("Places3"))
                earn = int(rm.group("Earn").replace(",", ""))
                ave_earn = int(rm.group("AveEarn").replace(",", ""))
                hmr = int(rm.group("HMR")) if rm.group("HMR").isdigit() else 0
                cmr = int(rm.group("CMR")) if rm.group("CMR").isdigit() else 0
                l3_str = rm.group("L3") or ""
                l3_digits = [int(ch) if ch != "0" else 10 for ch in l3_str if ch.isdigit()]
                avg_pos = float(np.mean(l3_digits)) if l3_digits else 6.5
                odds_num = float(rm.group("OddsNum"))
                odds_den = float(rm.group("OddsDen"))
                fcst_odds = round(odds_num / odds_den, 2) if odds_den > 0 else 15.0
                comment = rm.group("Comment").strip()

                gear_boost = 1.0 if ("blinkers" in comment.lower() or "headgear" in comment.lower() or "tongue" in comment.lower()) else 0.0
                mr_drop = max(0, hmr - cmr) if (hmr > 0 and cmr > 0) else 0

                runners.append({
                    "Race": current_race,
                    "Dist": race_dist,
                    "No": int(rm.group("No")),
                    "Horse": horse_name,
                    "Draw": int(rm.group("Draw")),
                    "Wt": float(rm.group("Wt")),
                    "MR": cmr,
                    "MR_Drop": mr_drop,
                    "Gear_Boost": gear_boost,
                    "Runs": runs,
                    "Wins": wins,
                    "Places": places,
                    "Stakes": earn,
                    "Earnings_Per_Run": float(ave_earn),
                    "Place_Strike": (wins * 2 + places) / runs if runs > 0 else 0.25,
                    "Speed_Index": sp_map.get(horse_name, cf_map.get(horse_name, 35.0)),
                    "Avg_Lengths_Btn": avg_pos,
                    "Days_Rested": 45 if "rest" in comment.lower() else 21,
                    "Last_Odds": fcst_odds,
                    "Comment": comment
                })

    return pd.DataFrame(runners), meeting_title


def parse_racecoast_pdf(pdf):
    runners = []
    meeting_title = "Race Coast Meeting"
    race_header_re = re.compile(r"RACE\s+(\d+)\s*[-–]\s*(?:Abt/)?(\d+)\s*m", re.IGNORECASE)
    runner_header_re = re.compile(
        r"^(?P<No>\d{1,2})\s+"
        r"(?P<Horse>[A-Z0-9\'\-\’]+(?:\s+[A-Z0-9\'\-\’]+)*?)\s+"
        r"(?P<Gear>[ASLF](?:\s+[BCPXHJKNZte])*)\s+"
        r"(?P<Draw>\d{1,2}|RESERVE\s*\d)\s+"
        r"(?P<Weight>\d{2}(?:\.\d)?)"
        r"(?:\s+\((?P<MR>\d+)\))?"
        r"(?:\s+\[(?P<LastMR>\d+)\])?$"
    )

    for page_idx, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if page_idx == 1 and len(lines) > 0:
            meeting_title = next(iter(lines), meeting_title)

        page_race_match = None
        for line in lines[:8]:
            m = race_header_re.search(line)
            if m:
                page_race_match = m
                break
        if not page_race_match:
            continue

        current_race = int(page_race_match.group(1))
        race_distance = int(page_race_match.group(2))
        full_page_text = " ".join(lines)

        speed_map = {}
        speed_block = re.search(r"SPEED RATINGS:\s*(.*?)(?:BEST AVERAGE:|DAYS RESTED:)", full_page_text)
        if speed_block:
            for item in speed_block.group(1).split(";"):
                sm = re.search(r"([A-Za-z\s\'\-\’]+?)\s+(-?\d+\.\d+)", item.strip())
                if sm:
                    speed_map[sm.group(1).strip().upper()] = float(sm.group(2))

        rest_map = {}
        rest_block = re.search(r"DAYS RESTED:\s*(.*?)(?:\b1\s+[A-Z]{2,})", full_page_text)
        if rest_block:
            for item in rest_block.group(1).split(";"):
                rm = re.search(r"([A-Za-z\s\'\-\’]+?)\s*\((\d+)\s*days\)", item.strip(), re.IGNORECASE)
                if rm:
                    rest_map[rm.group(1).strip().upper()] = int(rm.group(2))

        current_runner = None
        for line in lines:
            rm = runner_header_re.match(line)
            if rm:
                if current_runner:
                    runners.append(current_runner)
                horse_name = rm.group("Horse").strip().upper()
                draw_raw = rm.group("Draw")
                if "RESERVE" in draw_raw.upper():
                    current_runner = None
                    continue
                mr_val = int(rm.group("MR")) if rm.group("MR") else 0
                last_mr_val = int(rm.group("LastMR")) if rm.group("LastMR") else mr_val
                current_runner = {
                    "Race": current_race,
                    "Dist": race_distance,
                    "No": int(rm.group("No")),
                    "Horse": horse_name,
                    "Draw": int(draw_raw) if draw_raw.isdigit() else 8,
                    "Wt": float(rm.group("Weight")),
                    "MR": mr_val,
                    "MR_Drop": max(0, last_mr_val - mr_val),
                    "Gear_Boost": 0.0,
                    "Runs": 0,
                    "Wins": 0,
                    "Places": 0,
                    "Stakes": 0,
                    "Speed_Rating": speed_map.get(horse_name, np.nan),
                    "Days_Rested": rest_map.get(horse_name, 21),
                    "Comment": "",
                    "Last_Odds": 12.0,
                    "Lengths_Behind": [],
                    "Speed_MPS": []
                }
                continue

            if current_runner is None:
                continue

            stats_m = re.search(r"Runs:\s*(\d+)\s+Wins:\s*(\d+)\s+Places:\s*(\d+)\s+Stakes Won:\s*R([\d,]+)", line)
            if stats_m:
                current_runner["Runs"] = int(stats_m.group(1))
                current_runner["Wins"] = int(stats_m.group(2))
                current_runner["Places"] = int(stats_m.group(3))
                current_runner["Stakes"] = int(stats_m.group(4).replace(",", ""))
                continue

            if line.startswith("COMMENT:") or line.startswith("TRAINER COMMENT:"):
                parts = line.split(":", 1)
                current_runner["Comment"] = parts.pop().strip()
                continue

            run_m = re.match(
