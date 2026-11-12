# Payment provider for Tenmina's fees (EN-04)

Tenmina's own fees (land checks, later errands and listings) are collected through a licensed payment provider by card and mobile money (FR-PAY-001, IF-02). Purchase money never goes through this provider: it goes to the escrow bank (RUL-01, RUL-34).

Compared 12 November 2026 from secondary sources, not the providers' own price lists. Every figure is a working assumption `[TO VERIFY]` with the provider before signing.

## What matters for Tenmina

1. **International cards.** Most clients pay from the UK, US, Canada and Europe with cards issued there.
2. **Mobile money.** Local clients and family members pay by MTN MoMo, Telecel Cash or AirtelTigo Money.
3. **A payment link** usable without software in R0, then an API for the portal in R1.
4. **Refunds to the original method** (RUL-29, FR-PAY-008).
5. **Coverage in Nigeria and Kenya** for the next countries.

## Comparison

| | Paystack | Flutterwave | Hubtel |
|---|---|---|---|
| Mobile money (Ghana) | 1.95% | 2% (official table) | About 1.95% (sources vary, 1.2% to 2%) |
| Ghana-issued cards | 1.95% | 2.6% | About 2.9% |
| International cards | 1.95% in recent sources; an older guide says 3.9% + GHS 1 extra | 4.8% | 3.5% in one source; another says not offered |
| Settlement | Next working day, to a bank or mobile money account | Local next day; international about 5 days | Hourly to the Hubtel balance, reported |
| Nigeria and Kenya | Yes | Yes | Ghana only |
| Notes | Payment links and pages without code | Prices foreign-currency payments as international | Strong local brand; needs a registered business; a monthly fee was reported in 2025 |

All three need Tenmina to be a registered business before going live. Refunds to the original method: confirm with each `[TO VERIFY]`.

## Recommendation

**Paystack first, Flutterwave as the fallback.**

- Paystack has the lowest reported cost on the payment that matters most, an international card, plus mobile money, next-day settlement and payment links that work in R0 without software. It also operates in Nigeria and Kenya.
- Before signing, confirm in writing: the international card rate (the 1.95% versus 3.9% conflict), refunds to the original card or wallet, whether foreign cards are settled in cedis and at what rate, and the documents needed.
- Keep Flutterwave as the fallback if Paystack's international card rate is the higher figure, or if foreign cards are often declined.
- Hubtel suits a local, mobile-money-first business; its international card support is unclear.

## Next steps

1. Register the company (all three need it).
2. Open a Paystack account and confirm the points above.
3. Create a payment link for each test price (`docs/validation-plan.md` section 3) and add it to the landing page beside the order form.
4. Record the provider in `docs/specs/01` IF-02 and in the business plan.

## Sources

- [Paystack in Ghana: payouts and address rules (2026)](https://www.lilachbullock.com/paystack-in-ghana/)
- [Paystack vs Hubtel vs expressPay: MoMo payments for Ghana stores](https://www.maxmegroup.com/learn/paystack-vs-hubtel-vs-expresspay)
- [How to accept online payments in Ghana: MoMo, Paystack and Flutterwave](https://utopiagroup.io/resources/online-payments-ghana/)
- [Best payment gateways for businesses in Ghana in 2026 (NOWPayments)](https://nowpayments.io/blog/payment-gateway-ghana)
- [Flutterwave pricing for receiving payments](https://flutterwave.com/ng/support/pricing/pricing-for-receiving-payment)
- [Flutterwave in Ghana: accounts, fees, payouts](https://www.lilachbullock.com/flutterwave-in-ghana/)
- [Payment gateway Ghana: 5 best options compared (PhotonPay, 2026)](https://www.photonpay.com/hk/blog/article/payment-gateway-ghana)
- [Hubtel review Ghana: features, fees and real use cases (2026)](https://www.jbklutse.com/hubtel-review-ghana/)
- [Top e-commerce payment gateways in Ghana (Clarkyard, 2026)](https://www.clarkyard.com/blog/e-commerce-payment-gateways-ghana-2026)
