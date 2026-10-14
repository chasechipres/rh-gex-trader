# Private instructions: this account and its owner

The public CLAUDE.md is the playbook; this file is what's specific to you. Claude reads both every session
(the public file imports this one). The values below are placeholders: change each line marked **EDIT** to
fit you, and delete what doesn't apply. Commit it with `rhgex sync`.

## Autonomy grant

**EDIT** (keep, change or delete this paragraph; without it Claude asks before every order):

From the account owner: you may place, modify and cancel orders in the agentic account through the
`robinhood-trading` MCP tools without asking me first, when the trade follows CLAUDE.md's rules and passes the
guardrails hook. That covers opening entries, protective stops and exits. This grant never extends to other
accounts, to blocked symbols, or to editing `private/guardrails.toml` or the hook.

## The account

- **EDIT** Size and goal: a small ($X,XXX) account funded with money I can afford to lose, aiming for
  growth. Describe your risk appetite here; the limits themselves live in `private/guardrails.toml`.
- **EDIT** Deposits or withdrawals: I'll say when I make one, so the daily loss baseline and the drawdown
  peak can be read correctly.

## Time zone and schedule

- **EDIT** My computers run on **Eastern time**. Cron and the post file names use it. (Machines in
  different time zones? Name each one and its zone.)
- **EDIT** Full cycles at 10:13 / 12:33 / 15:03 ET are cron times **10:13 / 12:33 / 15:03** here. (Central:
  9:13 / 11:33 / 14:03. Mountain: 8:13 / 10:33 / 13:03. Pacific: 7:13 / 9:33 / 12:03.)

## Blocked symbols and why

`private/guardrails.toml` blocks them; this is the reasoning, so ideas get redirected instead of just dropped.

- **EDIT** (example) **SPY, VOO, IVV, SPLG, SPYM:** I buy an S&P 500 fund in another account (a 401k, an
  IRA, automatic investing), and a loss on any S&P 500 fund here inside 30 days of a buy there can be a wash
  sale. Express S&P 500 views with **SPX or XSP options** instead (SPX ~= 10x SPY; XSP = SPX / 10), which are
  Section 1256 contracts. Delete this line if it doesn't apply, and uncomment the block in `guardrails.toml`
  if it does.
- **EDIT** (example) **ABC, XYZ:** I hold them in another account; don't trade them here in either
  direction. List yours, or delete this line.

## Anything else

- **EDIT** Add standing preferences here: sectors to avoid, a max number of trades a day you're comfortable
  with, when to notify you, and so on. Delete this line if there's nothing.
