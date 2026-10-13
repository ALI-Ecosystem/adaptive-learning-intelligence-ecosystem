"""Small hide-and-replace test on Hebrew learner conversations.

Ten computer-science concepts whose parent is a plain fact of the source (one parent,
unflagged, no children) are hidden, and the agent places each one again from a short
Hebrew student message. The messages describe the concept, and most do not give its
English name, so the agent also has to work out which concept is meant.

Usage: python -m placement.hebrew_eval
Output: runs/hebrew-eval/results.csv (with an empty kody_verdict column) + traces
"""
import csv

from . import config
from .agent import make_client, run_agent
from .evaluate import outcome
from .graph import Graph, connect
from .traces import save_trace

CASES = [
    ("C2778937211", "היי, בתרגול של מבני נתונים הראו מיון שבוחרים בו איבר ציר, מחלקים את המערך "
                    "לקטנים ממנו ולגדולים ממנו, וממיינים כל צד ברקורסיה. למה במקרה הגרוע זה n בריבוע?"),
    ("C121610932", "אני לא מבין למה חיפוש בינארי עובד רק על מערך ממוין. כל פעם חותכים את הטווח לחצי?"),
    ("C62692426", "במטלה צריך לממש סריקה לעומק של גרף עם מחסנית. מה ההבדל בינה לבין סריקה לרוחב?"),
    ("C2777667771", "בעבודה קיבלנו התראה על נוזקת כופרה שמצפינה את הקבצים ודורשת תשלום בביטקוין. "
                    "איך היא בדרך כלל נכנסת לארגון?"),
    ("C39569185", "בקורס אבטחת מידע דיברו על התקפה שבה מזריקים סקריפט לדף אינטרנט דרך שדה קלט, "
                  "והוא רץ אצל משתמשים אחרים שנכנסים לדף. איך מתגוננים מזה?"),
    ("C158338273", "שמעתי על הצפנה שמאפשרת לעשות חישובים על מידע מוצפן בלי לפענח אותו קודם. "
                   "זה באמת אפשרי?"),
    ("C76399640", "במערכות הפעלה לא הבנתי את הרעיון של זיכרון וירטואלי. איך כל תהליך חושב שיש לו "
                  "את כל הזיכרון לעצמו?"),
    ("C200568363", "למה בג'אווה מחלקה לא יכולה לרשת משתי מחלקות ובפייתון כן? מה הבעיה עם ירושה מרובה?"),
    ("C207968372", "בקורס למידת מכונה צריך לחלק לקוחות לקבוצות עם אלגוריתם שבוחר k מרכזים ומעדכן "
                   "אותם שוב ושוב. איך בוחרים את k?"),
    ("C54108766", "בבדיקת רשת ראיתי אחוז גבוה של אובדן חבילות בפינג. ממה זה נובע ואיך זה משפיע על TCP?"),
]


def main():
    graph = Graph(connect())
    client = make_client()
    out_dir = config.RUNS_DIR / "hebrew-eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, text in CASES:
        c = graph.concept(cid)
        truth = c["parents"][0]
        g = graph.with_hidden({cid})
        res = run_agent("סטודנט: " + text, g, client)
        save_trace(res, {"eval_item": cid, "truth": truth["id"]}, out_dir / "traces")
        d = res.decision or {}
        pred = d.get("parent_id") if d.get("decision") == "new" else None
        row = {"hidden_concept": c["name"], "agent_named_it": d.get("concept_name", ""),
               "true_parent": truth["name"],
               "agent_parent": (g.concept(pred) or {}).get("name", "") if pred else
                               f"said exists: {d.get('existing_id')}",
               "outcome": outcome(g, pred, truth["id"]), "confidence": d.get("confidence"),
               "reasoning": d.get("reasoning", ""), "kody_verdict": ""}
        rows.append(row)
        print(f"{c['name']:30} named {row['agent_named_it']:30} -> {row['agent_parent']:35} "
              f"(source: {truth['name']}) {row['outcome']}")
    with (out_dir / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    exact = sum(r["outcome"] == "exact" for r in rows)
    named = sum(r["agent_named_it"].lower() == r["hidden_concept"].lower() for r in rows)
    print(f"\nexact parent {exact}/{len(rows)}, concept named exactly {named}/{len(rows)}")
    print(f"results: {out_dir / 'results.csv'}")
    graph.driver.close()


if __name__ == "__main__":
    main()
