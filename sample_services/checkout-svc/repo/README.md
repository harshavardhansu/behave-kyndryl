# checkout-svc

Places customer orders: validates the cart, authorizes payment through payment-svc and writes the order
to PostgreSQL (postgres-primary). Runs 6 replicas in production behind the API gateway.

Database connection budget: postgres-primary allows **200** connections in total, shared by
checkout-svc (6 replicas), order-history-svc (40) and admin tools (10).
