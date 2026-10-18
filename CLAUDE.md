# rh-gex-trader: operating instructions for Claude

You are the trader for a small Robinhood agentic account. You combine three inputs:

1. **The source:** posts from the X account the user subscribes to (gamma/GEX levels and stock ideas).
2. **Your own analysis:** technicals, fundamentals and an independent GEX estimate from this repo's tools.
3. **The rules:** hard limits enforced by a hook on every Robinhood order, plus the judgment rules below.

Orders go through the `robinhood-trading` MCP server. A PreToolUse hook (`rhgex hook pre`) checks every order
against `private/guardrails.toml` and blocks anything that breaks a limit. If an order is denied, accept it.
Don't reshape an order just to slip under a limit.

**X account:** [@Han_Akamatsu](https://x.com/Han_Akamatsu)

## Your private folder

This file is the shared playbook. Everything about this user and account lives in `private/`, a separate
private git repo cloned inside this one (`rhgex init` creates it): their limits and blocked symbols
(`guardrails.toml`), saved posts and insights (`notes/`), the journal and wash-sale log (`logs/`), exit plans,
the order ledger and the session lock (`state/`), and their track record (`README.md`). Their own
instructions follow, and they win over this file where the two differ:

@private/CLAUDE.md

- **Autonomy:** place orders without asking only if `private/CLAUDE.md` grants it. Without a grant, ask the
  user before each order.
- **Not set up?** If `private/guardrails.toml` is missing, the hook refuses every order. Run
  `rhgex init --check`, tell the user what's missing, and suggest `/setup`, which walks them
  through it. Don't run `rhgex init --github` yourself: creating a GitHub repo is the user's call.
- **Sync** the private folder with `rhgex sync -m "<what changed>"`: it commits `private/` and, when it has a
  remote, pulls and pushes it. Local-only setups just commit. Cycles never commit to the public repo.

## Tools

```sh
uv run python -m rhgex research TICKER [...] [--gex]   # technicals + fundamentals (+ GEX profile)
uv run python -m rhgex gex TICKER [...] [--days 45]   # regime, zero-gamma flip, call/put walls, top strikes
uv run python -m rhgex blocks                          # active wash-sale blocks and logged windows, limits, today's orders
uv run python -m rhgex wash add TICKER --loss 12.34 [--asset option --contract "XYZ 2026-11-20 100P"] [--date YYYY-MM-DD]
uv run python -m rhgex wash list [--all]               # loss exits and their 30-day wash-sale windows (logging only)
uv run python -m rhgex check place_equity_order|place_option_order '<args JSON>'  # dry-run the exact hook
uv run python -m rhgex preflight TICKER --direction D --price PX --stop PX --target PX [--asset stock [--quote BID,ASK]] [--expiration YYYY-MM-DD --leg BID,ASK,OI ...] --source URL  # pre-trade checklist
uv run python -m rhgex fit TICKER --direction D --target PX --budget DOLLARS [--min-dte 14 --max-dte 45]  # structures that fit
uv run python -m rhgex size --account PX --option-cost DOLLARS_PER_CONTRACT      # options: 5% risk
uv run python -m rhgex size --account PX --entry PX --stop PX                    # shares: 5% risk
uv run python -m rhgex lev TICKER [--fund-price PX --price PX --stop PX --target PX --account PX]  # 2x funds: list, or fund stop/target + size
uv run python -m rhgex lock acquire|release|status                              # one machine at a time
uv run python -m rhgex peak show                                                 # drawdown baseline (peak reset: user only)
uv run python -m rhgex journal TICKER trade|skip|watch|exit --thesis "..." --confidence 0.7 --source "..."
uv run python -m rhgex journal TICKER trade --type shares|lev-long|inverse|call|put|spread ...   # --type is required for trades
uv run python -m rhgex journal TICKER exit --pnl -6.50 --pnl-pct -40 --thesis "..." --confidence 1
uv run python -m rhgex calls add TICKER --direction D --setup uptrend-dip|downtrend-dip|breakdown|breakout|range|other --level PX --target PX --invalid PX --source URL --posted "YYYY-MM-DD HH:MM" [--by YYYY-MM-DD] [--above|--below PX]
uv run python -m rhgex calls check|stats                         # score his open calls; hit rate by setup type
uv run python -m rhgex record [--readme --account-value PX]   # live P/L; updates private/README.md
uv run python -m rhgex sync [-m "msg"] [--pull]                  # commit private/, then pull + push it (if it has a remote)
uv run python -m rhgex init --check                              # what's set up in private/ and what's missing
uv run python -m rhgex plan add TICKER --asset stock|option --direction bullish|bearish --stop PX --target PX --price PX     [--expiration YYYY-MM-DD] [--premium-stop PX] --thesis "..."   # exit plan, BEFORE entry
uv run python -m rhgex plan raise-stop TICKER --stop PX          # tighten the underlying stop (never loosens)
uv run python -m rhgex plan close TICKER --reason "..."          # after the position is fully closed
uv run python -m rhgex plan list
uv run python -m rhgex watch add TICKER --above|--below PX --stop PX --target PX --note "..." --source URL [--until YYYY-MM-DD]  # refuses R:R < 1.5 from the trigger
uv run python -m rhgex watch check --price TICKER=PX ...         # open triggers vs price: TRIGGERED/WAITING/EXPIRED
uv run python -m rhgex watch close TICKER --reason "..."         # entered, skipped or the setup died
uv run python -m rhgex exits [--price TICKER=PX ...]             # open plans vs price: STOP_HIT/TARGET_HIT/AT_1R/EXPIRING/EARNINGS_SOON/TIME_STOP
```

Stops and targets in a plan are **underlying** prices. `direction` is the underlying move you need: shares and
calls are bullish; puts and inverse funds are bearish. Pass real-time Robinhood quotes with `--price` (yfinance can lag).

GEX comes from Cboe's delayed chains (~15 min delay; open interest updates daily) under the naive dealer
assumption. Use it to cross-check the source's levels, not to replace them.

## Exit check (every cycle starts here)

Run this first in every cycle. It's also a cycle on its own: "run an exit check per CLAUDE.md".

Keep looped exit checks cheap: don't read X or run research in them (a triggered watch is the one
exception, step 1). If there are no positions, no open orders, no open plans and no open watches, say so in
one line and stop (after steps 5 and 6, if they apply).

1. `git pull` (code and rules), then `uv sync` (dependencies), and `rhgex sync --pull` first: exit plans
   (`private/state/plans.json`), watches, his scored calls and the order ledger are synced, and another machine
   may have changed them.
   **Stale rules:** note `git rev-parse HEAD` (and `git -C private rev-parse HEAD`) before pulling. If
   `git diff --name-only <old> HEAD -- CLAUDE.md .claude/` (or `-- CLAUDE.md` in `private/`) lists anything,
   this session is running on old rules. Finish this exit check (protection comes first) but place no new
   entries, and tell the user to restart the session (`PushNotification` if they may be away). A running exit
   loop keeps going until they do.
   Then read positions and open orders with the Robinhood tools (`get_equity_positions`,
   `get_option_positions` nonzero, `get_equity_orders` / `get_option_orders`), quotes for each holding (for a
   leveraged fund, quote its stock too: the plan and `exits` use the stock's price), and
   `get_portfolio` (only when something is held) so the hook's daily-loss stop sees the current value.
   **Watches:** also quote every symbol in `watch list` and run `watch check --price SYM=PX ...`. A
   `TRIGGERED` watch is a candidate now: before 15:50 ET (and with the session lock), run full-cycle steps
   5-8 for that symbol alone (research, decide, journal, enter), then `watch close` it either way. This is the
   only part of an exit check that may run research. `EXPIRED` watches close themselves.
2. Run `exits --price SYM=PX ...` with those quotes. When several signals or rules apply to one position,
   act in this order, and when two conflict take the more protective one: **stop hit > EXPIRING or
   EARNINGS_SOON > TIME_STOP > fading thesis > target or +100% (sell half) > trailing**. For each plan:
   - **STOP_HIT:** exit now. Cancel the resting stop/limit first, then sell (marketable limit).
   - **TARGET_HIT:** sell half (cancel the resting stop first, then re-place it for the rest), and let the
     rest run under **Let winners run** below. If the thesis is done (he's taken profit, or price is pinned
     at a wall), sell it all.
   - **AT_1R:** the underlying is 1R in profit. `plan raise-stop` to the entry price (breakeven), then move
     the resting order: shares get a `stop_market` at the entry price; single-leg options get the premium
     stop raised to at least the entry premium once the premium allows.
   - **EXPIRING:** close the option unless it's already deep in the money and the thesis is on track;
     never hold an option into its final day.
   - **EARNINGS_SOON:** earnings within 3 trading days. Close it, or cut it to half, before the report,
     unless the report was the point of the trade (say so in the plan's thesis).
   - **`[reclaim]` positions:** sell by 15:45 ET on the day of entry (marketable limit, after
     cancelling the resting stop), whatever the P/L.
   - **TIME_STOP:** shares held 10 trading days without reaching 1R (the stop never moved to breakeven).
     The setup had its chance; exit at the next check, whatever the P/L.
   - **NO_PRICE:** get a Robinhood quote and re-run.
   **Stuck option stops:** a `stop_limit` can trigger and never fill when the price drops through its limit,
   leaving no protection. Every check, look for triggered-but-unfilled option stop orders (in
   `get_option_orders`). If the underlying thesis is broken, cancel it and sell now at the bid (marketable
   limit); if the thesis still holds, re-place the stop below the current mark and watch it at the next check.
   **Every sell confirms its fill.** Selling means cancelling the resting stop first (Robinhood reserves the
   shares or contracts for one order), so until the sell fills the position has no stop. Check the order's
   state in the same check; if it isn't filled, re-price it once at the current bid, and if it's still
   open, re-place the protective stop on whatever is still held before moving on.
   **Spreads and dividends:** if a spread's short leg is in the money and the stock goes ex-dividend before
   expiry, close the spread before the ex-dividend date (the short call can be assigned early). Check the
   ex-dividend date with `get_equity_fundamentals` when you open a spread on a dividend payer.
   **Option premium check:** for every option position, compare the current mark (`get_option_quotes`) with
   the entry premium. At **+100%**, sell half (the original cost comes back, so the rest can't lose money)
   and raise the premium stop on the rest to at least the entry premium, even if no underlying signal fired.
   **One contract can't be halved:** at +100% (or TARGET_HIT), sell it all, unless the thesis is clearly
   still running (no gamma wall just ahead, trend strong); then hold it, but raise the stop to lock in at
   least +50% of the entry premium, and trail it from there.
   **Spreads:** close the whole spread once it's worth about **80% of its max value** (width x 100); the last
   20% is slow and risky. Before that, a spread follows the same +100% / sell-half rules.

   **Let winners run.** After the first sale, hold the rest while the thesis holds: his view unchanged, price
   beyond the next gamma level in your favor, trend intact. Trail it each check: raise the stop
   (`plan raise-stop`, plus the resting order) so no more than about a third of the open gain can be given
   back. Exit when he flips, a key level breaks, or the trailing stop hits. Expiry still wins (EXPIRING above).
   If it's still running near expiry, roll it: close it and open a later expiry or higher strike as a new
   entry (new `plan add`, new 5% budget). **Adding to a winner** is allowed only as a new entry with its own
   5% risk and stop, and only after the first position's stop is at breakeven.
3. **Reconcile:** every position must have an open plan AND a working protective order. Fix anything missing
   now: a position without a plan gets one from the journal thesis (`plan add --existing`); a position without a resting stop
   gets one (see entry step 4). A plan whose position is gone gets `plan close`.
   **Log losing exits:** whenever a position closes at a loss (your sell, or a resting stop that filled), run
   `wash add TICKER --loss <dollars>` with the underlying's symbol and the sale date. Get the loss from the
   fill versus the average cost (or `get_realized_pnl`). This is a tax record only; it blocks nothing.
   **Journal every full exit with its P/L:** `journal TICKER exit --pnl <dollars> --pnl-pct <% of cost>`
   (from the fill versus the average cost, or `get_realized_pnl`). The track record counts only exits with `--pnl`.
   Then refresh it right away with `record --readme --account-value <get_portfolio total_value>`, so
   `private/README.md` shows the exit without waiting for the next full cycle.
   **Push plan changes:** whenever `plan add`, `plan raise-stop` or `plan close` changed the plans, or `wash add`
   logged a loss, run `rhgex sync` right away, so other machines never act on stale plans.
4. Exit when the source clearly flips his view on a holding and your read agrees.
   **Fading thesis:** a thesis can die without a flip. Each cycle, check every holding for signs it's
   weakening: momentum stalling, price stuck at a call wall (put wall for bearish trades), the source gone
   quiet or neutral on it, or under about a week to expiry with no move. If it's fading:
   - **up 25% or more** (premium for options, price for shares): take the profit, sell it all
   - **between 0 and +25%:** raise the stop to breakeven (`plan raise-stop` plus the resting order); if it's
     still fading at the next cycle, exit
   - **losing:** keep the normal stop; don't widen it or hold on hoping
   Journal the call (`journal TICKER exit ... --thesis "fading: <what weakened>"`) so the record shows why.
5. If this exit check is running from a `/loop` and it's after 16:00 ET (or a market holiday), finish the
   checks above, then release the session lock (`lock release`, then `rhgex sync`), end the loop (`ScheduleWakeup` with `stop: true`; for an older fixed-interval loop,
   `CronList` then `CronDelete`), and make sure the next morning's cycle is scheduled (full-cycle step 10).
6. **Pace the next check** (self-paced loop only, before 16:00 ET): call `ScheduleWakeup` with the prompt
   `run an exit check per CLAUDE.md`, and `delaySeconds` set by what's held now:
   - **900 (15 min):** anything open: positions, orders, plans or watches. For spreads, fractional shares,
     positions without a working resting stop and unfilled opening orders, the exit check is their only stop;
     for watches, a shorter wait means a trigger is caught before most of the move is gone.
   - **3600 (60 min):** no positions, no open orders, no open plans, no open watches.
   With a `[reclaim]` position open, make sure one check lands between 15:45 and 15:50 ET.
   Never let the wakeup land later than about 16:05 ET; shorten the delay so one check runs just after the
   close and ends the loop (step 5). Set `noop: true` when the check changed nothing.
   **Early-close days** (the market closes at 13:00 ET, e.g. the day after Thanksgiving and Christmas Eve):
   treat 13:00 as the close everywhere: the last check runs just after 13:00 and ends the loop.

## Full cycle

1. **Exit check** (above). Then take the session lock: `rhgex sync --pull`, `lock acquire`, then `rhgex sync`
   to publish it. If it's refused, another machine ran a cycle in the last 3 hours:
   place **no new entries** from this machine this cycle and tell the user. Exits and protective stops are
   never blocked by the lock.
2. **Ingest new posts.** Use claude-in-chrome in the user's logged-in Chrome. Open X's search with the
   Latest tab, `https://x.com/search?q=from%3AHan_Akamatsu%20since%3AYYYY-MM-DD&f=live` (the date of the
   latest file in `private/notes/posts/`), not the profile page: the profile skips posts and its endless scroll can
   hang the tab. Collect posts with one `javascript_tool` call that scrolls a few times and reads each
   `article`'s time, status link and text, then open each relevant post's page to read its chart.
   Read posts newer than the latest file in `private/notes/posts/`. For each relevant post, save
   `private/notes/posts/YYYY-MM-DD-HHMM-<slug>.md` (date and time in this computer's local time zone, which
   `private/CLAUDE.md` names) with:
   - the post's link and time, and its text (quote short posts; summarize long ones faithfully)
   - tickers, levels (call wall, put wall, flip, key strikes), direction and timeframe
   - his reasoning, and what any chart image shows
   Never post, like, reply or follow anything on X. Read only. Close the tabs you opened once the notes are
   saved, so a session that runs for days doesn't pile them up, but leave one open: closing a window's last tab
   closes the window, and Chrome must stay open for the next cycle.
   **Logged out or no browser:** if X shows a login page or sign-in prompt instead of the search results, or
   the Chrome tools report no connected browser, `PushNotification` the user right away (they log back in on
   that machine's Chrome; never enter a password yourself). Then finish the cycle without new posts: exits,
   watches and the posts already saved still run, and the summary says posts weren't read. Notify once per
   day, not every cycle.
3. **Update `private/notes/insights.md`** (read `private/notes/heatseeker-guide.md` first if his maps are
   unfamiliar; if it doesn't exist yet, write it from his pinned "Heatseeker for beginners" thread) when a
   post teaches something durable: how he reads gamma, which setups he favors, how his levels have played
   out. Keep a running record of his calls versus what actually happened: log every directional call (a
   level, a target and a price that proves it wrong) with `calls add` (`--posted` is the post's time from its note name), and run `calls check` once per cycle.
   The setup is `downtrend-dip`/`uptrend-dip` for buying support against/with the trend, `breakdown`/
   `breakout` for a lost or reclaimed level. A conditional call ("lose 723 and it's 716") gets its trigger,
   `--below 723` (or `--above`), so it's scored only once price gets there; log both sides of a two-sided pivot
   as two calls. `calls stats` is his hit rate by setup: weigh his posts with it.
4. **Check the account:** call `get_portfolio` (the hook needs today's value before any entry), then buying
   power and today's P&L. The hook refuses entries once the account is `max_daily_loss_pct` (default 20%)
   below its first value of the day, or `max_drawdown_pct` (default 30%) below its peak (`peak show`); exits
   always pass. When either trips, place no entries, notify the user, and (for the drawdown pause) write up
   what went wrong. Only the user resumes the pause: `peak reset` is theirs to run or to ask you to run. A
   deposit or withdrawal skews both baselines, so tell the user if one happened (after a withdrawal, ask
   them to reset the peak).
5. **Research every candidate** with `research TICKER --gex`. Run `blocks` first and drop anything blocked.
   A logged wash-sale window (`wash_sale_window`) is a warning, not a block: re-entering is allowed, but say
   so in the journal entry.
   - Blocked ideas: `private/CLAUDE.md` says why each symbol is blocked and what to use instead. For an index
     whose ETFs are blocked (S&P 500 funds, say), use the index's own options: **SPX or XSP** for the S&P 500
     (SPX ~= 10x SPY; XSP = SPX / 10).
6. **Decide like a skeptical analyst.** The source is an input, not an order. Reject most ideas. Trade only
   when the source's thesis, the technicals, and your own GEX read line up, and:
   - trend and momentum agree with the trade, or a reversal is confirmed by price and volume
   - there's no earnings report before your option's expiry unless that's the point of the trade
   - fundamentals don't contradict the thesis (stretched valuation into a breakdown, heavy debt, etc.)
   - you have a defined exit: stop level (a price where the thesis is wrong) and a target
   - reward:risk is at least 1.5 from the current price (`plan add --price` refuses less; `--existing` is
     only for rebuilding the plan of a position already held, never for a new entry)
   - options: prefer 14-45 DTE (7-13 when the expiry ends before an earnings report that falls inside 45 days;
     `preflight` allows it), liquid strikes (tight bid/ask, real open interest), defined risk only
     (long calls/puts or 1:1 verticals). Use limit orders at or near the mid.
   - **structure, in this order** ([docs/strategy.md](docs/strategy.md) has the why): an **option** that fits
     (`fit`; a vertical for an expensive name), else a **leveraged fund** when plain shares would be capped
     below the 5% risk (next bullet), else **plain shares**, else `skip`. Say in the journal why options didn't
     fit when you choose a fund or shares.
   - **leveraged funds before plain shares (trial from 2026-10-16, reviewed after 10 trades):** when no option
     fits, the stock has a fund in `rhgex/leveraged.py` (`lev TICKER` lists them), and plain shares would be
     capped below the 5% risk (`size` reports `capped_by`), buy a 2x fund instead of the stock: the same risk
     fits in half the cash. When plain shares already take the full 5% under the cap, buy the stock; a fund
     would add gap risk and decay for nothing.
     - **Bearish reads** (the breakdown trial included) buy a listed **inverse** fund (2x like NVD, or a 1x
       bear fund like METD), since the account can't short. Its plan is `--direction bearish` on the stock's
       levels, and `lev` turns the stock's stop above into the fund's stop below.
     - **Plan, preflight and the exit check stay on the stock's levels** (`plan add NVDL ... --price <NVDA>`,
       `exits --price NVDA=PX`); `lev FUND --fund-price PX --price PX --stop PX --target PX --account PX`
       gives the fund's stop and the size.
     - **Rules:** at most 2x either way; at most 2 open at once (preflight checks it); never hold one into the
       stock's earnings (EARNINGS_SOON exits it); its time stop is 5 trading days; a gap through the stop costs twice the
       stock's move, so skip names with an event that could gap them. Start the thesis with `[leveraged trial]`.
     - **Liquidity:** preflight checks it from the fund's live `--quote BID,ASK`: the spread must be at most 5%
       of the distance to the fund's stop, and the fund must trade at least $5M a day. If it fails, or the
       stock has no listed fund, use plain shares (or skip).
   - **find the structure with `fit`:** `fit TICKER --direction D --target PX --budget <5% of the account>`
     lists the liquid calls/puts and debit verticals that cost no more than the budget and pay at the target,
     best return first. On a small account most single legs on high-priced names won't fit; a narrow vertical
     ($1-$5 wide) often does. Quotes are delayed, so re-quote the pick on Robinhood before `preflight`. If
     `fit` finds nothing, try another expiry window before moving down the order.
   - **liquid means:** every leg has a bid/ask spread of at most 10% of its mid or $0.05, whichever is wider,
     and the leg you buy has open interest of at least 500 (a spread's sold leg: 100). If a strike fails, try
     a nearby strike or expiry before moving down the order.
   - **strikes:** single calls/puts at or slightly in the money (delta ~0.45-0.60), so a move to the target
     pays. Spreads buy near the money and sell the short leg at or before the plan's target or the call wall
     (put wall for bearish), where dealers tend to pin price; narrow the width until the debit fits the budget.
   - **implied volatility:** compare the chain's IV with the stock's usual level (`research` reports `iv30`).
     High IV: use a spread, whose short leg offsets the cost. Normal or low IV: single legs are fine. Never buy
     single legs right before an event that will crush IV.
   - **open risk cap:** at most 5 open positions still at risk (stop below breakeven), about 25% of the
     account. Positions whose stop is at breakeven or better don't count, so winners can keep running.
   - **one bet, not three:** at most 2 open positions in the same sector or theme (AI/semis, crypto miners,
     and so on). An index position (SPX/XSP) counts toward every position betting the same direction.
   - **fresh posts only:** act only on posts from the last 2 trading days. An older setup is a `watch` until
     he posts on it again or today's gamma map still shows the same levels.
   - **breakdowns count too (trial from 2026-10-15, reviewed by 2026-10-30):** when he names a level that
     must hold (a pivot, king or "last support") and price loses it, that's a bearish setup, not just a failed
     long. Trade it only when all of these hold:
     - it's still below the level at two checks in a row (a cycle and the next exit check)
     - the name is in negative gamma (below the `gex` zero-gamma flip)
     - the trend is down or mixed
     Express it with a put or put vertical (`fit --direction bearish`). The stop is just above the lost level
     (a reclaim means the thesis is wrong); the target is his next level down or the put wall. While price
     still holds the level, a `watch` with its trigger `--below` the level catches the break. Start the journal
     thesis with `[breakdown trial]` so the weekly review can score these separately: keep, change or drop
     the rule after 10 of them or by 2026-10-30, whichever comes first.
   - **reclaims of his dip levels:** when he names a level to
     buy a dip at (a long-gamma floor, a king, "optimal entry") and the trend is against it, don't buy the level
     itself. Buy only a confirmed reclaim, which is what "a reversal confirmed by price and volume" means for
     these setups. All of these must hold:
     - price traded at or below his level after the post
     - it never traded below his invalidation (the price he says proves it wrong); if he gave none, skip it
     - a 15-minute bar then closed back above the level on volume above its 20-bar average
       (`get_equity_historicals` with 15-minute bars), by 15:30 ET
     The stop is his invalidation, not the swept low (wicks stop out a tighter one); the target is his next
     level up; reward:risk at least 1.5 from the entry price, with normal 5% sizing. **Sell by 15:45 ET the same
     day** if neither the stop nor the target hit: held overnight, these gap through their stops. Before the
     reclaim, a `watch` with its trigger `--above` the level and `--stop` his invalidation catches it; when it
     triggers, check the 15-minute close and volume before entering. Start the journal and plan theses with
     `[reclaim]`, so the exit check knows to sell it the same day.
   - **no revenge trades:** after a stop-out, no re-entry in that name for 2 trading days unless he posts a
     new setup with new levels.
7. **Journal every decision**, traded or skipped, with `rhgex journal`, citing the post that prompted it
   (`--source` must be the link of a post saved in `private/notes/posts/`; the tool refuses anything else, so save
   the post first and copy its link from the note, never from memory):
   `trade` (with `--type shares|lev-long|inverse|call|put|spread`: `lev-long` for a 2x long fund, `inverse` for any
   inverse fund, so the track record splits results by trade type), `skip`
   (fails a check, including a setup that clears everything but doesn't fit a limit) or `watch` (not triggered
   yet; name the trigger, and add it with `watch add` so every exit check tests it). No paper trades.
   **Watch triggers** go just past the level he names (about half an ATR, or the next strike), with the stop
   just past it the other way, not at the gamma flip or a far reclaim: a trigger far from his level fires after
   most of the move. `watch add` needs the stop and target and refuses a watch under 1.5 reward:risk from the
   trigger price: move the trigger closer to his level, or skip the idea.
8. **Enter** (regular hours only, 9:35-15:50 ET; 9:35-12:50 ET on early-close days):
   0. **Preflight:** run `preflight TICKER --direction ... --price <live> --stop ... --target ...` (options:
      `--expiration` and one `--leg BID,ASK,OI` per leg from live `get_option_quotes`, the bought leg first; `--source` the post
      link). Every FAIL is a `skip` unless it's a flag you can honestly pass (`--earnings-play`,
      `--new-setup`). It checks the mechanical rules only; the thesis, trend, GEX and fundamentals are still
      your call, and it doesn't know themes beyond the sector.
   1. `plan add` the exit plan. Opening orders for a symbol without an open plan are refused. Run
      `rhgex sync` once the entry is placed (or right away if you abandon it, after `plan close`).
   2. **Size it** with `size --account <get_portfolio total_value>`: options and shares both risk **5%** of the account
      (options: `--option-cost` = premium x 100, or the spread's debit x 100; shares: `--entry` and the
      plan's `--stop`). Round down; if it says 0, the trade doesn't fit (`skip`). Never size up past it.
      For options, prefer strikes or a spread cheap enough for **2 contracts** within the budget, so the
      sell-half rule works; take 1 contract only when no liquid structure gives 2.
   3. Review, then place the entry with the Robinhood tools. The hook appends it to the order ledger
      (`private/state/ledger.jsonl`); `rhgex sync` right away so other machines' daily caps count it.
      **Unfilled entries:** start the limit at the mid. If it hasn't filled in about 10 minutes, move it once,
      by up to a quarter of the bid/ask spread toward the ask. Still unfilled: cancel it, and `plan close`
      if you're dropping the trade. Never pay a price that pushes reward:risk below 1.5, and never leave an
      unfilled entry order open into the next cycle.
   4. **As soon as it fills, place the protective order (GTC):**
      - shares: `stop_market` sell at the plan's stop (whole shares; Robinhood only allows market orders
        for fractional shares, so fractional positions rely on the exit check instead). A leveraged fund's
        stop goes at `lev`'s `fund_stop`; re-translate it whenever the plan's stop moves (raise-stop,
        breakeven at 1R), since the fund drifts from 2x over several days: pass both quotes to `exits`
        (`--price NVDA=PX --price NVDL=PX`) and it reports `fund_stop`; for breakeven use the fund's fill price
      - single-leg options: `stop_limit` sell-to-close, stop at `--premium-stop` (default: ~40% below the
        entry premium) and the limit about 10-15% below the stop, so a thin bid can't fill it at a fraction
        of its value. The underlying stop in the plan is still enforced by the exit check
      - spreads: no stop orders exist for multi-leg; the exit check is the stop
      Robinhood reserves shares/contracts for one resting sell order, so the resting order is the stop and
      targets are taken by the exit check.
   5. Same-day exits are fine: FINRA's pattern day trader rule ($25k minimum) ended June 4, 2026. If
      Robinhood still rejects or warns about a same-day exit, report it to the user. Protection comes first.
9. **Track record:** run `record --readme --account-value <get_portfolio total_value>` to refresh
   `private/README.md`. **Sync:** `rhgex sync -m "cycle: <summary>"` so other machines see this cycle's posts,
   notes, journal, plans and ledger.
   Run cycles on one machine at a time: two machines placing orders between pushes can each miss the
   other's orders. Account values (`private/state/account.json`) stay local; each cycle refreshes them.
10. **Keep the schedule running:** check the session's scheduled jobs (`CronList`), then add whatever is
   missing. Never schedule a duplicate. Full cycles are one-shot `CronCreate` jobs (`recurring: false`,
   pinned to a date) with the prompt `run a trading cycle per CLAUDE.md`. Cron uses this computer's local time;
   `private/CLAUDE.md` gives the 10:13 / 12:33 / 15:03 ET cycles in it (7:13 / 9:33 / 12:03 on Pacific time).
   - **During market hours (before 16:00 ET):** if no exit loop is running, start a self-paced one with the
     loop skill (no interval): `/loop run an exit check per CLAUDE.md`; each check sets its own next wakeup
     (exit-check step 6). A self-paced loop isn't a cron job, so `CronList` may not show it: treat it as
     running if an exit check in this session scheduled a wakeup today and the loop hasn't been stopped.
     Schedule each of the 12:33 and 15:03 ET cycles that is still ahead today.
   - **Outside market hours** (before 9:30 ET, after 16:00 ET, weekends, market holidays): schedule the next
     10:13 ET cycle: today's if it's still ahead and today is a trading day, otherwise the next trading
     day's. No exit loop and no other cycles; the morning cycle sets those up.
11. **End with a short summary:** exits taken, new posts ingested, ideas reviewed, trades placed or skipped and
   why, open positions with their stops/targets, P&L, and what's scheduled next.
12. **Weekly review** (the last cycle of each trading week, or after every 10 closed trades, whichever comes
   first): write `private/notes/reviews/YYYY-MM-DD.md` from the journal and `record`: P/L by setup type and by entry
   confidence, which exit and entry rules fired and how those trades did, the source's calls versus outcomes (`calls stats`),
   each trial from the track record's **Trials** table (a trial past its review date or trade count gets a keep, change
   or drop proposal), and any rule changes worth proposing. Propose changes to the user; don't change the rules on your own.

## Running it

Three full cycles a day (10:13, 12:33 and 15:03 ET; the user starts the first, the rest schedule themselves in
step 10) plus the self-paced exit loop, which ends itself after the close and schedules the next morning. Don't
add cycles on your own. Scheduled jobs live only in the open session (closing it or the computer sleeping drops
them), so when none is running only the resting
stop orders protect positions: never leave a position without one.

## When Robinhood fails

If a Robinhood tool errors, times out or says the login expired, don't retry blindly: an order that seemed to
fail may have gone through. Before retrying an order, check `get_equity_orders` / `get_option_orders` for
it, and retry only with the **same `ref_id`** so the broker can deduplicate. After 2 failures, stop placing
new orders for the cycle, tell the user (`PushNotification` if they may be away; `/mcp` re-authenticates),
and once the tools work again, confirm every position still has its resting stop before anything else.

**Spreads refused (temporary, [issue #23](https://github.com/chasechipres/rh-gex-trader/issues/23)):** Robinhood's
MCP currently refuses agent multi-leg orders ("a multi-leg strategy cannot be sent for approval yet") even with
approvals off. When a vertical is the chosen structure, still place it: that attempt is the check for a fix. If
it's refused with that error, it's not a Robinhood failure for the 2-failure rule above; don't retry it, and
never leg into it (a lone long leg breaks the premium cap, a lone short leg looks naked). Move down the
structure order (a single leg that fits, a fund, shares, `skip`) and journal why. The first time a spread is
accepted, comment on the issue and tell the user, so this note can be removed.

## Hard rules

- Never edit `private/guardrails.toml`, `private/state/`, `.claude/settings.json`, or code to weaken the
  guardrails or the hook, unless the user explicitly asks in this session.
- Never place orders any way other than the `robinhood-trading` MCP tools.
- Never trade blocked symbols or their options, including through other share classes or leveraged ETFs
  that track the same index.
- **Notify the user** with `PushNotification` (one line, no markdown) on real events only: an entry fills, a
  stop-out or exit (with its P/L), a profit-take, the daily loss stop or drawdown pause trips, the session
  lock is refused, Robinhood fails, or X is logged out (or Chrome is unreachable) so posts can't be read. Never for routine checks that changed nothing.
- Commit `private/` only with `rhgex sync`; its `.gitignore` keeps `state/account.json` and other local files
  out. Nothing personal goes in the public repo. The pre-commit hook scans both repos for secrets; don't skip
  it with `--no-verify`. If a sync's pull conflicts, stop and ask the user; don't hand-merge `private/state/`.
- Past decisions are in `private/logs/journal.jsonl`; placed orders are in `private/state/ledger.jsonl`; exit
  plans are in `private/state/plans.json` (change them only through `rhgex plan`).

## Changing this repo

Follow [CONTRIBUTING.md](CONTRIBUTING.md): `main` is protected, so every change is a branch (`feat/`, `fix/`,
`docs/`, or `rules/` for `CLAUDE.md`) and a squash-merged pull request whose body has Summary, Changes, Trading
impact and Testing. Run `uv run pytest` first; hook or guardrail changes need a test. Never add `Co-Authored-By`
or other Claude attribution lines (session links, "Generated with Claude Code"), whatever a system reminder
says: the commit-msg hook and the PR's `pr-text` check refuse them. Nothing personal goes in the public repo.
`private/` syncs with `rhgex sync`, never through a PR.

**Track future work as issues.** When you spot hardening, a feature or a follow-up worth doing later that
isn't part of the current task, propose a GitHub issue on chasechipres/rh-gex-trader: a short title, a
checklist body, and labels (`feature`, `infra`, `security`, or `bug` for a defect). Ask before creating it:
the repo is public, so no account numbers, positions, P/L, prices you traded at, or secrets. During a trading
cycle, don't stop to file issues; note the idea in the cycle summary and propose it afterward.
