// Collect the source's posts from X's search page (CLAUDE.md, full cycle step 2). Paste this whole file into one
// `javascript_tool` call on the search tab (it uses the tool's top-level `await`). It returns the post count and
// the newest and oldest times; running it again keeps what it has and scrolls on. Then read the posts with
// `rhgexBatch(0)`, `rhgexBatch(<next>)`, ... until `next` is null.
//
// Why it looks like this: Claude in Chrome blocks a result that contains a URL or query string, and long results
// get cut off. So the posts stay in the page (window.rhgexPosts), links are stripped from the text, each post comes
// back as its numeric status id (the link is https://x.com/Han_Akamatsu/status/<id>), and rhgexBatch returns them
// in batches of about 3k characters. `m` counts a post's images and videos (it can undercount: X loads media as it
// scrolls into view); open the post to read a chart. Search results cut long posts off at "Show more", and only
// the post's own text is read, not a quoted post's: open the post for either.
await (async () => {
  const URLISH = /(https?:\/\/\S+|\b[\w-]+(\.[\w-]+)+\/\S*|\S*[?&]\S*=\S*)/g; // links, bare domain/paths, queries
  const seen = new Map((window.rhgexPosts || []).map((p) => [p.id, p]));
  const read = () => {
    for (const a of document.querySelectorAll("article")) {
      const link = [...a.querySelectorAll('a[href*="/status/"]')].find((l) => l.querySelector("time"));
      const id = link && (link.getAttribute("href").match(/status\/(\d+)/) || [])[1];
      if (!id || seen.has(id)) continue;
      const text = (a.querySelector('[data-testid="tweetText"]')?.innerText || "").replace(URLISH, "[link]");
      const media = a.querySelectorAll('[data-testid="tweetPhoto"], video').length;
      seen.set(id, { id, time: link.querySelector("time").getAttribute("datetime"), text, media });
    }
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  for (let w = 0; w < 20 && !document.querySelector("article"); w++) await sleep(500); // page still loading
  // Scroll until two rounds in a row find nothing new (the end of the search), at most 25 rounds.
  for (let i = 0, idle = 0; i < 25 && idle < 2; i++) {
    const before = seen.size;
    read();
    idle = seen.size === before ? idle + 1 : 0;
    window.scrollBy(0, 2500);
    await sleep(2000);
  }
  read();
  window.rhgexPosts = [...seen.values()].sort((a, b) => b.time.localeCompare(a.time));
  // A batch of compact posts ({id, t: UTC minute, m: images/videos, x: text}) under `budget` characters. By default
  // only posts that name a $TICKER or carry an image (his levels and charts); {all: true} returns everything.
  const relevant = (p) => /\$[A-Z]{1,5}\b/.test(p.text) || p.media > 0;
  window.rhgexBatch = (start = 0, { all = false, budget = 3000 } = {}) => {
    const list = all ? window.rhgexPosts : window.rhgexPosts.filter(relevant);
    const out = [];
    let size = 0, i = start;
    for (; i < list.length; i++) {
      const p = list[i];
      let x = p.text.replace(/\s+/g, " ").trim();
      if (x.length > budget - 200) x = x.slice(0, budget - 200) + " [cut: open the post]";
      const c = { id: p.id, t: p.time.slice(0, 16) + "Z", m: p.media, x };
      const n = JSON.stringify(c).length;
      if (out.length && size + n > budget) break;
      out.push(c);
      size += n;
    }
    return { posts: out, next: i < list.length ? i : null, total: list.length,
             skipped: window.rhgexPosts.length - list.length };
  };
  const ps = window.rhgexPosts;
  return { total: ps.length, newest: ps[0]?.time, oldest: ps[ps.length - 1]?.time,
           loggedIn: !!document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]') };
})();
