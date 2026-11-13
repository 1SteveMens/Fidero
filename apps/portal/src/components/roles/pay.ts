/* Start paying a Tenmina fee through the payment provider. The development provider's hosted page is
   the portal's own checkout page (/checkout/[id]); a real provider's page is opened as given. */
export type PaymentStarted = { payment: { id: string }; checkout_url: string };

export function goToCheckout(p: PaymentStarted, back: string) {
  const fake = /^\/v1\/payments\/[^/]+\/fake-checkout$/.test(p.checkout_url);
  window.location.href = fake ? `/checkout/${p.payment.id}?return=${encodeURIComponent(back)}` : p.checkout_url;
}
