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
