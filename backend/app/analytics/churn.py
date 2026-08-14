"""
Churn / at-risk customer scoring.

This is the one genuinely *trained, supervised* ML model in the project
(forecasting is a linear fit, anomaly detection is a z-score threshold --
neither is "fit a model to labeled examples"). Everything else in this
app answers "what happened and why"; this answers "who should I worry
about."

Methodology, explicitly to avoid leakage:
- Time is split into periods (quarters). Each period after the first is
  a candidate "cutoff": features are built ONLY from orders before the
  cutoff, and the label is whether the customer had any order DURING
  the cutoff period. A customer's future is never used to build their
  own features.
- The EARLIEST cutoffs are used for training, the LATEST cutoff is held
  out entirely for evaluation -- a walk-forward split, not a random
  shuffle, since a random split would let the model train on a later
  point in time than some of its test examples, which is a subtle form
  of leakage for time-series-shaped data.
- A final production model is retrained on all cutoffs combined (train
  + eval) once evaluation is done, then used to score current customers
  against the most up-to-date feature window -- standard practice:
  validate on a holdout, then retrain on everything for deployment.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

from app.data import catalog
from app.analytics import multi_table


class ChurnError(Exception):
    pass


NUMERIC_FEATURES = ["frequency", "monetary", "avg_order_value", "recency_days", "n_periods_active"]


def _get_period_boundaries(con, table_name, date_column):
    df = con.execute(f"""
        SELECT DISTINCT date_trunc('quarter', {date_column}) AS period
        FROM "{table_name}" ORDER BY period
    """).fetchdf()
    return list(df["period"])


def _build_features(con, table_name, id_column, metric_column, date_column, window_start, window_end):
    df = con.execute(f"""
        SELECT "{id_column}" AS customer_id,
               count(*) AS frequency,
               sum({metric_column}) AS monetary,
               avg({metric_column}) AS avg_order_value,
               max({date_column}) AS last_order_date,
               count(DISTINCT date_trunc('quarter', {date_column})) AS n_periods_active
        FROM "{table_name}"
        WHERE {date_column} >= ? AND {date_column} < ?
        GROUP BY 1
    """, [window_start, window_end]).fetchdf()

    if df.empty:
        return df
    df["recency_days"] = (pd.Timestamp(window_end) - pd.to_datetime(df["last_order_date"])).dt.days
    return df.drop(columns=["last_order_date"])


def _active_customer_ids(con, table_name, id_column, date_column, window_start, window_end):
    df = con.execute(f"""
        SELECT DISTINCT "{id_column}" AS customer_id
        FROM "{table_name}"
        WHERE {date_column} >= ? AND {date_column} < ?
    """, [window_start, window_end]).fetchdf()
    return set(df["customer_id"])


def _build_examples_for_cutoff(con, table_name, id_column, metric_column, date_column, feature_start, cutoff, next_cutoff):
    """One row per customer active in [feature_start, cutoff): features from
    that window, label = did NOT reappear in [cutoff, next_cutoff)."""
    features = _build_features(con, table_name, id_column, metric_column, date_column, feature_start, cutoff)
    if features.empty:
        return features
    active_in_label_window = _active_customer_ids(con, table_name, id_column, date_column, cutoff, next_cutoff)
    features["churned"] = (~features["customer_id"].isin(active_in_label_window)).astype(int)
    return features


def train_and_score_churn(
    dataset_id: str,
    id_column: str,
    metric_column: str,
    date_column: str,
    top_n: int = 20,
) -> dict:
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise ChurnError("Dataset not found.")

    con = catalog.get_connection(dataset_id)
    try:
        try:
            table_name, available_columns = multi_table.resolve_base_table(
                con, dataset_id, metric_column, date_column
            )
        except multi_table.MultiTableError as e:
            raise ChurnError(str(e))

        col_names = {c["name"] for c in available_columns}
        if id_column not in col_names:
            raise ChurnError(f"'{id_column}' is not a column in this dataset.")

        periods = _get_period_boundaries(con, table_name, date_column)
        if len(periods) < 3:
            raise ChurnError(
                f"Need at least 3 time periods to train + evaluate with a "
                f"held-out split; found {len(periods)}."
            )

        feature_start = periods[0]
        cutoffs = periods[1:]  # each period after the first can be a label window
        # cutoff's own "next boundary" -- end of its label window
        cutoff_bounds = []
        for i, c in enumerate(cutoffs):
            next_c = cutoffs[i + 1] if i + 1 < len(cutoffs) else (
                pd.Timestamp(c) + pd.DateOffset(months=3)
            )
            cutoff_bounds.append((c, next_c))

        # earliest cutoffs -> train, last cutoff -> held-out test
        train_bounds = cutoff_bounds[:-1]
        test_bound = cutoff_bounds[-1]

        train_frames = [
            _build_examples_for_cutoff(con, table_name, id_column, metric_column, date_column, feature_start, c, nc)
            for c, nc in train_bounds
        ]
        train_df = pd.concat([f for f in train_frames if not f.empty], ignore_index=True) if train_frames else pd.DataFrame()

        test_df = _build_examples_for_cutoff(
            con, table_name, id_column, metric_column, date_column, feature_start, test_bound[0], test_bound[1]
        )

        if train_df.empty or test_df.empty:
            raise ChurnError("Not enough active customers in the training/test windows to fit a model.")
        if train_df["churned"].nunique() < 2:
            raise ChurnError("Training data has only one class (all churned or all retained) -- can't fit a classifier.")

        scaler = StandardScaler()
        X_train = scaler.fit_transform(train_df[NUMERIC_FEATURES].fillna(0))
        y_train = train_df["churned"].values
        X_test = scaler.transform(test_df[NUMERIC_FEATURES].fillna(0))
        y_test = test_df["churned"].values

        model = LogisticRegression(class_weight="balanced", max_iter=1000)
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1]

        metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 3),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 3),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 3),
            "roc_auc": round(float(roc_auc_score(y_test, y_proba)), 3) if y_test.sum() not in (0, len(y_test)) else None,
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "test_churn_rate": round(float(y_test.mean()), 3),
        }

        feature_importance = {
            feat: round(float(coef), 3)
            for feat, coef in zip(NUMERIC_FEATURES, model.coef_[0])
        }

        # retrain on everything (train + held-out test) for the deployed model
        full_df = pd.concat([train_df, test_df], ignore_index=True)
        final_scaler = StandardScaler()
        X_full = final_scaler.fit_transform(full_df[NUMERIC_FEATURES].fillna(0))
        final_model = LogisticRegression(class_weight="balanced", max_iter=1000)
        final_model.fit(X_full, full_df["churned"].values)

        # score CURRENT customers using the most up-to-date feature window
        current_end = pd.Timestamp(periods[-1]) + pd.DateOffset(months=3)
        current_features = _build_features(con, table_name, id_column, metric_column, date_column, feature_start, current_end)
        if current_features.empty:
            raise ChurnError("No current customer activity to score.")

        X_current = final_scaler.transform(current_features[NUMERIC_FEATURES].fillna(0))
        current_features["churn_probability"] = final_model.predict_proba(X_current)[:, 1]

        at_risk = (
            current_features.sort_values("churn_probability", ascending=False)
            .head(top_n)[["customer_id", "churn_probability", "recency_days", "frequency", "monetary"]]
        )
        at_risk_list = [
            {
                "customer_id": str(r["customer_id"]),
                "churn_probability": round(float(r["churn_probability"]), 3),
                "recency_days": int(r["recency_days"]),
                "frequency": int(r["frequency"]),
                "monetary": round(float(r["monetary"]), 2),
            }
            for _, r in at_risk.iterrows()
        ]

        return {
            "metrics": metrics,
            "feature_importance": feature_importance,
            "at_risk_customers": at_risk_list,
        }
    finally:
        con.close()