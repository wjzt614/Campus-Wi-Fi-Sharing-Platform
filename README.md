# Campus Wi-Fi Sharing Platform

Based on game-theory incentive mechanisms for campus bandwidth sharing

## Project Overview

This system is a campus Wi-Fi bandwidth sharing platform. Through multiple game-theory mechanisms such as a reputation system, token incentives, coalition games, and trust guarantees, it turns the "use without sharing" prisoner's dilemma into a cooperation equilibrium where sharing more is more beneficial. This encourages students to proactively share idle bandwidth.

## Tech Stack

- Backend: Python + FastAPI + SQLAlchemy
- Database: SQLite (auto-created; no configuration needed)
- Frontend: HTML / CSS / JavaScript + Chart.js
- Realtime push: Server-Sent Events (SSE)

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Open in your browser: `http://localhost:8000`

## Core Features

### User system
- Register / login. Accounts are bound long-term to support an infinitely repeated game.
- A 7-day protection period after new user registration: no rejection and no freezing, but price penalties still apply.

### Bandwidth management
- Share bandwidth: contribute idle bandwidth and receive an immediate credit reward; when others consume your bandwidth, flow currency is credited to you in real time.
- Request bandwidth: show a preview before consuming (cost, credit changes, rejection risk); you cannot consume bandwidth you shared.
- Bandwidth pool dashboard: shows the total amount, your maximum requestable amount, your contributed amount, and the current dynamic price.

### Reputation system (Credit)
| Level | Credit value | Badge | Discount |
|------|--------------|-------|----------|
| Eagle | >= 90 | 🦅 | Consumption price -30% |
| Tiger | >= 70 | 🐯 | Consumption price -15% |
| Dolphin | >= 50 | 🐬 | Standard price |
| Turtle | < 50 | 🐢 | Paused / limited use |

- Sharing bandwidth -> credit increases (peak-hour rewards are doubled).
- Consuming bandwidth -> credit slightly decreases (-0.05 / MB).

### Flow currency (Token incentives)
- Real circulation: the flow currency paid by consumers is directly transferred to the sharer.
- SSE realtime push: when others consume your bandwidth, your balance updates instantly with an animation hint.
- Guarantee commission: after guaranteeing someone, you automatically receive a 1% commission on each consumption made by the guaranteed user.

### Sharing ratio & penalties (30-day rolling window)
| Sharing ratio | Outcome |
|----------------|---------|
| >= 20% | Normal |
| 10% ~ 20% | Consumption price +50% |
| < 10% | Price +100% + linear rejection probability (0% => 100% rejection) |
| 5 accumulated low-sharing rejections | Account frozen for 3 days |

### Sharing gain (discount factor delta)
- Formula: `delta = min(0.99, 0.5 + 0.005 * min(reputation_score, 100) + 0.1 * min(recent_sharing_rate, 1.0))`
- Affects the credit reward multiplier for sharing (1.0x to 2.0x). More active users have higher sharing gains.

### Coalition / mutual-aid groups
- Create / join mutual-aid groups. When consuming, members inside the group are matched with priority, with an extra 8% discount.
- The discounts saved inside the group are aggregated into a "group jackpot" and distributed by Shapley values based on each member's contributed bandwidth.

### Trust guarantee
- Credit >= 70 (Tiger level and above) can guarantee new users.
- The guaranteed user gains increased trust quota and receives 50 flow currency.
- The guarantor receives a 1% commission on each consumption made by the guaranteed user.

### Dynamic pricing
- Bandwidth pool < 80% of benchmark: base price +10%
- Bandwidth pool > 120% of benchmark: base price -10%

### Leaderboard
- Sorted by credit. Top 10% users are marked 🏅 and receive an extra 5% consumption discount.
- Badges: Sharing Star (share > 500MB), Mutual-Aid Expert (Eagle level).

### Anti wash-trading detection
- If bidirectional transactions exceed 10MB within 1 hour, the sharer's additional reputation/credit gain for that consumption is withheld (flow currency transfer still happens) to prevent credit washing.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/register | Register |
| POST | /api/login | Login |
| GET | /api/user-stats/{id} | User status |
| POST | /api/share-bandwidth | Share bandwidth |
| POST | /api/request-bandwidth | Request bandwidth |
| GET | /api/cost-preview | Cost preview (before consuming) |
| GET | /api/available-bandwidth | Bandwidth pool status |
| POST | /api/coalition/create | Create mutual-aid group |
| POST | /api/coalition/join | Join mutual-aid group |
| GET | /api/coalition/{id} | Mutual-aid group details |
| GET | /api/coalitions | All mutual-aid groups |
| POST | /api/trust/guarantee | Guarantee a user |
| GET | /api/leaderboard | Leaderboard |
| GET | /api/currency-stream/{id} | SSE realtime flow-currency stream |

## Project Structure

```
├── main.py              # Backend entry (FastAPI + game-theory engine)
├── requirements.txt     # Python dependencies
├── campus_wifi.db       # SQLite database (auto-created)
├── templates/
│   └── index.html       # Frontend main page
├── static/
│   ├── style.css        # Styles
│   └── script.js        # Frontend logic
└── README.md            # Project documentation
```

## Startup Notes & FAQ

### Notes

1. On the first run, `campus_wifi.db` is auto-created; data is preserved after restarts.
2. The default port is `8000`. If it is occupied, modify the `port` parameter at the end of `main.py`.
3. Delete `campus_wifi.db` to reset all data.

### FAQ

Q: Registration prompt: "Email already registered"
A: Use another email, or log in to the existing account.

Q: Bandwidth request prompt: "No available bandwidth"
A: The bandwidth pool is currently empty. Another user needs to share bandwidth first.

Q: Flow currency is insufficient
A: Share bandwidth first, and then wait for others to consume it; flow currency will be credited automatically.

Q: Account is frozen
A: If the sharing ratio stays below 10% and you have 5 accumulated rejections, the account is frozen for 3 days. The freeze lifts automatically after the period ends.

## Game-Theory Incentive Mechanisms (Detailed)

### Core Problem

Campus Wi-Fi sharing is essentially a **public resource game**:

- Every student wants to use bandwidth shared by others (free-riding).
- But if everyone only uses without sharing, the bandwidth pool will be depleted and the system collapses.
- This is the classic **Prisoner's Dilemma**: individual rationality leads to collective irrationality.

This system converts a single interaction into an infinitely repeated game using layered game-theory mechanisms, making "sharing bandwidth" the dominant strategy for each rational user. As a result, cooperation becomes an equilibrium.

---

### Mechanism 1: Repeated game + discount factor (delta)

**Principle**: In a one-shot game, betrayal (not sharing) is the dominant strategy. However, when the game is repeated infinitely, cooperation becomes equilibrium as long as the discounted future benefits are large enough.

**Implementation**:

- User accounts are long-term bound, so each interaction is a round of the repeated game.
- Discount factor: `delta = min(0.99, 0.5 + 0.005 * min(credit_value, 100) + 0.1 * min(recent_sharing_rate, 1.0))`.
- A higher `delta` yields a higher credit reward multiplier for sharing (1.0x to 2.0x).
- More active users have a higher `delta`, giving more weight to future benefits, and making them more likely to keep cooperating.

**Effect**: Users maintain active sharing behavior to keep `delta` high (high sharing gains).

---

### Mechanism 2: Reputation system (Credit value)

**Principle**: Reputation addresses information asymmetry, forming a **separating equilibrium**. High-quality users actively maintain reputation; low-quality users are isolated by the system.

**Implementation**:

- Sharing bandwidth -> credit increases.
- Consuming bandwidth -> credit slightly decreases (-0.05 / MB).
- Credit levels determine consumption discounts:

| Level | Credit value | Discount |
|------|--------------|----------|
| 🦅 Eagle | >= 90 | -30% |
| 🐯 Tiger | >= 70 | -15% |
| 🐬 Dolphin | >= 50 | Standard price |
| 🐢 Turtle | < 50 | Paused / limited use |

**Effect**: High-credit users enjoy discounts, while low-credit users are restricted. This creates a positive loop: sharing -> reputation increases -> discounts increase -> users are more willing to consume -> users are more willing to share.

---

### Mechanism 3: Token incentives (Flow currency)

**Principle**: Token incentives with real circulation create quantifiable economic benefits for sharing, making incentives compatible.

**Implementation**:

- Sharing bandwidth does not directly grant tokens, avoiding "getting benefits without contributing".
- When others consume your bandwidth, flow currency is transferred to you in real time.
- SSE push: balance changes are shown immediately, reinforcing instant feedback.
- Guarantee commission: after you guarantee someone, you automatically receive 1% commission on every consumption made by the guaranteed user.

**Effect**: Real flow currency circulation gives clear economic incentives for sharing. The guarantee mechanism turns guaranteeing into an "investment" choice, so guarantors become cautious and select trustworthy targets, forming a reputation transmission chain.

---

### Mechanism 4: Sharing ratio penalties (Trigger strategy)

**Principle**: Trigger strategy means that once betrayal is detected, the system applies penalties immediately. This makes the long-term cost of betrayal higher than its short-term gains.

**Implementation**: Use a 30-day rolling window to calculate the sharing ratio, preventing early behavior from permanently trapping users.

| Sharing ratio | Penalty |
|----------------|----------|
| >= 20% | Normal |
| 10% ~ 20% | Consumption price +50% |
| < 10% | Price +100% + linear rejection probability (lower ratio => higher rejection chance) |
| 5 rejections due to low sharing (accumulated) | Account frozen for 3 days |

- Rejection probability formula: `P(rejection) = (10% - sharing_ratio) * 10`. It is linear smoothing with no critical threshold that enables threshold exploitation.
- New user 7-day protection: exempt from rejection and freezing, but price penalties still apply (prevents full immunity from being abused).
- Rolling window: users can improve their situation at any time by sharing bandwidth, avoiding being trapped in a bad equilibrium.

**Effect**: The marginal cost of free-riding rises sharply as the sharing ratio decreases, making sustained free-riding economically unattractive.

---

### Mechanism 5: Coalition game (Mutual-aid groups)

**Principle**: Coalition games lower coordination costs through small-group cooperation, while Shapley values ensure fair allocation and prevent free-riding inside the coalition.

**Implementation**:

- After joining a mutual-aid group, consumption prioritizes matching group members and applies an extra 8% discount.
- Coalition benefit = the total 8% discount saved from within-group mutual consumption (the "group jackpot").
- Shapley distribution: `phi_i = total_saved * (member_i_contribution / total_coalition_contribution)`.
- More contribution yields more jackpot, incentivizing active sharing within the group.

**Effect**: Mutual-aid groups convert games among strangers into games among familiar people (dorm building / classmates). Both social pressure and economic incentives drive cooperation.

---

### Mechanism 6: Dynamic pricing (Supply-demand signal)

**Principle**: Price signals guide resource allocation. When bandwidth is tight, prices increase to encourage sharing; when bandwidth is abundant, prices decrease to encourage consumption.

**Implementation**:

- Bandwidth pool < 80% benchmark (500MB): base price +10%
- Bandwidth pool > 120% benchmark: base price -10%
- Credit discounts stack with pricing, so high-credit users have advantages under any market condition.

---

### Mechanism 7: Wash-trading detection (anti-collusion)

**Principle**: If two users consume each other's shared bandwidth, the sharer can receive extra reputation/credit and also get flow currency. When wash-trading is detected, the sharer's extra reputation/credit gain is withheld to reduce incentive for washing.

**Implementation**:

- Detect whether bidirectional transactions exceed 10MB within 1 hour.
- If wash trading is detected: cancel the sharer's additional reputation/credit gain for this consumption cycle (flow currency transfer still happens).
- This makes the expected gain from wash trading lower than the gain from real sharing, preserving system integrity.

---

### Mechanism 8: Tournament/leaderboard incentives

**Principle**: Tournament mechanisms expand a one-shot game into multi-period competition. Users cooperate continuously to obtain future rewards.

**Implementation**:

- Leaderboard sorted by credit and publicly displayed.
- Top 10% users are marked 🏅 and receive an extra 5% consumption discount.
- Badges: Sharing Star (share > 500MB) and Mutual-Aid Expert (Eagle level).

---

### Overall incentive logic

```text
Share bandwidth
  -> credit increases (delta multiplier bonus)
  -> level up -> larger consumption discounts
  -> others consume -> flow currency credited in real time
  -> sharing ratio increases -> consumption price decreases and rejection risk disappears
  -> leaderboard ranking -> extra 5% discount
  -> coalition jackpot -> sharing is even more cost-effective within the group

Not sharing
  -> sharing ratio decreases -> consumption price increases (up to +100%)
  -> rejection probability increases (up to 100%)
  -> credit decreases -> discounts disappear
  -> after 5 low-share rejections -> freeze for 3 days
```

**Key insight**: By stacking multiple mechanisms, "continuous sharing" becomes better than "only use without sharing" in three dimensions: short-term (flow currency revenue), mid-term (credit-based discounts), and long-term (leaderboard rewards). Ultimately, the system achieves Pareto improvement: each rational user's optimal strategy matches the system-wide optimal strategy.

---

## Simulation Process and Results

To better demonstrate mechanism effectiveness, this project includes a project-like simulation script:

- Script: `simulate_game_theory_incentives.py`
- Output figure: `project_like_simulation.png`
- Comparison setup:
  - Scenario A: without incentives (baseline freeriding tendency)
  - Scenario B: with incentives (credit + token transfer + penalties + rejection + freezing)

### How the simulation works

Each round simulates repeated interactions among users:

1. Update user states (30-day behavior window decay, freeze countdown, online/offline randomness).
2. Each user chooses `share` or `free-ride` based on expected payoff.
3. Sharing adds bandwidth to the pool and yields reputation-related gains.
4. Consumption applies pricing/discount/penalty/rejection rules and transfers token payments.
5. Record system-level metrics and proceed to the next round.

The model is designed to be close to the actual project rules while keeping moderate abstraction for clearer comparative analysis.

### What is plotted

The generated figure contains two subplots:

1. **Cooperation ratio over rounds**
   - Raw trajectory (thin line) + moving-average trend (bold line)
   - Dashed horizontal lines show late-stage means
2. **System stability**
   - Rolling standard deviation of cooperation ratio (lower means more stable)
   - Also shown as raw + smoothed trends with late-stage means

### Reproduce

```bash
python simulate_game_theory_incentives.py
```

After running, check `project_like_simulation.png`.
![Project-like simulation result](project_like_simulation.png)

### Example outcome (current parameter set)

- Late-stage cooperation:
  - No incentive: ~0.039
  - With incentive: ~0.501
- Interpretation:
  - The incentive mechanism raises long-run cooperation substantially.
  - The system moves from a low-cooperation equilibrium toward a high-cooperation equilibrium while maintaining acceptable stability.
