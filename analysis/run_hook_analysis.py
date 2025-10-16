import os, math, itertools, argparse
import pandas as pd
import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score

from analysis.config import AnalysisConfig
from analysis.column_map import COLUMN_MAP

CFG = AnalysisConfig()

def load_and_map(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # rename columns to analysis names
    rename = {src: dest for src, dest in COLUMN_MAP.items() if src in df.columns}
    df = df.rename(columns=rename)
    # sanity: required columns
    required = ["post_id","account_id","posted_at","followers","views","hours_since_post"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # auto-scale face_pct_1s if it's in 0..100
    if "face_pct_1s" in df.columns:
        m = df["face_pct_1s"].dropna()
        if len(m) and m.max() > 1.5:  # likely percentage
            df["face_pct_1s"] = df["face_pct_1s"] / 100.0

    # coerce numeric
    numeric_cols = list(set(CFG.hook_prob_cols + CFG.cont_hook_cols + ["followers","views","hours_since_post"]))
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # parse posted_at to datetime
    df["posted_at"] = pd.to_datetime(df["posted_at"], errors="coerce")
    return df

def build_target(df: pd.DataFrame, beta: float) -> pd.DataFrame:
    f = df["followers"].clip(lower=1)
    h = df["hours_since_post"].clip(lower=1)
    y = np.log1p(df["views"]) - np.log1p(f) - beta*np.log1p(h)
    # winsorize to stabilize
    low, high = y.quantile(0.01), y.quantile(0.99)
    df["y_norm"] = y.clip(lower=low, upper=high)
    return df

def spearman_table(df: pd.DataFrame, feats: list, target="y_norm") -> pd.DataFrame:
    rows=[]
    for f in feats:
        if f not in df.columns:
            continue
        mask = df[f].notna() & df[target].notna()
        if mask.sum() < 20:
            continue
        rho,p = spearmanr(df.loc[mask, f], df.loc[mask, target])
        rows.append({"feature": f, "n": int(mask.sum()), "rho": rho, "p": p})
    out = pd.DataFrame(rows).sort_values("rho", ascending=False)
    return out

def make_pairs(df: pd.DataFrame, pair_feats: list):
    pairs = []
    # group by account and week
    df = df.copy()
    df["week"] = df["posted_at"].dt.to_period("W").astype(str)
    for (acct, wk), g in df.groupby(["account_id","week"]):
        g = g.sort_values("posted_at")
        idx = g.index.to_list()
        for i,j in itertools.combinations(idx, 2):
            yi, yj = g.loc[i, "y_norm"], g.loc[j, "y_norm"]
            if pd.isna(yi) or pd.isna(yj):
                continue
            xi = g.loc[i, pair_feats]
            xj = g.loc[j, pair_feats]
            if xi.isna().any() or xj.isna().any():
                continue
            xdiff = (xi.values - xj.values)
            y = 1 if yi > yj else 0
            pairs.append((xdiff, y))
    if not pairs:
        return None, None
    X = np.vstack([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    return X, y

def pairwise_rank(X: np.ndarray, y: np.ndarray, feature_names: list, seed=42):
    logit = LogisticRegression(max_iter=1000, solver="lbfgs")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    aucs, coefs = [], []
    for tr, te in cv.split(X, y):
        logit.fit(X[tr], y[tr])
        pred = logit.predict_proba(X[te])[:,1]
        aucs.append(roc_auc_score(y[te], pred))
        coefs.append(logit.coef_[0])
    coef_mean = np.mean(coefs, axis=0)
    imp = pd.DataFrame({
        "feature": feature_names,
        "coef_mean": coef_mean
    }).sort_values("coef_mean", ascending=False)
    return float(np.mean(aucs)), float(np.std(aucs)), imp

def interaction_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    # shock x early proof
    if {"hook_prob_shock_violation","payoff_time_sec"}.issubset(df.columns):
        z = df[["hook_prob_shock_violation","payoff_time_sec","y_norm"]].dropna()
        z["shock_x_earlyproof"] = z["hook_prob_shock_violation"] * (z["payoff_time_sec"] <= 1.0).astype(int)
        rho,p = spearmanr(z["shock_x_earlyproof"], z["y_norm"])
        rows.append({"interaction":"shock_x_earlyproof","n":len(z),"rho":rho,"p":p})
    # relatable x humor
    if {"hook_prob_relatable_slice","hook_prob_humor_gag"}.issubset(df.columns):
        z = df[["hook_prob_relatable_slice","hook_prob_humor_gag","y_norm"]].dropna()
        z["relatable_x_humor"] = z["hook_prob_relatable_slice"] * z["hook_prob_humor_gag"]
        rho,p = spearmanr(z["relatable_x_humor"], z["y_norm"])
        rows.append({"interaction":"relatable_x_humor","n":len(z),"rho":rho,"p":p})
    return pd.DataFrame(rows)

def bucket_tests(df: pd.DataFrame, rules: dict, target="y_norm") -> pd.DataFrame:
    out=[]
    for name, expr in rules.items():
        try:
            cond = df.eval(expr)
        except Exception:
            continue
        a = df.loc[cond & df[target].notna(), target]
        b = df.loc[(~cond) & df[target].notna(), target]
        if len(a) >= 20 and len(b) >= 20:
            d = float(a.median() - b.median())
            out.append({"rule": name, "n_true": int(len(a)), "n_false": int(len(b)), "delta_median": d,
                        "median_true": float(a.median()), "median_false": float(b.median())})
    return pd.DataFrame(out).sort_values("delta_median", ascending=False)

def write_playbook(univariate: pd.DataFrame, pair_imp: pd.DataFrame, inter: pd.DataFrame, buckets: pd.DataFrame, out_path: str):
    lines=[]
    lines.append("# Dog Niche Hook Playbook (Data-Driven)")
    lines.append("")
    lines.append("## TL;DR")
    # Quick bullets based on buckets and signs
    if not buckets.empty:
        top = buckets.head(5)
        for _,r in top.iterrows():
            lines.append(f"- **{r['rule']}** → Δmedian = {r['delta_median']:.3f} (n_true={r['n_true']}, n_false={r['n_false']})")
    lines.append("")
    lines.append("## Univariate Signals (Spearman vs normalized views)")
    if not univariate.empty:
        lines.append(univariate.to_string(index=False))
    lines.append("")
    lines.append("## Pairwise Ranking (within account & week)")
    if not pair_imp.empty:
        lines.append(pair_imp.to_string(index=False))
    lines.append("")
    lines.append("## Interactions")
    if not inter.empty:
        lines.append(inter.to_string(index=False))
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to scraped data CSV")
    ap.add_argument("--outdir", default="results", help="Output directory for reports")
    ap.add_argument("--beta", type=float, default=CFG.time_decay_beta, help="Time decay beta for normalization")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    df = load_and_map(args.csv)
    df = build_target(df, beta=args.beta)

    # Univariate
    uni_feats = CFG.hook_prob_cols + CFG.cont_hook_cols
    univariate = spearman_table(df, uni_feats, target="y_norm")
    univariate.to_csv(os.path.join(args.outdir, "univariate.csv"), index=False)

    # Pairwise ranking
    X, y = make_pairs(df, CFG.pairwise_features)
    if X is not None and len(y) >= 50:
        auc_mean, auc_sd, imp = pairwise_rank(X, y, CFG.pairwise_features)
        imp["note_auc_mean"] = auc_mean
        imp["note_auc_sd"] = auc_sd
        imp.to_csv(os.path.join(args.outdir, "pairwise_weights.csv"), index=False)
    else:
        imp = pd.DataFrame()

    # Interactions
    interactions = interaction_tests(df)
    interactions.to_csv(os.path.join(args.outdir, "interactions.csv"), index=False)

    # Buckets
    buckets = bucket_tests(df, CFG.bucket_rules, target="y_norm")
    buckets.to_csv(os.path.join(args.outdir, "buckets.csv"), index=False)

    # Playbook
    write_playbook(univariate, imp, interactions, buckets, os.path.join(args.outdir, "playbook.md"))

    print(f"✅ Done. See folder: {args.outdir}")
    if X is not None:
        print(f"Pairwise pairs: {len(y)}  |  AUC(mean±sd): {imp['note_auc_mean'].iloc[0]:.3f}±{imp['note_auc_sd'].iloc[0]:.3f}" if not imp.empty else "Pairwise computed.")
    else:
        print("Pairwise ranking skipped (insufficient matched pairs).")

if __name__ == "__main__":
    main()
