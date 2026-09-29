"""EXPLORATORY - SYNTHETIC - NOT VALIDATION (E10).

The frozen P2 rule (and P2 + P2c) when the 300 trades fall on few UTC days: 5, 8, 10, 15.
It sets eval.min_day_clusters. Same trade model as gate_power.py section D2.
Usage (from this folder): python3 few_clusters.py > ../../../../../research/data/few_clusters_seed31.txt
"""
import random
from multiprocessing import Pool
import gate_power as g

def cell(args):
    days, rho_d, p_long, mu, sims, b, seed = args
    rng = random.Random(seed)
    loc0, loc = g.calibrate(0.0, 1.2), g.calibrate(mu, 1.2)
    k = {"t96": 0, "boot96": 0, "crt96": 0, "frozen96": 0, "frozen96+P2c": 0}
    for _ in range(sims):
        rs, ds, ps, ss, f = g.gen_trades(rng, loc, 1.2, rho_d, p_long, 0.5, 0.5, days)
        s, c = g.cluster_sums(rs, ds)
        t = g.lb_t(rs, .96); bl = g.boot_lbs(s, c, rng, b, (.96,))[.96]; cr = g.crt_lb(rs, ds, .96)
        k["t96"] += t > 0; k["boot96"] += bl > 0; k["crt96"] += cr > 0
        fz = min(t, bl, cr) > 0
        k["frozen96"] += fz
        if fz:
            base = g.baseline_means(rng, loc0, 1.2, rho_d, ss, f)
            dd = [r - x for r, x in zip(rs, base)]
            k["frozen96+P2c"] += g.frozen_lb(dd, ds, rng, b, .96) > 0
    return f"days={days:>2} rho_d={rho_d} long={p_long:.0%} mu={mu:+.2f}: " + "  ".join(f"{n} {g.wilson(v, sims)}" for n, v in k.items())

if __name__ == "__main__":
    cells = []
    i = 0
    for mu in (0.0, 0.10):
        for rho, pl in ((0.0, 0.5), (0.3, 0.8)):
            for days in (5, 8, 10, 15):
                i += 1
                cells.append((days, rho, pl, mu, 2000, 1000, 31 * 100_003 + i))
    with Pool(4) as p:
        for line in p.map(cell, cells, chunksize=1):
            print(line)
