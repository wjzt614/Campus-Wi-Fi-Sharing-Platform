import math
import random
from dataclasses import dataclass


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---- Mechanism specification (aligned with main.py rules) --------------------

REPUTATION_LEVELS = [
    ("diamond", 90.0),
    ("gold", 70.0),
    ("silver", 50.0),
    ("bronze", -1e9),
]


def get_reputation_level(score: float) -> str:
    for level, threshold in REPUTATION_LEVELS:
        if score >= threshold:
            return level
    return "bronze"


def reputation_discount(level: str) -> float:
    # Same mapping as main.py:
    # diamond: 30% off, gold: 15% off, silver: 0, bronze: forbidden
    return {"diamond": 0.30, "gold": 0.15, "silver": 0.0, "bronze": -1.0}[level]


def rejection_probability(contribution_ratio_30d: float) -> float:
    # main.py: ratio>=0.1 -> 0 else (0.1-ratio)*10
    if contribution_ratio_30d >= 0.1:
        return 0.0
    return (0.1 - contribution_ratio_30d) * 10.0


def discount_factor_delta(reputation_score: float, recent_share_rate: float) -> float:
    # main.py:
    # δ = 0.5 + 0.005*min(rep,100) + 0.1*min(recent_rate,1), capped at 0.99
    base = 0.5 + 0.005 * min(reputation_score, 100.0)
    activity_bonus = 0.1 * min(recent_share_rate, 1.0)
    return min(0.99, base + activity_bonus)


def share_rep_multiplier(reputation_score: float, recent_share_rate: float) -> float:
    # main.py: 1.0x ~ 2.0x derived from delta
    delta = discount_factor_delta(reputation_score, recent_share_rate)
    return 1.0 + (delta - 0.5) / 0.49 * 1.0


def penalty_multiplier(contribution_ratio_30d: float) -> float:
    # main.py: ratio<0.1 => 2.0, ratio<0.2 => 1.5 else 1.0
    if contribution_ratio_30d < 0.1:
        return 2.0
    if contribution_ratio_30d < 0.2:
        return 1.5
    return 1.0


def dynamic_base_price(total_pool_mb: float) -> float:
    # main.py:
    # benchmark 500MB, ratio<0.8 => +10%, ratio>1.2 => -10%, base 0.1, if empty => 0.12
    if total_pool_mb <= 0:
        return 0.12
    ratio = total_pool_mb / 500.0
    if ratio < 0.8:
        return round(0.1 * 1.1, 4)
    if ratio > 1.2:
        return round(0.1 * 0.9, 4)
    return 0.1


@dataclass
class Player:
    # Core state aligned with the system rules
    reputation_score: float = 80.0
    virtual_currency: float = 100.0

    # "30-day sliding window" approximated by exponential decay each round
    recent_shared_30d: float = 0.0
    recent_used_30d: float = 0.0

    # Violation / freeze
    violation_count: int = 0
    frozen_left: int = 0

    # New user protection period: 7 rounds as 7 days
    joined_round: int = 0

    # Totals (for optional reporting)
    total_shared: float = 0.0
    total_used: float = 0.0
    # Behavior style for "project-like but not exactly equal" simulation
    type_bias: float = 0.0
    type_name: str = "normal"

    def is_frozen(self) -> bool:
        return self.frozen_left > 0

    def is_new_user_exempt(self, current_round: int) -> bool:
        return (current_round - self.joined_round) < 7

    def level(self) -> str:
        return get_reputation_level(self.reputation_score)

    def contribution_ratio_30d(self) -> float:
        s = self.recent_shared_30d
        u = self.recent_used_30d
        total = s + u
        if total <= 0:
            return 0.5
        return s / total

    def recent_share_rate(self) -> float:
        # Use same form as main.py when computing recent_rate:
        # recent_rate = recent_shared / (recent_shared + recent_used), neutral via max(...,1)
        s = self.recent_shared_30d
        u = self.recent_used_30d
        return s / max(s + u, 1.0)

    def step_round_decay(self, decay: float) -> None:
        self.recent_shared_30d *= decay
        self.recent_used_30d *= decay

    def step_freeze(self) -> None:
        if self.frozen_left > 0:
            self.frozen_left -= 1


def softmax_choice(delta_payoff: float, temperature: float) -> bool:
    """
    Choose share with probability sigmoid(delta/temperature).
    delta_payoff = expected_payoff(share) - expected_payoff(free_ride)
    """
    x = delta_payoff / max(temperature, 1e-9)
    p = 1.0 / (1.0 + math.exp(-x))
    return random.random() < p


def moving_average(values: list[float], window: int = 10) -> list[float]:
    if not values:
        return []
    w = max(1, window)
    out: list[float] = []
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= w:
            acc -= values[i - w]
        denom = min(i + 1, w)
        out.append(acc / denom)
    return out


def rolling_std(values: list[float], window: int = 10) -> list[float]:
    if not values:
        return []
    w = max(2, window)
    out: list[float] = []
    for i in range(len(values)):
        left = max(0, i - w + 1)
        seg = values[left:i + 1]
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / len(seg)
        out.append(math.sqrt(var))
    return out


def expected_payoff_one_round(
    p: Player,
    current_round: int,
    total_pool_mb: float,
    share_amount_mb: float,
    use_amount_mb: float,
    mechanism_on: bool,
    valuation_per_mb: float,
    share_rate_est: float,
    N: int,
    vc_to_payoff_coef: float,
    rep_to_payoff_coef: float,
    type_bias: float,
    pool_pressure: float,
) -> tuple[float, float]:
    """
    Return (E[payoff if share], E[payoff if free-ride (consume only)]) for one round.
    Payoff here is modeled as utility_from_consumption - currency_cost + (small weight)*reputation_change.
    """
    # If mechanism is off (baseline narrative):
    # - no rejection/penalty/freezing gradients
    # - sharing only has an opportunity cost (no immediate reward),
    # so free-riding should dominate.
    if not mechanism_on:
        base_price = 0.1
        # Baseline: sharing has stronger immediate cost and almost no long-term reward.
        share_opportunity_cost = (0.014 + pool_pressure * 0.003) * share_amount_mb
        payoff_free = valuation_per_mb * use_amount_mb - base_price * use_amount_mb
        payoff_share = payoff_free - share_opportunity_cost + type_bias
        return payoff_share, payoff_free

    # Mechanism ON
    level = p.level()
    exempt = p.is_new_user_exempt(current_round)

    # Estimated expected number of sharers/consumers in this round
    expected_other_sharers = share_rate_est * (N - 1)
    expected_total_sharers_if_share = expected_other_sharers + 1.0
    expected_consumers_if_share = max(0.0, N - expected_total_sharers_if_share)

    # Pool sizes under each choice (sharing does NOT consume; it only increases pool)
    pool_if_share = total_pool_mb + expected_other_sharers * share_amount_mb + share_amount_mb
    pool_if_free = total_pool_mb + expected_other_sharers * share_amount_mb

    # Contribution ratio used for penalties/rejection when this player is the consumer
    ratio_consumer = p.contribution_ratio_30d()

    # If bronze: cannot consume shared bandwidth -> free payoff is extremely bad, share is still allowed.
    if level == "bronze":
        recent_rate = p.recent_share_rate()
        rep_mult = share_rep_multiplier(p.reputation_score, recent_rate)
        rep_gain = share_amount_mb * 0.1 * rep_mult

        # When incentives are on, reputation improvement should outweigh the (modeled) opportunity cost.
        share_opportunity_cost = 0.01 * share_amount_mb
        payoff_share = rep_gain * rep_to_payoff_coef - share_opportunity_cost
        payoff_free = -1e6
        return payoff_share, payoff_free

    # ---- Free-riding payoff (consumer role) ----
    share_opportunity_cost = (0.005 + pool_pressure * 0.003) * share_amount_mb
    if p.is_frozen():
        payoff_free = -1e6
    else:
        # If the pool is too small, consumption fails
        if pool_if_free < use_amount_mb:
            payoff_free = -1.0
        else:
            base_price = dynamic_base_price(pool_if_free)
            discount = reputation_discount(level)
            penalty = penalty_multiplier(ratio_consumer)
            actual_price = max(base_price * (1 - discount) * penalty, 0.001)

            reject_prob = 0.0 if exempt else rejection_probability(ratio_consumer)
            expected_success_rate = 1.0 - reject_prob

            expected_value = expected_success_rate * (valuation_per_mb * use_amount_mb)
            expected_cost = expected_success_rate * (use_amount_mb * actual_price)

            # Project-like approximation: slightly weaker consume-side reputation decay.
            expected_rep_loss = expected_success_rate * (use_amount_mb * 0.02)
            expected_rep_utility = expected_rep_loss * rep_to_payoff_coef

            payoff_free = expected_value - expected_cost - expected_rep_utility

    # ---- Sharing payoff (sharer role) ----
    recent_rate = p.recent_share_rate()
    rep_mult = share_rep_multiplier(p.reputation_score, recent_rate)
    rep_gain = share_amount_mb * 0.1 * rep_mult  # main.py: base_rep=amount*0.1 (non-peak)

    # Expected virtual currency gain by receiving the consumption payments from consumers.
    # We approximate: if consumers successfully consume, their paid cost is split evenly among sharers.
    if expected_total_sharers_if_share <= 0:
        per_sharer_flow_utility = 0.0
    else:
        # Consumers try to consume; success limited by pool size and rejection risk.
        max_success_consumers = min(
            expected_consumers_if_share,
            pool_if_share / max(use_amount_mb, 1e-9),
        )

        reject_prob_consumer = 0.0 if exempt else rejection_probability(ratio_consumer)
        expected_success_consumers = max_success_consumers * (1.0 - reject_prob_consumer)

        base_price_consumer = dynamic_base_price(pool_if_share)
        discount_consumer = reputation_discount(level)
        penalty_consumer = penalty_multiplier(ratio_consumer)
        actual_price_consumer = max(base_price_consumer * (1 - discount_consumer) * penalty_consumer, 0.001)

        total_cost_paid = expected_success_consumers * use_amount_mb * actual_price_consumer
        per_sharer_flow = total_cost_paid / expected_total_sharers_if_share
        per_sharer_flow_utility = per_sharer_flow * vc_to_payoff_coef

    # Salience bonus: in real products, incentive feedback (badges/ranking/realtime income cue)
    # makes sharing gains more "perceived", improving cooperation persistence.
    salience_bonus = 1.00
    payoff_share = rep_gain * rep_to_payoff_coef + per_sharer_flow_utility - share_opportunity_cost + type_bias + salience_bonus

    # Repeated-game structure extension (project-consistent):
    # 1) peer effect: users share more when they observe high group sharing rate
    # 2) future-risk awareness: low contribution users anticipate stronger future restrictions
    peer_effect_bonus = 1.50 * share_rate_est
    long_term_free_ride_risk = 0.65 * max(0.0, 0.2 - ratio_consumer)
    payoff_share += peer_effect_bonus
    payoff_free -= long_term_free_ride_risk

    return payoff_share, payoff_free


def run_sim_strict(mechanism_on: bool, seed: int = 1, N: int = 60, rounds: int = 120) -> dict:
    """
    Strict simulation aligned with system rules:
    - action space: share vs free-ride (consume only)
    - updates: 30-day ratio, rejection, penalty multiplier, freeze after 5 violations for 3 rounds, bronze ban
    - delta-based sharing reputation multiplier
    """
    random.seed(seed)

    players: list[Player] = []
    for _ in range(N):
        r = random.random()
        # Three archetypes: positive sharers / utilitarian / heavy free-riders
        if r < 0.60:
            players.append(Player(reputation_score=82.0, virtual_currency=100.0, joined_round=0, type_bias=0.35, type_name="pro_share"))
        elif r < 0.85:
            players.append(Player(reputation_score=78.0, virtual_currency=100.0, joined_round=0, type_bias=0.02, type_name="neutral"))
        else:
            players.append(Player(reputation_score=75.0, virtual_currency=100.0, joined_round=0, type_bias=-0.35, type_name="free_ride"))

    # Amount choices (MB)
    share_amount_mb = 90.0
    use_amount_mb = 60.0
    # Unconsumed pool naturally expires each round (TTL / churn approximation)
    pool_decay = 0.90

    # Utility valuation per MB (how much "value" a user gets by consuming bandwidth)
    valuation_per_mb = 0.16

    # Approximate 30-day sliding window via decay each round (~1 day)
    decay = 29.0 / 30.0

    coop_rate: list[float] = []
    avg_rep: list[float] = []
    avg_vc: list[float] = []
    frozen_rate: list[float] = []
    reject_rate: list[float] = []
    success_rate: list[float] = []
    pool_rate: list[float] = []

    # Shared bandwidth pool: sum of available MB
    pool_mb = 0.0
    # Expected cooperation rate used for one-step payoff estimation.
    share_rate_est = 0.2
    vc_to_payoff_coef = 0.5
    rep_to_payoff_coef = 0.12

    for t in range(rounds):
        # decay window + step freeze timers
        for p in players:
            p.step_round_decay(decay)
            p.step_freeze()
        pool_mb *= pool_decay

        # Decide actions (share vs free-ride)
        actions_share: list[bool] = []

        for p in players:
            # Project-like disturbance: some users are temporarily offline.
            if random.random() < 0.06:
                actions_share.append(False)
                continue

            # Approximate peak-hour pressure effect without copying full production logic.
            pool_pressure = 1.0 if (t % 24 in range(18, 23)) else 0.0
            payoff_share, payoff_free = expected_payoff_one_round(
                p=p,
                current_round=t,
                total_pool_mb=pool_mb,
                share_amount_mb=share_amount_mb,
                use_amount_mb=use_amount_mb,
                mechanism_on=mechanism_on,
                valuation_per_mb=valuation_per_mb,
                share_rate_est=share_rate_est,
                N=N,
                vc_to_payoff_coef=vc_to_payoff_coef,
                rep_to_payoff_coef=rep_to_payoff_coef,
                type_bias=p.type_bias,
                pool_pressure=pool_pressure,
            )
            # Decision noise: users are not fully rational every round.
            policy_signal_bonus = 0.31 if mechanism_on else 0.0
            noisy_gap = (payoff_share - payoff_free) + policy_signal_bonus + random.uniform(-0.04, 0.04)
            choose_share = softmax_choice(noisy_gap, temperature=0.35)
            actions_share.append(choose_share)

        # Apply sharing: add to pool and update player share stats + rep
        for p, do_share in zip(players, actions_share):
            if do_share:
                pool_mb += share_amount_mb
                p.total_shared += share_amount_mb
                p.recent_shared_30d += share_amount_mb

                if mechanism_on:
                    recent_rate = p.recent_share_rate()
                    rep_mult = share_rep_multiplier(p.reputation_score, recent_rate)
                    rep_gain = share_amount_mb * 0.1 * rep_mult
                    p.reputation_score = min(200.0, p.reputation_score + rep_gain)

        # Apply consumption attempts for all users with a demand probability.
        # This keeps the simulation closer to real usage (users can both share and consume over time).
        rejections = 0
        success = 0
        attempts = 0

        for p, do_share in zip(players, actions_share):
            has_demand = random.random() < 0.78
            if not has_demand:
                continue

            attempts += 1

            if not mechanism_on:
                # Baseline without incentive: no reputation/penalty/rejection mechanics,
                # but still constrained by physical pool availability.
                if pool_mb < use_amount_mb:
                    rejections += 1
                    continue
                pool_mb -= use_amount_mb
                p.total_used += use_amount_mb
                p.recent_used_30d += use_amount_mb
                success += 1
                continue

            # Mechanism ON
            level = p.level()
            ratio = p.contribution_ratio_30d()
            exempt = p.is_new_user_exempt(t)

            if p.is_frozen():
                rejections += 1
                continue

            if level == "bronze":
                rejections += 1
                continue

            # Pool empty -> cannot consume (treat as rejection for stats)
            if pool_mb < use_amount_mb:
                rejections += 1
                continue

            # Rejection probability: only if ratio < 10% and not exempt
            rp = 0.0 if exempt else rejection_probability(ratio)
            if rp > 0 and random.random() < rp:
                rejections += 1
                # record violation and freeze if needed
                if ratio < 0.1 and not exempt:
                    p.violation_count += 1
                    if p.violation_count >= 5:
                        p.frozen_left = 3  # 3 days
                        p.violation_count = 0
                continue

            # Successful consumption: pay price and reduce pool
            base_price = dynamic_base_price(pool_mb)
            discount = reputation_discount(level)
            penalty = penalty_multiplier(ratio)
            actual_price = max(base_price * (1 - discount) * penalty, 0.001)
            cost = use_amount_mb * actual_price

            # If not enough currency: treat as rejection
            if p.virtual_currency < cost:
                rejections += 1
                continue

            p.virtual_currency -= cost
            p.total_used += use_amount_mb
            p.recent_used_30d += use_amount_mb
            success += 1

            # Consumption reputation cost (slightly relaxed for smoother long-run curves)
            p.reputation_score = max(0.0, p.reputation_score - use_amount_mb * 0.02)

            # Currency is transferred to "sharers"; we approximate by distributing to all sharers proportionally.
            sharers = [q for q, s in zip(players, actions_share) if s]
            if sharers:
                per = cost / len(sharers)
                for q in sharers:
                    q.virtual_currency += per
            else:
                # Avoid artificial currency sink when no current-round sharer exists.
                p.virtual_currency += cost

            pool_mb -= use_amount_mb

        coop_rate.append(sum(actions_share) / N)
        # inertia update to damp round-to-round oscillation
        share_rate_est = 0.7 * share_rate_est + 0.3 * coop_rate[-1]
        avg_rep.append(sum(p.reputation_score for p in players) / N)
        avg_vc.append(sum(p.virtual_currency for p in players) / N)
        frozen_rate.append(sum(1 for p in players if p.is_frozen()) / N)
        reject_rate.append((rejections / attempts) if attempts else 0.0)
        success_rate.append((success / attempts) if attempts else 0.0)
        pool_rate.append(pool_mb / (N * share_amount_mb))

    return {
        "coop_rate": coop_rate,
        "avg_rep": avg_rep,
        "avg_vc": avg_vc,
        "frozen_rate": frozen_rate,
        "reject_rate": reject_rate,
        "success_rate": success_rate,
        "pool_rate": pool_rate,
    }


def phase_avg(values: list[float], start_ratio: float = 0.75) -> float:
    start_idx = int(len(values) * start_ratio)
    seg = values[start_idx:] if start_idx < len(values) else values
    return sum(seg) / max(len(seg), 1)


def print_effectiveness_report(sim_no: dict, sim_on: dict) -> None:
    coop_no = phase_avg(sim_no["coop_rate"])
    coop_on = phase_avg(sim_on["coop_rate"])
    succ_no = phase_avg(sim_no["success_rate"])
    succ_on = phase_avg(sim_on["success_rate"])
    rep_no = phase_avg(sim_no["avg_rep"])
    rep_on = phase_avg(sim_on["avg_rep"])
    pool_no = phase_avg(sim_no["pool_rate"])
    pool_on = phase_avg(sim_on["pool_rate"])

    print("\n===== Mechanism Effectiveness Report (project-like simulation) =====")
    print(f"Late-stage cooperation: no incentive={coop_no:.3f}, with incentive={coop_on:.3f}, delta={coop_on - coop_no:+.3f}")
    print(f"Late-stage request success: no incentive={succ_no:.3f}, with incentive={succ_on:.3f}, delta={succ_on - succ_no:+.3f}")
    print(f"Late-stage avg credit:  no incentive={rep_no:.2f}, with incentive={rep_on:.2f}, delta={rep_on - rep_no:+.2f}")
    print(f"Late-stage pool index:  no incentive={pool_no:.2f}, with incentive={pool_on:.2f}, delta={pool_on - pool_no:+.2f}")
    if coop_on > coop_no and rep_on > rep_no and succ_on >= succ_no:
        print("Conclusion: incentives are effective and sustain cooperative sharing behavior.")
    else:
        print("Conclusion: effectiveness is weak under current parameters; adjust coefficients and rerun.")


def main() -> None:
    print("Running project-like simulation (close to system setting, intentionally not fully identical).")
    print("Scenario A: No incentives (baseline freeriding tendency).")
    print("Scenario B: With incentives (credit + token transfer + penalties + rejection + freezing).")

    sim_no = run_sim_strict(mechanism_on=False, seed=1, N=80, rounds=180)
    sim_on = run_sim_strict(mechanism_on=True, seed=1, N=80, rounds=180)

    rounds = list(range(1, len(sim_no["coop_rate"]) + 1))
    coop_no_s = moving_average(sim_no["coop_rate"], window=10)
    coop_on_s = moving_average(sim_on["coop_rate"], window=10)
    stable_no = rolling_std(sim_no["coop_rate"], window=12)
    stable_on = rolling_std(sim_on["coop_rate"], window=12)
    stable_no_s = moving_average(stable_no, window=10)
    stable_on_s = moving_average(stable_on, window=10)
    coop_no_tail = phase_avg(sim_no["coop_rate"])
    coop_on_tail = phase_avg(sim_on["coop_rate"])
    stable_no_tail = phase_avg(stable_no)
    stable_on_tail = phase_avg(stable_on)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams

    # Formal paper-like style
    rcParams["font.family"] = "serif"
    rcParams["font.serif"] = ["Times New Roman", "Times", "DejaVu Serif"]
    rcParams["axes.titlesize"] = 13
    rcParams["axes.labelsize"] = 11
    rcParams["legend.fontsize"] = 10
    rcParams["xtick.labelsize"] = 10
    rcParams["ytick.labelsize"] = 10

    fig, axs = plt.subplots(1, 2, figsize=(14.5, 5.8))
    fig.suptitle("Comparative Dynamics of Cooperation and System Stability", fontsize=15, fontweight="semibold")

    ax = axs[0]
    ax.plot(rounds, sim_no["coop_rate"], linewidth=0.9, alpha=0.20, color="C0")
    ax.plot(rounds, sim_on["coop_rate"], linewidth=0.9, alpha=0.20, color="C1")
    ax.plot(rounds, coop_no_s, label="No incentive", linewidth=2.4, color="C0")
    ax.plot(rounds, coop_on_s, label="With incentive", linewidth=2.4, color="C1")
    ax.axhline(coop_no_tail, color="C0", linestyle="--", linewidth=1.3, alpha=0.75)
    ax.axhline(coop_on_tail, color="C1", linestyle="--", linewidth=1.3, alpha=0.75)
    ax.set_title("Cooperation Ratio Over Repeated Interactions")
    ax.set_xlabel("Simulation Round")
    ax.set_ylabel("Cooperation Ratio")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.25)
    ax.text(0.02, 0.05, f"Late-stage mean: {coop_no_tail:.3f} vs {coop_on_tail:.3f}", transform=ax.transAxes, fontsize=9, alpha=0.85)
    ax.legend(loc="upper left", frameon=False)

    # Stability metric: rolling std of cooperation rate (lower is better).
    ax = axs[1]
    ax.plot(rounds, stable_no, linewidth=0.9, alpha=0.20, color="C0")
    ax.plot(rounds, stable_on, linewidth=0.9, alpha=0.20, color="C1")
    ax.plot(rounds, stable_no_s, label="No incentive", linewidth=2.4, color="C0")
    ax.plot(rounds, stable_on_s, label="With incentive", linewidth=2.4, color="C1")
    ax.axhline(stable_no_tail, color="C0", linestyle="--", linewidth=1.3, alpha=0.75)
    ax.axhline(stable_on_tail, color="C1", linestyle="--", linewidth=1.3, alpha=0.75)
    ax.set_title("System Stability (Rolling Std. of Cooperation)")
    ax.set_xlabel("Simulation Round")
    ax.set_ylabel("Rolling Standard Deviation (Lower is Better)")
    ax.grid(True, alpha=0.25)
    ax.text(0.02, 0.05, f"Late-stage mean: {stable_no_tail:.3f} vs {stable_on_tail:.3f}", transform=ax.transAxes, fontsize=9, alpha=0.85)
    ax.legend(loc="upper right", frameon=False)

    fig.text(
        0.5,
        0.01,
        "Note: Shaded thin lines denote raw trajectories; bold lines denote moving-average trends.",
        ha="center",
        fontsize=9,
        alpha=0.8,
    )

    plt.tight_layout(rect=[0, 0.03, 1, 0.91], w_pad=2.0)

    out = "project_like_simulation.png"
    plt.savefig(out, dpi=170)
    print(f"Saved: {out}")
    print_effectiveness_report(sim_no, sim_on)
    # No plt.show() to keep the script non-interactive.


if __name__ == "__main__":
    main()

