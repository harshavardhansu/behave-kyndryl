package com.northstar.payment;

public class FraudCheckClient {
    private static final Duration SCORING_BUDGET = Duration.ofMillis(300);
    // When the budget is exceeded we still wait for the score (fail-closed), so latency adds up.
    public Score score(Authorization request) { return rules.evaluate(request, SCORING_BUDGET); }
}
