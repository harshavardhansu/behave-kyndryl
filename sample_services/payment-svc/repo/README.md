# payment-svc

Authorizes card payments. Each authorization calls fraud-check (scoring budget 300 ms) and then the
external payment provider. Fraud rulesets roll out region by region (eu-west-1 first).
