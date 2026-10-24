"""Generated tables for SCRUM-95 (from results.json; nothing typed by hand)."""
from gap import assisted as G


def pct(w):
    if not w:
        return "—"
    return f"{100 * w['p']:.1f}% ({w['k']}/{w['n']}, {100 * w['lo']:.1f}–{100 * w['hi']:.1f})"


def cl(ci):
    return "—" if not ci else f"{100 * ci[0]:.1f}–{100 * ci[1]:.1f}"


def render(r) -> str:
    L = ["# SCRUM-95 — assisted-versus-unaided gap: validation results", "",
         f"Thresholds: gap {r['thresholds']['gap']}, reduction {r['thresholds']['reduction']}, "
         f"credibility {r['thresholds']['credibility']}. Rates: share (k/n, 95% Wilson); "
         "cluster = 95% bootstrap over learners.", "",
         f"Cases: {r['n_cases_gap']} (learner, concept, round); {r['n_cases_reduction']} "
         "(learner, concept) for the reduction.", "",
         "## Gap, all rounds", "",
         "| method | found (true gap) | false gap (no true gap) | cluster | wrong 'no gap' | cluster | insufficient | error among decided |",
         "|---|---|---|---|---|---|---|---|"]
    for k, s in r["gap_overall"].items():
        L.append(f"| {k} | {pct(s['found'])} | {pct(s['false_yes'])} | {cl(s['false_yes_cluster'])} | "
                 f"{pct(s['wrong_no'])} | {cl(s['wrong_no_cluster'])} | {pct(s['insufficient'])} | "
                 f"{pct(s['error_among_decided'])} |")
    L += ["", "## Gap by population (measure, per round)", "",
          "| population | true gap r1 / r2 / r3 | round | CREDIBLE | NO_CREDIBLE | INSUFFICIENT |",
          "|---|---|---|---|---|---|"]
    for p, d in r["gap_by_population"].items():
        tg = " / ".join(f"{v:.2f}" for v in d["mean_true_gap_by_round"].values())
        for rd, sh in d["measure_by_round"].items():
            L.append(f"| {p} | {tg} | {rd} | {pct(sh.get(G.CREDIBLE_GAP))} | "
                     f"{pct(sh.get(G.NO_CREDIBLE_GAP))} | {pct(sh.get(G.INSUFFICIENT))} |")
    L += ["", "## Gap by population: measure vs baselines (all rounds)", "",
          "| population | method | false gap | wrong 'no gap' | insufficient |", "|---|---|---|---|---|"]
    for p, d in r["gap_by_population"].items():
        for k in ("measure", "point", "last"):
            s = d[k]
            L.append(f"| {p} | {k} | {pct(s['false_yes'])} | {pct(s['wrong_no'])} | {pct(s['insufficient'])} |")
    L += ["", "## Reduction (round 1 → round 3)", "",
          "| method | found (true reduction) | false reduction | wrong 'not reduced' | insufficient | error among decided |",
          "|---|---|---|---|---|---|"]
    for k, s in r["reduction_overall"].items():
        L.append(f"| {k} | {pct(s['found'])} | {pct(s['false_yes'])} | {pct(s['wrong_no'])} | "
                 f"{pct(s['insufficient'])} | {pct(s['error_among_decided'])} |")
    L += ["", "| population | mean true reduction | REDUCED | NOT_REDUCED | INSUFFICIENT | most common status paths |",
          "|---|---|---|---|---|---|"]
    for p, d in r["reduction_by_population"].items():
        sh = d["measure"]
        paths = ", ".join(f"{k} ({v})" for k, v in d["top_paths"])
        L.append(f"| {p} | {d['mean_true_reduction']:.2f} | {pct(sh.get(G.REDUCED))} | "
                 f"{pct(sh.get(G.NOT_REDUCED))} | {pct(sh.get(G.INSUFFICIENT))} | {paths} |")
    L += ["", "## Threshold sensitivity", "", "| gap threshold | found | false gap | wrong 'no gap' | insufficient |",
          "|---|---|---|---|---|"]
    for t, s in r["sensitivity_gap"].items():
        L.append(f"| {t} | {pct(s['found'])} | {pct(s['false_yes'])} | {pct(s['wrong_no'])} | {pct(s['insufficient'])} |")
    L += ["", "| reduction threshold | found | false reduction | wrong 'not reduced' | insufficient |",
          "|---|---|---|---|---|"]
    for t, s in r["sensitivity_reduction"].items():
        L.append(f"| {t} | {pct(s['found'])} | {pct(s['false_yes'])} | {pct(s['wrong_no'])} | {pct(s['insufficient'])} |")
    L += ["", "## Group level (cohort = one population; bootstrap over learners)", "",
          "| population | mean raw gap r1 / r2 / r3 | mean reduction (95% CI) | P(> 0.1) | status | true mean reduction |",
          "|---|---|---|---|---|---|"]
    for p, d in r["group_level"].items():
        g = " / ".join(f"{v['mean']:.2f}" for v in d["mean_gap_by_round"].values())
        red = d["reduction"]
        L.append(f"| {p} | {g} | {red['mean']:.3f} ({red['ci95'][0]:.3f}–{red['ci95'][1]:.3f}) | "
                 f"{red['p_reduced']:.2f} | {red['status']} | {d['true_mean_reduction']:.3f} |")
    L += ["", f"Inputs: run answers sha256 {r['inputs']['run_answers_sha256'][:16]}…, "
          f"calibration sha256 {r['inputs']['calibration_sha256'][:16]}…", ""]
    return "\n".join(L)


def render_confidence(r) -> str:
    from gap import confidence as C
    A, B, N, I = C.ABOVE, C.BELOW, C.NONE, "INSUFFICIENT_EVIDENCE"
    L = ["# SCRUM-95 — perceived-versus-demonstrated gap (confidence): validation results", "",
         f"Thresholds: gap ±{r['thresholds']['gap']}, reduction {r['thresholds']['reduction']}, "
         f"prior weight {r['thresholds']['prior_weight']} answers centred on no gap.", "",
         "Norms (share correct per confidence level 1..5): main (all populations, missing not at "
         "random) " + ", ".join(f"{k}:{v:.3f}" for k, v in sorted(r["norm_main"].items(), key=lambda x: int(x[0])))
         + "; clean (calibrated populations) "
         + ", ".join(f"{k}:{v:.3f}" for k, v in sorted(r["norm_clean"].items(), key=lambda x: int(x[0]))) + ".", "",
         "## No self-report", "",
         f"Never-reporters flagged NO_SELF_REPORT: {pct(r['no_self_report']['never_reporters_flagged'])}; "
         f"reporters flagged: {pct(r['no_self_report']['reporters_flagged'])}.", "",
         "## Overall (round cases of reporting learners)", "",
         "| variant | found ABOVE | false ABOVE | cluster | found BELOW | false BELOW | found NONE | insufficient | error among decided |",
         "|---|---|---|---|---|---|---|---|---|"]
    rows = dict(r["overall"]); rows["naive (conf>=4 & last wrong)"] = r["naive"]
    for k, s in rows.items():
        L.append(f"| {k} | {pct(s['found_' + A])} | {pct(s['false_' + A])} | {cl(s['false_' + A + '_cluster'])} | "
                 f"{pct(s['found_' + B])} | {pct(s['false_' + B])} | {pct(s['found_NONE'])} | "
                 f"{pct(s['insufficient'])} | {pct(s['error_among_decided'])} |")
    L += ["", "## By population (main)", "",
          "| population | mean true inflation | truth ABOVE | ABOVE | NONE | BELOW | INSUFFICIENT | naive ABOVE | clean-norm ABOVE / BELOW | discrimination |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for p, d in r["by_population"].items():
        m = d["measure"]; cn = d["clean_norm"]
        disc = "—" if d["mean_discrimination"] is None else f"{d['mean_discrimination']:.2f}"
        L.append(f"| {p} | {d['mean_true_gap']:+.2f} | {pct(d['truth'].get(A))} | {pct(m.get(A))} | {pct(m.get(N))} | "
                 f"{pct(m.get(B))} | {pct(m.get(I))} | {pct(d['naive_above'])} | "
                 f"{pct(cn.get(A))} / {pct(cn.get(B))} | {disc} |")
    L += ["", "## Answers needed to find a true ABOVE gap (round 1, reported answers)", "",
          "| population | cases | found within the round | median answers | distribution |", "|---|---|---|---|---|"]
    for p, d in r["answers_to_detect"].items():
        L.append(f"| {p} | {d['cases']} | {pct(d['found_in_round1'])} | {d['median']} | {d['distribution']} |")
    L += ["", "## Reduction (|gap| round 1 → round 3)", "",
          "| variant | found | false REDUCED | insufficient |", "|---|---|---|---|"]
    for k, s in r["reduction_overall"].items():
        L.append(f"| {k} | {pct(s['found'])} | {pct(s['false_reduced'])} | {pct(s['insufficient'])} |")
    L += ["", "| population | mean true reduction | REDUCED | NOT_REDUCED | INSUFFICIENT |", "|---|---|---|---|---|"]
    for p, d in r["reduction"].items():
        m = d["measure"]
        L.append(f"| {p} | {d['mean_true']:+.3f} | {pct(m.get('REDUCED'))} | {pct(m.get('NOT_REDUCED'))} | {pct(m.get(I))} |")
    return "\n".join(L) + "\n"
