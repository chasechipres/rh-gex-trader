# Strategy: how it picks a trade, and why

The reasoning behind the rules in [CLAUDE.md](../CLAUDE.md), for a small account (roughly $1,000-$5,000) funded
with money you can lose and run for growth. The rules themselves live in CLAUDE.md; this page is the why.

- [The goal](#the-goal) · [Swing trades](#swing-trades) · [Risk per trade](#risk-per-trade)
- [How a setup becomes an order](#how-a-setup-becomes-an-order) · [What a small account changes](#what-a-small-account-changes)
- [Why most ideas are skipped](#why-most-ideas-are-skipped) · [His dip levels: buy the reclaim](#his-dip-levels-buy-the-reclaim)
- [Watching between cycles](#watching-between-cycles) · [What can still go wrong](#what-can-still-go-wrong)

## The goal

Grow a small account fast without letting one bad day end it. That means accepting a high loss rate per trade
in exchange for winners that run, while hard limits (the hook) cap how much any order, day or drawdown can
cost. The source supplies ideas; Claude decides; the hook has the last word.

## Swing trades

Trades last days to about two weeks: long enough for a gamma level to play out, short enough to skip most
overnight news. Entries happen during regular hours only; between cycles a watcher catches level crosses within
about a minute and the exit checks follow a heartbeat (see [Watching between cycles](#watching-between-cycles)),
and resting stops cover the hours nobody is watching. The exception is a [reclaim](#his-dip-levels-buy-the-reclaim):
it's a same-day trade, sold by 15:45 ET. Shares get a 10-trading-day time stop (5 for
leveraged funds); options are closed two days before expiry.

## Risk per trade

Every trade is sized so a full loss costs **5% of the account**, whatever the vehicle. At 5% a losing streak of
five costs about a quarter of the account, which is survivable; the 20% daily loss stop and 30% drawdown pause
stop the bleeding before that compounds. Growth comes from using the whole 5% on good setups and letting
winners run (half sold at +100% or the target, the rest trailed), not from betting more per trade.

## How a setup becomes an order

Once a setup passes the checks, the structure is chosen in this order:

| Order | Structure | Why it's here |
|---|---|---|
| 1 | **Option** (`fit`): a call or put, or a 1:1 debit spread | Built-in leverage with a loss capped at the premium; a spread cuts the cost on expensive names. |
| 2 | **2x leveraged fund** on the stock (`lev`); an **inverse** fund for bearish reads | Only when no option fits *and* plain shares would be capped below the 5% risk by the per-order limit: the fund fits the same risk in half the cash. Inverse funds are the only way to be bearish, since the account can't short. |
| 3 | **Plain shares** | When the stock is cheap enough that shares take the full 5% risk under the cap, or no liquid fund exists. |
| 4 | **Skip** | Nothing fits the budget, or the setup fails a check. |

Spreads are currently refused by Robinhood's agent API ([#23](https://github.com/chasechipres/rh-gex-trader/issues/23));
each spread is still attempted, so the first acceptance shows it's fixed.

## What a small account changes

- **Options often don't fit.** At 5% of $1,500 the budget is about $75, which buys a call on a $10-$30 stock
  but almost nothing near the money on a $200-$400 one. Narrow spreads were the answer for expensive names.
- **The per-order cap binds before the risk budget does.** Shares are sized by the stop distance, so a tight
  stop on an expensive stock asks for more cash than one order may use (75% of the account by default). A 2x
  fund reaches the same risk with half the cash; that's the case funds exist for here.
- **Fixed costs matter more.** A wide bid/ask spread or a slippy stop is a bigger share of a small trade's risk,
  which is why legs and funds must be liquid (preflight checks both).

As the account grows, more option structures fit and fewer share trades get capped, so the order above leans
further toward options on its own.

## Why most ideas are skipped

The source posts levels, not trades. An idea becomes an order only when his thesis, the price action and an
independent gamma read agree, the trend agrees (or a reversal is confirmed by price and volume), the post is
fresh, and there's a stop and a target at least 1.5 times as far away. Watches wait for price to reach his
level instead of chasing it. `calls stats` scores his calls by setup type, and a setup type that rarely works
gets less benefit of the doubt.

## His dip levels: buy the reclaim

His most frequent setup is a level to buy during a selloff: a long-gamma floor, a king, an "optimal entry". In a
downtrend that's catching a falling knife, and the trend rule used to skip nearly all of them. Some bounced the
same day as he said; others kept falling, and held for days most gave it back.

So these are traded only on a **confirmed reclaim**, the standard failed-breakdown entry ("spring", "undercut and
rally"): price trades at or below his level, never through his invalidation, and then a 15-minute bar closes back
above the level on above-average volume. The stop is his invalidation, not the swept low; the target is his next
level; reward:risk is at least 1.5 and sizing is the normal 5%. The position is **sold by 15:45 ET the same day**.

Why this version, from a replay of one week of his dip calls on 15-minute bars:

| Version | What happened |
|---|---|
| Buy at his level, same day | Most trades, but bought every call that kept falling |
| Reclaim, stop just under the swept low | Normal wicks stopped out most of them |
| **Reclaim, his stop, same day** | Fewest trades, skipped every call that broke his invalidation first, smallest losses |
| Same reclaim, held for days | Worse: overnight gaps went through the stops |

One week is thin evidence, so the journal tags these `[reclaim]` and the weekly review scores them against the
other versions. Calls without an invalidation from him are skipped: there's no honest stop.

## Watching between cycles

Most of what an exit check reacts to is a price crossing a level, which code can see without a model.
`rhgex monitor` (the watcher) polls quotes every minute during regular hours and exits, waking the session, only
when something needs a look: a watch trigger, a confirmed reclaim, a plan's stop, target or 1R level, or a
`[reclaim]` position at 15:45 ET. Each event fires once per level and day.

What it can't see still needs a model check on a heartbeat: order states and stuck stops, option marks, the
account value, earnings and expiry dates, a fading thesis. The heartbeat scales with what's at risk:

| Held | Heartbeat | Why |
|---|---|---|
| Options, spreads, fractional shares, anything without a resting stop | 15 min | The check is their stop, or it needs Robinhood data |
| Shares or 2x funds with resting stops | 30 min | The broker's stop protects them; the watcher catches the levels |
| Only watches, or nothing | 60 min | The watcher catches triggers within about a minute |

Its quotes come from Yahoo (a script can't call Robinhood) and can lag, so an event is a reason to look, never a
trade: every action is confirmed on a Robinhood quote first. If quotes stop, it says so (`FEED_DOWN`) and the
loop falls back to 15-minute checks, so a dead watcher never looks like a quiet market.

## What can still go wrong

- **Gaps.** A stop only caps the loss if price trades through it. An overnight gap can blow past it, and on a
  2x fund the gap counts double. No holding through earnings and the shorter fund time stop are the defenses.
- **Days without a session.** Only resting stops protect positions; spreads and fractional shares have none.
- **No posts.** If X logs out of Chrome, the cycle can't read him; it notifies you and trades nothing new from
  posts until you log back in. Exits and watches keep working.
- **The source.** His levels are an input with a mixed record; the journal and `calls stats` show how much to
  trust them.
- **Real money.** Fund the account with what you can lose. That balance is the true limit.
