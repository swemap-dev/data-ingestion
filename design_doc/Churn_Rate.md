# Technical Spec: SWEMAP Risk Dashboard - Change Frequency (File Churn)

## 1. Objective
Calculate a **Risk Score (0-10)** for every file in a repository based on the weighted frequency of its inclusion in Pull Requests (PRs). This metric identifies "Hotspots" where high churn indicates architectural fragility or high maintenance overhead.

---

## 2. Mathematical Model: Weighted Temporal Decay
Instead of raw counts, we use a **Generalized Logistic Function (Sigmoid)** to weight each PR event based on its "freshness" ($t$), where $t$ is the number of days since the PR was merged.

### 2.1 The Decay Function
For each PR event $i$ on a file, the weight $W_i$ is calculated as:

$$W(t) = L + \frac{H - L}{1 + e^{k(t - x_0)}}$$

**Constants (Optimized for 2-Week Sprint Cycles):**
| Constant | Value | Description |
| :--- | :--- | :--- |
| **$H$ (High)** | **1.0** | Maximum risk weight for a brand-new change. |
| **$L$ (Low)** | **0.1** | The "Legacy Plateau." Old changes retain 10% weight as baseline risk. |
| **$x_0$ (Midpoint)** | **21** | The "Cliff" center (21 days). Risk drops sharply after 3 weeks. |
| **$k$ (Steepness)** | **0.5** | Controls the decay slope (approx. 7–10 day transition). |



### 2.2 Aggregate File Score
The **Raw Score ($S_{raw}$)** for a file is the sum of weights for all PRs within the lookback period $Z$:

$$S_{raw} = \sum_{i=1}^{n} W(t_i)$$

---

## 3. Scoring & Normalization Logic
To convert $S_{raw}$ into a human-readable **0-10 User Score ($R$):**

1.  **Percentile Ranking:** Calculate the percentile rank of the file's $S_{raw}$ relative to all other files in the repository to handle "Mega-Changelog" outliers.
2.  **Relative Mapping:** Map the percentile rank to the 0-10 scale.
3.  **Absolute Threshold Capping:**
    * **High Cap:** If $S_{raw} \geq X$ (Default $X=2.0$), the highest-ranked file gets a **10**. If the highest $S_{raw} < X$, it is capped at **7**.
    * **Low Cap:** If $S_{raw} \leq Y$ (Default $Y=0.1$), the lowest-ranked file gets a **1**. If the lowest $S_{raw} > Y$, it is capped at **3**.

---

## 4. Feature Definitions
* **Hotspots:** Files with a User Score $R \geq 8$.
* **Lookback Period ($Z$):** 180 days (6 months) default.
* **Analysis Window:** 30 days (for primary freshness).

---

## 5. Implementation Roadmap & Mental Notes

### 5.1 Future Feature: Semantic Weighting
The current model treats all changes equally. Future iterations will introduce a `SignificanceFactor` (SF) to the summation:
$$S_{raw} = \sum (W(t_i) \times SF_i)$$
* **Brain Files:** $SF = 2.0$
* **Documentation:** $SF = 0.1$
* **Automated/Bot PRs:** $SF = 0.05$

### 5.2 Edge Case Handling
* **Revert Noise:** Filter out "Revert" PRs or apply negative weight to avoid penalizing files that have been safely rolled back.
* **File Renames:** Use Git `follow` logic to ensure risk history is preserved when a file is moved/renamed.
* **The Quiet Repo:** If repository variance is negligible ($\Delta S_{raw} < \epsilon$), default all scores to a neutral **3** to avoid false volatility.
* **Monolith vs. Microservice:** Currently assumes uniform repo structure. Future work includes auto-scaling $X$ and $Y$ based on total repository file count.