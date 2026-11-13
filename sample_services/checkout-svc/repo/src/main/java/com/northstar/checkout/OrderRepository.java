package com.northstar.checkout;

public interface OrderRepository extends JpaRepository<Order, Long> {
    Optional<Order> findByIdempotencyKey(String key);   // added in v2.18.0 (1b9e0a2)
}
