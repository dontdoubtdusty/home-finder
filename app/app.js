// Home Finder phone app. Data comes from Firestore (written by the PC collector);
// favorites / hidden / notes / phone-added listings are shared between allowed users.
import { firebaseConfig } from "./firebase-config.js";
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signInWithRedirect,
  getRedirectResult, signOut,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  initializeFirestore, persistentLocalCache, persistentMultipleTabManager,
  collection, doc, onSnapshot, getDoc, setDoc, addDoc, updateDoc, deleteDoc,
  serverTimestamp, arrayUnion,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

// ---------------------------------------------------------------- helpers
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "?" : "$" + Math.round(n).toLocaleString());
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
const num = (v) => (v === "" || v == null || isNaN(+v) ? null : +v);
const bedsLabel = (b) => (b == null ? "? bd" : b === 0 ? "Studio" : `${b} bd`);

const FLAGS = {
  below_market: "Below market", price_drop: "Price drop",
  stale: "Long on market", cheapest_site: "Cheapest across sites",
};
const PETS = { cat: "Cats", dog: "Dogs" };
const AMENITIES = {
  in_unit_laundry: "In-unit laundry", laundry_on_site: "Laundry on site", parking: "Parking",
  garage: "Garage", dishwasher: "Dishwasher", ac: "A/C", gym: "Gym", pool: "Pool",
  elevator: "Elevator", balcony: "Balcony", furnished: "Furnished",
};
const ICON = {
  star: '<svg viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" fill="FILL" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
  hide: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 6.1A9.9 9.9 0 0 1 12 6c5 0 9 6 9 6a16 16 0 0 1-2.6 3.2M6.6 6.6C4.3 8.1 3 12 3 12s4 6 9 6a8.6 8.6 0 0 0 4.4-1.2M9.9 9.9a3 3 0 0 0 4.2 4.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  note: '<svg viewBox="0 0 24 24"><path d="M5 4h14v12l-4 4H5z M15 20v-4h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
};
const star = (on) => ICON.star.replace("FILL", on ? "currentColor" : "none");

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem("hf-prefs")) || {}; } catch { return {}; }
}
function savePrefs() {
  try { localStorage.setItem("hf-prefs", JSON.stringify(S.prefs)); } catch { /* private mode */ }
}

// ---------------------------------------------------------------- state
const S = {
  user: null,
  listings: new Map(),   // id -> listing (active and recently inactive)
  state: new Map(),      // id -> {favorite, hidden, note}
  subs: [],              // phone submissions
  meta: null,
  view: "deals",
  prefs: Object.assign({ sort: "score", max: "", beds: "", match: true, hidden: false, flags: [] }, loadPrefs()),
  unsubs: [],
  map: null, mapLayer: null, pickMap: null, pickMarker: null, pick: null,
};

// ---------------------------------------------------------------- firebase
const configured = !String(firebaseConfig.apiKey || "").startsWith("REPLACE");
let auth, db;
if (configured) {
  const app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  db = initializeFirestore(app, {
    localCache: persistentLocalCache({ tabManager: persistentMultipleTabManager() }),
  });
}

function showGate(msg, { signIn = false, signOutBtn = false } = {}) {
  $("app").hidden = true;
  $("gate").hidden = false;
  $("gateMsg").textContent = msg;
  $("signInBtn").hidden = !signIn;
  $("gateSignOut").hidden = !signOutBtn;
}

async function doSignIn() {
  const provider = new GoogleAuthProvider();
  try {
    await signInWithPopup(auth, provider);
  } catch (e) {
    if (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment") {
      await signInWithRedirect(auth, provider);
    } else if (e.code !== "auth/popup-closed-by-user" && e.code !== "auth/cancelled-popup-request") {
      showGate(`Sign-in failed: ${e.message}`, { signIn: true });
    }
  }
}

function stopListeners() {
  S.unsubs.forEach((u) => u());
  S.unsubs = [];
  S.listings.clear(); S.state.clear(); S.subs = []; S.meta = null;
}

async function onUser(user) {
  stopListeners();
  S.user = user;
  if (!user) {
    showGate("Rental deals near you, compared across sites. Sign in to continue.", { signIn: true });
    return;
  }
  const email = (user.email || "").toLowerCase();
  let allowed = false;
  try {
    allowed = (await getDoc(doc(db, "allowed_users", email))).exists();
  } catch (e) {
    if (e.code === "unavailable") allowed = true; // offline: let cached data show
  }
  if (!allowed) {
    showGate(`${email} isn't on the list yet. Ask the owner to run:  py -m homefinder allow ${email}`,
      { signOutBtn: true });
    return;
  }
  $("gate").hidden = true;
  $("app").hidden = false;
  $("menuEmail").textContent = email;
  startListeners();
  render();
}

function startListeners() {
  const err = (what) => (e) => toast(`Couldn't load ${what}: ${e.code || e.message}`);
  S.unsubs.push(onSnapshot(collection(db, "listings"), (snap) => {
    snap.docChanges().forEach((c) => {
      if (c.type === "removed") S.listings.delete(c.doc.id);
      else S.listings.set(c.doc.id, Object.assign({ id: c.doc.id }, c.doc.data()));
    });
    scheduleRender();
  }, err("listings")));
  S.unsubs.push(onSnapshot(collection(db, "state"), (snap) => {
    snap.docChanges().forEach((c) => {
      if (c.type === "removed") S.state.delete(c.doc.id);
      else S.state.set(c.doc.id, c.doc.data());
    });
    scheduleRender();
  }, err("saved items")));
  S.unsubs.push(onSnapshot(collection(db, "submissions"), (snap) => {
    S.subs = snap.docs.map((d) => Object.assign({ _id: d.id }, d.data()))
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    scheduleRender();
  }, err("added listings")));
  S.unsubs.push(onSnapshot(doc(db, "meta", "summary"), (snap) => {
    S.meta = snap.exists() ? snap.data() : null;
    scheduleRender();
  }, err("summary")));
}

async function setState(id, patch) {
  try {
    await setDoc(doc(db, "state", id),
      Object.assign({}, patch, { updated_by: S.user.uid, updated_at: serverTimestamp() }), { merge: true });
  } catch (e) {
    toast(`Not saved: ${e.code || e.message}`);
  }
}

// ---------------------------------------------------------------- rendering
let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; render(); });
}

function render() {
  if (!S.user) return;
  renderHeader();
  if (S.view === "deals") renderDeals();
  if (S.view === "map") renderMap();
  if (S.view === "saved") renderSaved();
  if (S.view === "add") renderSubs();
  // Don't rebuild the sheet under someone typing a note (it would drop focus).
  if (!$("sheet").hidden && S.openId && document.activeElement?.id !== "noteBox") renderSheet(S.openId);
}

function renderHeader() {
  const m = S.meta;
  if (!m) { $("updated").textContent = "Waiting for first update from the PC…"; return; }
  const when = new Date(m.updated_at || m.generated_at);
  const nMatch = activeListings().filter((l) => l.passes_filters).length;
  $("updated").textContent = `${nMatch} match · updated ${when.toLocaleDateString()} ${when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  $("areaSummary").innerHTML = (m.summary || []).map((s) =>
    `<span class="stat">${esc(bedsLabel(s.beds))} median <b>${money(s.median)}</b></span>`).join("");
}

const activeListings = () => [...S.listings.values()].filter((l) => l.active !== false);
const st = (id) => S.state.get(id) || {};

function filtered() {
  const p = S.prefs;
  const max = num(p.max), beds = num(p.beds);
  const rows = activeListings().filter((l) =>
    (!p.match || l.passes_filters) &&
    (p.hidden || !st(l.id).hidden) &&
    (max == null || l.price <= max) &&
    (beds == null || l.beds == null || l.beds >= beds) &&
    p.flags.every((f) => (l.flags || []).includes(f)));
  const by = {
    score: (a, b) => b.score - a.score,
    price: (a, b) => a.price - b.price,
    below: (a, b) => (b.pct_below_market ?? -1e9) - (a.pct_below_market ?? -1e9),
    dom: (a, b) => (b.days_on_market || 0) - (a.days_on_market || 0),
    distance: (a, b) => (a.distance_miles ?? 1e9) - (b.distance_miles ?? 1e9),
    new: (a, b) => String(b.first_seen || "").localeCompare(String(a.first_seen || "")),
  }[p.sort] || ((a, b) => b.score - a.score);
  return rows.sort(by);
}

function card(l) {
  const s = st(l.id);
  const addr = [l.address, l.unit].filter(Boolean).join(", ") || "Address not given";
  const meta = [bedsLabel(l.beds), l.baths == null ? "? ba" : `${l.baths} ba`,
    l.sqft ? `${Math.round(l.sqft).toLocaleString()} sqft` : null,
    l.distance_miles != null ? `${l.distance_miles} mi` : null, l.source].filter(Boolean).join(" · ");
  const tags = (l.flags || []).map((f) => {
    let t = FLAGS[f] || f;
    if (f === "below_market") t += ` ${l.pct_below_market}%`;
    if (f === "price_drop") t += ` −${l.pct_price_drop}%`;
    if (f === "cheapest_site") t += ` −${money(l.cross_site_spread)}`;
    return `<span class="tag ${esc(f)}">${esc(t)}</span>`;
  });
  if (l.active === false) tags.unshift('<span class="tag gone">No longer listed</span>');
  return `<article class="card ${s.hidden ? "dim" : ""}" data-id="${esc(l.id)}">
    <div class="row1"><span class="price">${money(l.price)}</span><span class="score">score ${esc(l.score)}</span></div>
    <div class="addr">${esc(addr)}</div>
    <div class="meta">${esc(meta)}</div>
    ${tags.length ? `<div class="tags">${tags.join("")}</div>` : ""}
    <div class="card-actions">
      <button class="act ${s.favorite ? "on" : ""}" data-act="fav" aria-pressed="${!!s.favorite}">${star(s.favorite)} ${s.favorite ? "Saved" : "Save"}</button>
      <button class="act ${s.hidden ? "on" : ""}" data-act="hide" aria-pressed="${!!s.hidden}">${ICON.hide} ${s.hidden ? "Hidden" : "Hide"}</button>
      ${s.note ? `<span class="note-preview">${ICON.note.replace("<svg", '<svg width="14" height="14"')} ${esc(s.note)}</span>` : ""}
    </div>
  </article>`;
}

function renderDeals() {
  const rows = filtered();
  $("dealList").innerHTML = rows.length ? rows.map(card).join("") : `<div class="empty">${
    S.listings.size ? "Nothing matches. Loosen the filters above." : "No listings yet. They appear after the PC runs <code>py -m homefinder run</code>."}</div>`;
}

function renderSaved() {
  const rows = [...S.listings.values()].filter((l) => st(l.id).favorite)
    .sort((a, b) => (a.active === false) - (b.active === false) || b.score - a.score);
  $("savedList").innerHTML = rows.length ? rows.map(card).join("")
    : '<div class="empty">Tap ☆ Save on a listing to keep it here. Saved listings are shared with everyone using this app.</div>';
}

function markerColor(l) {
  const f = l.flags || [];
  if (f.includes("below_market") || f.includes("cheapest_site")) return "#2f7d4f";
  if (f.length) return "#2b5c9e";
  return "#8a8780";
}

function renderMap() {
  if (!window.L || !S.meta) return;
  if (!S.map) {
    const c = S.meta.center;
    S.map = L.map("map", { zoomControl: false }).setView([c.lat, c.lon], 13);
    L.control.zoom({ position: "bottomright" }).addTo(S.map);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(S.map);
    const ring = L.circle([c.lat, c.lon], { radius: c.radius_miles * 1609.34, color: "#2f6f5e", weight: 1, fillOpacity: 0.04 }).addTo(S.map);
    S.map.fitBounds(ring.getBounds());
    S.mapLayer = L.layerGroup().addTo(S.map);
  }
  setTimeout(() => S.map.invalidateSize(), 0);
  S.mapLayer.clearLayers();
  filtered().forEach((l) => {
    if (l.latitude == null || l.longitude == null) return;
    L.circleMarker([l.latitude, l.longitude], {
      radius: st(l.id).favorite ? 9 : 7, color: markerColor(l), weight: 2, fillOpacity: 0.75,
    }).on("click", () => openSheet(l.id)).addTo(S.mapLayer);
  });
}

function renderSheet(id) {
  const l = S.listings.get(id);
  if (!l) { closeSheet(); return; }
  const s = st(id);
  const url = safeUrl(l.url);
  const place = [l.city, l.state, l.zip].filter(Boolean).join(", ");
  const q = encodeURIComponent([l.address, l.unit, l.city, l.state, l.zip].filter(Boolean).join(" "));
  const mapsUrl = l.latitude != null
    ? `https://www.google.com/maps/search/?api=1&query=${l.latitude},${l.longitude}`
    : `https://www.google.com/maps/search/?api=1&query=${q}`;
  const hist = (l.history || []).slice().reverse();
  const others = (l.other_listings || []).map((o) => {
    const u = safeUrl(o.url);
    return `<div>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(o.source)}</a>` : esc(o.source)} — ${money(o.price)}</div>`;
  }).join("");
  const market = l.market_median != null
    ? `About <b>${money(l.market_median)}</b> for similar ${esc(bedsLabel(l.beds))} nearby (${esc(l.comp_count)} comps, by ${esc(l.comp_basis)}). This one is <b>${esc(l.pct_below_market)}%</b> ${l.pct_below_market >= 0 ? "below" : "above"}.`
    : `Not enough similar listings nearby to compare (${esc(l.comp_count || 0)}).`;
  const known = (arr, labels) => arr == null ? "Unknown" : (arr.length ? arr.map((x) => labels[x] || x).join(", ") : "None");
  $("sheetContent").innerHTML = `<div class="detail">
    <h2 id="sheetTitle">${money(l.price)}<span class="muted small"> /mo</span></h2>
    <div>${esc([l.address, l.unit].filter(Boolean).join(", "))} <span class="muted">${esc(place)}</span></div>
    <div class="meta">${esc([bedsLabel(l.beds), l.baths == null ? "? ba" : l.baths + " ba", l.sqft ? Math.round(l.sqft) + " sqft" : null, l.distance_miles != null ? l.distance_miles + " mi away" : null, `${l.days_on_market || 0} days listed`].filter(Boolean).join(" · "))}</div>
    ${l.active === false ? '<div class="tags"><span class="tag gone">No longer listed</span></div>' : ""}
    <div class="btnrow">
      <button class="btn ${s.favorite ? "primary" : ""}" data-act="fav">${s.favorite ? "★ Saved" : "☆ Save"}</button>
      <button class="btn" data-act="hide">${s.hidden ? "Unhide" : "Hide"}</button>
      ${url ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">Open on ${esc(l.source)}</a>` : `<a class="btn" href="https://www.google.com/search?q=${q}%20for%20rent" target="_blank" rel="noopener">Search listing</a>`}
      <a class="btn" href="${esc(mapsUrl)}" target="_blank" rel="noopener">Maps</a>
    </div>
    <div class="block"><h3>Notes (shared)</h3>
      <textarea id="noteBox" maxlength="2000" placeholder="e.g. Called, viewing Sat 2pm">${esc(s.note || "")}</textarea>
      <div id="noteStatus" class="muted small"></div>
    </div>
    <div class="block"><h3>Market</h3><div>${market}</div></div>
    ${hist.length > 1 ? `<div class="block"><h3>Price history</h3><div class="hist">${hist.map((h) => `<span class="muted">${esc(h.date)}</span><span>${money(h.price)}</span>`).join("")}</div></div>` : ""}
    ${others ? `<div class="block"><h3>Also listed on</h3>${others}</div>` : ""}
    <div class="block"><h3>Pets & amenities</h3>
      <div>Pets: ${esc(known(l.pets, PETS))}</div><div>Amenities: ${esc(known(l.amenities, AMENITIES))}</div>
    </div>
  </div>`;
  const box = $("noteBox");
  box.addEventListener("input", () => {
    $("noteStatus").textContent = "Saving…";
    clearTimeout(box._t);
    box._t = setTimeout(async () => {
      await setState(id, { note: box.value.slice(0, 2000) });
      $("noteStatus").textContent = "Saved";
    }, 700);
  });
}

function openSheet(id) {
  S.openId = id;
  renderSheet(id);
  $("sheet").hidden = false;
  history.pushState({ sheet: id }, "");
}
function closeSheet() {
  if ($("sheet").hidden) return;
  // Re-rendering would wipe a note that's still being typed; flush it first.
  const box = $("noteBox");
  if (box && box._t) { clearTimeout(box._t); setState(S.openId, { note: box.value.slice(0, 2000) }); }
  $("sheet").hidden = true;
  S.openId = null;
}

// ---------------------------------------------------------------- add listing
function renderChecks() {
  $("petChecks").innerHTML = Object.entries(PETS).map(([k, v]) =>
    `<label><input type="checkbox" name="pets" value="${k}"> ${v}</label>`).join("") +
    '<label><input type="checkbox" name="pets_none" value="1"> None allowed</label>';
  $("amenityChecks").innerHTML = Object.entries(AMENITIES).map(([k, v]) =>
    `<label><input type="checkbox" name="amenities" value="${k}"> ${v}</label>`).join("");
}

function initPickMap() {
  if (S.pickMap || !window.L || !S.meta) return;
  const c = S.meta.center;
  S.pickMap = L.map("pickMap").setView([c.lat, c.lon], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(S.pickMap);
  L.circle([c.lat, c.lon], { radius: c.radius_miles * 1609.34, color: "#2f6f5e", weight: 1, fillOpacity: 0.03 }).addTo(S.pickMap);
  S.pickMap.on("click", (e) => {
    S.pick = { lat: +e.latlng.lat.toFixed(6), lon: +e.latlng.lng.toFixed(6) };
    if (S.pickMarker) S.pickMarker.setLatLng(e.latlng);
    else S.pickMarker = L.marker(e.latlng).addTo(S.pickMap);
    $("pickInfo").textContent = `Location set (${S.pick.lat}, ${S.pick.lon}). Tap again to move it.`;
  });
}

async function submitListing(ev) {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const msg = $("addMsg");
  const price = num(f.get("price"));
  const url = (f.get("url") || "").trim();
  const address = (f.get("address") || "").trim();
  if (!price) { msg.className = "small err"; msg.textContent = "Enter the rent."; return; }
  if (!address && !url) { msg.className = "small err"; msg.textContent = "Add a link or an address."; return; }
  if (url && !safeUrl(url)) { msg.className = "small err"; msg.textContent = "Link must start with http:// or https://"; return; }
  const pets = f.get("pets_none") ? [] : f.getAll("pets");
  const amenities = f.getAll("amenities");
  const data = {
    source: f.get("source") || "other", url: url || null, price,
    address: address || null, unit: (f.get("unit") || "").trim() || null,
    zip: (f.get("zip") || "").trim() || null, beds: num(f.get("beds")), baths: num(f.get("baths")),
    sqft: num(f.get("sqft")),
    latitude: S.pick ? S.pick.lat : null, longitude: S.pick ? S.pick.lon : null,
    // Unchecked boxes mean "unknown", not "none", unless "None allowed" is ticked.
    pets: pets.length || f.get("pets_none") ? pets : null,
    amenities: amenities.length ? amenities : null,
    created_at: new Date().toISOString(), created_by: S.user.uid,
  };
  const btn = ev.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    await addDoc(collection(db, "submissions"), data);
    ev.target.reset();
    S.pick = null;
    if (S.pickMarker) { S.pickMarker.remove(); S.pickMarker = null; }
    $("pickInfo").textContent = "No location set. Distance and comps need one.";
    msg.className = "small ok";
    msg.textContent = "Added. It'll be scored on the next update from the PC.";
  } catch (e) {
    msg.className = "small err";
    msg.textContent = `Not saved: ${e.code || e.message}`;
  } finally {
    btn.disabled = false;
  }
}

function renderSubs() {
  initPickMap();
  if (S.pickMap) setTimeout(() => S.pickMap.invalidateSize(), 0);
  const listed = new Set([...S.listings.keys()]);
  $("subList").innerHTML = S.subs.length ? S.subs.map((s) => {
    const id = `${String(s.source || "phone").toLowerCase()}:${s._id}`;
    const inDeals = listed.has(id);
    const u = safeUrl(s.url);
    return `<article class="card" data-sub="${esc(s._id)}" ${inDeals ? `data-id="${esc(id)}"` : ""}>
      <div class="row1"><span class="price">${money(s.price)}</span><span class="small ${inDeals ? "score" : "muted"}">${inDeals ? "In deals" : "Waiting for PC update"}</span></div>
      <div class="addr">${esc([s.address, s.unit].filter(Boolean).join(", ") || "No address")}</div>
      <div class="meta">${esc([s.source, s.beds != null ? bedsLabel(s.beds) : null, (s.created_at || "").slice(0, 10)].filter(Boolean).join(" · "))}${u ? ` · <a href="${esc(u)}" target="_blank" rel="noopener">link</a>` : ""}</div>
      <div class="card-actions">
        <button class="act" data-sub-act="price">Update price</button>
        <button class="act" data-sub-act="delete">Remove</button>
      </div>
    </article>`;
  }).join("") : '<div class="empty">Nothing added from the phone yet.</div>';
}

async function subAction(subId, act) {
  const s = S.subs.find((x) => x._id === subId);
  if (!s) return;
  const ref = doc(db, "submissions", subId);
  try {
    if (act === "delete") {
      if (!confirm("Remove this listing for everyone?")) return;
      await deleteDoc(ref);
      toast("Removed");
    } else if (act === "price") {
      const v = num(prompt("New monthly rent:", s.price));
      if (!v || v === s.price) return;
      const now = new Date().toISOString();
      await updateDoc(ref, {
        price: v, updated_at: now,
        history: arrayUnion({ date: (s.updated_at || s.created_at || now).slice(0, 10), price: s.price }),
      });
      toast("Price updated. Drop will show after the next PC update.");
    }
  } catch (e) {
    toast(`Not saved: ${e.code || e.message}`);
  }
}

// ---------------------------------------------------------------- wiring
function setView(v) {
  S.view = v;
  document.querySelectorAll(".view").forEach((el) => (el.hidden = el.id !== `view-${v}`));
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("viewTitle").textContent = { deals: "Deals", map: "Map", saved: "Saved", add: "Add a listing" }[v];
  window.scrollTo(0, 0);
  render();
}

function initControls() {
  const p = S.prefs;
  $("fSort").value = p.sort; $("fMax").value = p.max; $("fBeds").value = p.beds;
  $("fMatch").checked = p.match; $("fHidden").checked = p.hidden;
  $("flagChips").innerHTML = Object.entries(FLAGS).map(([k, v]) =>
    `<button class="chip" data-flag="${k}" aria-pressed="${p.flags.includes(k)}">${v}</button>`).join("");
  const update = () => {
    Object.assign(p, { sort: $("fSort").value, max: $("fMax").value, beds: $("fBeds").value,
      match: $("fMatch").checked, hidden: $("fHidden").checked });
    savePrefs(); render();
  };
  ["fSort", "fMax", "fBeds", "fMatch", "fHidden"].forEach((id) => $(id).addEventListener("input", update));
  $("flagChips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-flag]"); if (!b) return;
    const f = b.dataset.flag;
    p.flags = p.flags.includes(f) ? p.flags.filter((x) => x !== f) : p.flags.concat(f);
    b.setAttribute("aria-pressed", p.flags.includes(f));
    savePrefs(); render();
  });

  document.querySelector(".tabbar").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]"); if (b) setView(b.dataset.view);
  });

  // Card clicks (deals, saved, submissions) and their action buttons.
  document.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const subBtn = e.target.closest("[data-sub-act]");
    if (subBtn) { subAction(subBtn.closest("[data-sub]").dataset.sub, subBtn.dataset.subAct); return; }
    const act = e.target.closest("[data-act]");
    const host = e.target.closest("[data-id]") || (act && act.closest("#sheet") && { dataset: { id: S.openId } });
    if (act && host) {
      const id = host.dataset.id, s = st(id);
      if (act.dataset.act === "fav") setState(id, { favorite: !s.favorite });
      if (act.dataset.act === "hide") { setState(id, { hidden: !s.hidden }); if (!s.hidden) toast("Hidden. Turn on 'Show hidden' to see it."); }
      return;
    }
    const c = e.target.closest(".card[data-id]");
    if (c && c.closest(".list")) openSheet(c.dataset.id);
  });

  $("sheetClose").addEventListener("click", () => history.back());
  $("sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") history.back(); });
  window.addEventListener("popstate", closeSheet); // Android back button closes the sheet

  $("menuBtn").addEventListener("click", () => ($("menu").hidden = !$("menu").hidden));
  $("signOutBtn").addEventListener("click", () => { $("menu").hidden = true; signOut(auth); });
  $("gateSignOut").addEventListener("click", () => signOut(auth));
  $("signInBtn").addEventListener("click", doSignIn);
  $("addForm").addEventListener("submit", submitListing);
  $("addForm").addEventListener("change", (e) => {
    if (e.target.name === "pets_none" && e.target.checked)
      document.querySelectorAll('input[name="pets"]').forEach((x) => (x.checked = false));
    if (e.target.name === "pets" && e.target.checked) document.querySelector('input[name="pets_none"]').checked = false;
  });

  // "Install" button where the browser supports it (Android Chrome).
  let installEvt = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installEvt = e; $("installBtn").hidden = false; });
  $("installBtn").addEventListener("click", async () => {
    if (!installEvt) return;
    installEvt.prompt();
    await installEvt.userChoice;
    installEvt = null; $("installBtn").hidden = true;
  });
  window.addEventListener("appinstalled", () => ($("installBtn").hidden = true));
}

// ---------------------------------------------------------------- start
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => { /* offline support only */ });
}
initControls();
renderChecks();
window.addEventListener("load", () => render()); // Leaflet (deferred) is ready by now

if (!configured) {
  showGate("Setup needed: paste your Firebase web config into app/firebase-config.js (see SETUP.md).");
} else {
  getRedirectResult(auth).catch((e) => showGate(`Sign-in failed: ${e.message}`, { signIn: true }));
  onAuthStateChanged(auth, onUser);
}
