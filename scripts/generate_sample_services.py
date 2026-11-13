"""Generate small, realistic source repositories and log files for the demo services.

The agents' read-only tools read these (``backend/investigation_tools.py``), so incidents other than
the Payment API sandbox also have code, configuration and logs to investigate.

    python scripts/generate_sample_services.py      # writes sample_services/<service>/{repo,logs}

Output is deterministic (fixed random seed), so re-running gives the same files. Everything is
synthetic demonstration data: no real systems, people or secrets.
"""

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample_services"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8")


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------- checkout-svc (INC-1042)

def checkout(rng: random.Random) -> None:
    base = ROOT / "checkout-svc"
    write(base / "repo/README.md", """
# checkout-svc

Places customer orders: validates the cart, authorizes payment through payment-svc and writes the order
to PostgreSQL (postgres-primary). Runs 6 replicas in production behind the API gateway.

Database connection budget: postgres-primary allows **200** connections in total, shared by
checkout-svc (6 replicas), order-history-svc (40) and admin tools (10).
""")
    write(base / "repo/CHANGELOG.md", """
# Changelog

## v2.18.0 (2026-10-30)
- c7f4e21 Reduce HikariCP maximum-pool-size from 30 to 10 per replica ("DB connection budget review").
- 1b9e0a2 Add order-level idempotency key check (one extra SELECT per checkout).

## v2.17.3 (2026-10-21)
- 8e21c44 Upgrade payment client to 4.2.1.
""")
    write(base / "repo/src/main/resources/application.yml", """
server:
  port: 8080
spring:
  datasource:
    url: jdbc:postgresql://postgres-primary:5432/orders
    username: checkout
    password: ${DB_PASSWORD}          # injected from the secret store
    hikari:
      pool-name: HikariPool-1
      maximum-pool-size: 10           # v2.18.0 (c7f4e21): was 30
      minimum-idle: 5
      connection-timeout: 2000        # ms to wait for a free connection before failing
      max-lifetime: 1800000
payment:
  client:
    timeout-ms: 800
""")
    write(base / "repo/deploy/values-production.yaml", """
replicaCount: 6
resources:
  requests: { cpu: "1", memory: 1Gi }
  limits:   { cpu: "2", memory: 2Gi }
env:
  SPRING_PROFILES_ACTIVE: production
# Connection math: replicas x maximum-pool-size must stay within the checkout share of the
# postgres-primary budget (150 of 200). v2.17: 6 x 30 = 180 (over budget at peak);
# v2.18: 6 x 10 = 60 (within budget). 6 x 20 = 120 and 6 x 25 = 150 are also within budget.
""")
    write(base / "repo/src/main/java/com/northstar/checkout/CheckoutService.java", """
package com.northstar.checkout;

@Service
public class CheckoutService {
    private final OrderRepository orders;
    private final PaymentClient payments;

    @Transactional  // holds one pooled DB connection for the whole method, including the payment call
    public Order placeOrder(Cart cart, String idempotencyKey) {
        orders.findByIdempotencyKey(idempotencyKey).ifPresent(existing -> { throw new DuplicateOrder(existing); });
        Authorization auth = payments.authorize(cart.total(), cart.paymentToken());  // ~186 ms p95
        return orders.save(Order.from(cart, auth));
    }
}
""")
    write(base / "repo/src/main/java/com/northstar/checkout/OrderRepository.java", """
package com.northstar.checkout;

public interface OrderRepository extends JpaRepository<Order, Long> {
    Optional<Order> findByIdempotencyKey(String key);   // added in v2.18.0 (1b9e0a2)
}
""")

    start = datetime(2026, 10, 30, 9, 20, tzinfo=timezone.utc)
    lines: list[str] = []
    now = start
    deploy = datetime(2026, 10, 30, 9, 34, tzinfo=timezone.utc)
    first_error = datetime(2026, 10, 30, 9, 42, 18, tzinfo=timezone.utc)
    pending = 0
    while now < datetime(2026, 10, 30, 10, 5, tzinfo=timezone.utc):
        now += timedelta(milliseconds=rng.randint(900, 4200))
        pod = f"checkout-svc-7d9f{rng.randint(1, 6)}"
        if deploy <= now < deploy + timedelta(seconds=5) and not any("Starting" in line for line in lines):
            lines.append(f"{stamp(now)} INFO  [main] {pod} c.n.checkout.Application - Started checkout-svc v2.18.0 (commit c7f4e21)")
            lines.append(f"{stamp(now)} INFO  [main] {pod} com.zaxxer.hikari.HikariDataSource - HikariPool-1 - Starting... maximumPoolSize=10 connectionTimeout=2000ms")
            continue
        if now < first_error:
            latency = rng.randint(140, 420)
            lines.append(f"{stamp(now)} INFO  [http-nio-8080-exec-{rng.randint(1, 40)}] {pod} c.n.checkout.CheckoutController - POST /checkout 201 {latency}ms order=ORD-{rng.randint(100000, 999999)}")
            if rng.random() < 0.04:
                lines.append(f"{stamp(now)} WARN  [http-nio-8080-exec-{rng.randint(1, 40)}] {pod} c.n.checkout.PaymentClient - payment.authorize slow: 612ms (provider p95 186ms) - retried 0 times")
            continue
        pending = min(140, pending + rng.randint(2, 9))
        if rng.random() < 0.55:
            lines.append(f"{stamp(now)} ERROR [http-nio-8080-exec-{rng.randint(1, 40)}] {pod} c.n.checkout.CheckoutController - POST /checkout 503 2014ms "
                         f"java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 2000ms.")
            if rng.random() < 0.3:
                lines.append(f"{stamp(now)} DEBUG [HikariPool-1 housekeeper] {pod} com.zaxxer.hikari.pool.HikariPool - HikariPool-1 - Pool stats (total=10, active=10, idle=0, waiting={pending})")
        else:
            lines.append(f"{stamp(now)} INFO  [http-nio-8080-exec-{rng.randint(1, 40)}] {pod} c.n.checkout.CheckoutController - POST /checkout 201 {rng.randint(900, 1980)}ms order=ORD-{rng.randint(100000, 999999)}")
    write(base / "logs/checkout-svc.log", "\n".join(lines))
    write(base / "logs/postgres-primary.log", "\n".join([
        "2026-10-30T09:30:00.000Z LOG:  connections: active=118 idle=40 max_connections=200 (checkout=60 order-history=40 admin=4)",
        "2026-10-30T09:45:00.000Z LOG:  connections: active=104 idle=12 max_connections=200 (checkout=60 order-history=40 admin=4)",
        "2026-10-30T09:45:00.000Z LOG:  checkpoint complete: wrote 1840 buffers (2.1%); 0 WAL file(s) added",
        "2026-10-30T10:00:00.000Z LOG:  connections: active=104 idle=10 max_connections=200 (checkout=60 order-history=40 admin=4)",
        "2026-10-30T10:00:00.000Z LOG:  database load: cpu=31% io_wait=2% slow_queries(>500ms)=0  (the database itself is not saturated)",
    ]))


# ---------------------------------------------------------------- payment-svc (INC-1041)

def payment(rng: random.Random) -> None:
    base = ROOT / "payment-svc"
    write(base / "repo/README.md", """
# payment-svc

Authorizes card payments. Each authorization calls fraud-check (scoring budget 300 ms) and then the
external payment provider. Fraud rulesets roll out region by region (eu-west-1 first).
""")
    write(base / "repo/rules/fraud-ruleset-v41.yaml", """
ruleset: v41
rollout: { stage: 1, regions: [eu-west-1] }
steps:
  - name: velocity_check
    mode: cached
  - name: device_fingerprint_lookup      # NEW in v41
    mode: synchronous                   # blocks scoring until the fingerprint service answers (p95 190 ms)
    cache_key: "${card_hash}:${device_fingerprint}"   # v40 key was "${card_hash}" -> far fewer cache hits
  - name: amount_anomaly
    mode: cached
budget_ms: 300
""")
    write(base / "repo/rules/fraud-ruleset-v40.yaml", """
ruleset: v40
steps:
  - { name: velocity_check, mode: cached }
  - { name: amount_anomaly, mode: cached }
cache_key: "${card_hash}"
budget_ms: 300
""")
    write(base / "repo/src/main/java/com/northstar/payment/FraudCheckClient.java", """
package com.northstar.payment;

public class FraudCheckClient {
    private static final Duration SCORING_BUDGET = Duration.ofMillis(300);
    // When the budget is exceeded we still wait for the score (fail-closed), so latency adds up.
    public Score score(Authorization request) { return rules.evaluate(request, SCORING_BUDGET); }
}
""")
    start = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
    enabled = start + timedelta(minutes=20)
    lines, now = [], start
    while now < start + timedelta(minutes=95):
        now += timedelta(milliseconds=rng.randint(1500, 5000))
        region = rng.choice(["eu-west-1", "eu-west-1", "us-east-1", "ap-south-1"])
        slow = region == "eu-west-1" and now > enabled
        fraud = rng.randint(250, 360) if slow and rng.random() < 0.6 else rng.randint(40, 120)
        total = fraud + rng.randint(120, 190)
        level = "WARN " if fraud > 300 else "INFO "
        msg = f"fraud-check: scoring exceeded 300ms budget (took {fraud}ms) ruleset=v41 step=device_fingerprint_lookup cache_hit=false" if fraud > 300 else f"POST /payments/authorize 200 {total}ms fraud={fraud}ms cache_hit={'false' if slow and rng.random() < 0.63 else 'true'}"
        lines.append(f"{stamp(now)} {level} payment-svc region={region} ruleset={'v41' if region == 'eu-west-1' and now > enabled else 'v40'} {msg}")
        if now > enabled and len(lines) % 40 == 0:
            lines.append(f"{stamp(now)} INFO  payment-svc fraud-cache stats region=eu-west-1 hit_ratio={round(rng.uniform(0.33, 0.41), 2)} (v40 baseline 0.91)")
    write(base / "logs/payment-svc.log", "\n".join(lines))


# ---------------------------------------------------------------- inventory-svc (INC-1040)

def inventory(rng: random.Random) -> None:
    base = ROOT / "inventory-svc"
    write(base / "repo/README.md", """
# inventory-svc / inventory-reconciler

Consumes the inventory-updates Kafka topic (6 partitions, 6 consumers) and reconciles stock in batches.
""")
    write(base / "repo/config/reconciler.properties", """
# Kafka consumer
group.id=inventory-reconciler
session.timeout.ms=10000
heartbeat.interval.ms=3000
max.poll.interval.ms=300000
max.poll.records=500
# Reconciliation
reconciler.batch.size=5000      # commit 9ad21f0 (v3.4.0): was 500, raised to reduce commit overhead
""")
    write(base / "repo/deploy/jvm.options", """
-Xms1g
-Xmx2g
-XX:+UseParallelGC              # stop-the-world collector; long pauses with large heaps
""")
    start = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    lines, now, rebalance = [], start, 0
    while now < start + timedelta(minutes=40):
        now += timedelta(seconds=rng.randint(2, 9))
        pod = f"inventory-reconciler-{rng.randint(1, 6)}"
        if pod[-1] in "456" and rng.random() < 0.25:
            pause = round(rng.uniform(6.5, 11.4), 1)
            lines.append(f"{stamp(now)} WARN  {pod} gc: Pause Full (Ergonomics) {pause}s heap 1.88G->1.71G(2.00G) batch_size=5000")
            if pause > 10:
                rebalance += 1
                lines.append(f"{stamp(now)} WARN  {pod} kafka: left group inventory-reconciler: session timeout 10000ms exceeded; rebalance #{rebalance}")
        else:
            lines.append(f"{stamp(now)} INFO  {pod} reconciler: committed batch size=5000 lag={rng.randint(900, 2310)} duration={rng.randint(3, 9)}s")
    write(base / "logs/inventory-reconciler.log", "\n".join(lines))


if __name__ == "__main__":
    rng = random.Random(42)
    for build in (checkout, payment, inventory):
        build(rng)
    files = sorted(p.relative_to(ROOT) for p in ROOT.rglob("*") if p.is_file())
    print(f"Wrote {len(files)} files under {ROOT}:")
    for file in files:
        print("  ", file)
