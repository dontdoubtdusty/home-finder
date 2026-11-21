# Phone app setup

The phone app is an installable web app hosted free on GitHub Pages. Listing data
and shared favorites/notes live in a free Firebase project. Your PC fetches
listings (your RentCast key never leaves it) and pushes the results to Firebase.

```
 PC (daily)                       Firebase (Firestore)              Phones
 RentCast + CSV + phone adds  ->  listings, meta          <-  read    Home Finder app
 score, match across sites        state (saved/hidden/notes) <-> read/write
                              <-  submissions (added on phone)
```

Sign-in is with Google. Only email addresses you add with
`py -m homefinder allow EMAIL` can see anything.

Takes about 20 minutes, once.

## 1. Create the Firebase project

1. Go to https://console.firebase.google.com and **Create a project** (e.g. `home-finder`).
   Google Analytics isn't needed.
2. **Build > Authentication > Get started > Sign-in method > Google > Enable**, pick a
   support email, and save.
3. **Authentication > Settings > Authorized domains > Add domain**:
   `dontdoubtdusty.github.io`
4. **Build > Firestore Database > Create database**, choose a location near you,
   and start in **production mode**.
5. **Firestore Database > Rules**: replace everything with the contents of
   [`firebase/firestore.rules`](firebase/firestore.rules) and **Publish**.

## 2. Connect the app (web config)

1. **Project settings** (gear icon) **> General > Your apps > Add app > Web (`</>`)**.
   Name it `Home Finder`. Leave Firebase Hosting unchecked.
2. Copy the `firebaseConfig` values into [`app/firebase-config.js`](app/firebase-config.js).
   These values are meant to be public. The security rules protect the data.

## 3. Connect the PC (service account)

1. **Project settings > Service accounts > Generate new private key**.
2. Save the file as `secrets/firebase-service-account.json` in this folder.
   `secrets/` is git-ignored. **Never commit or share this file**, because it has full access.
3. In `config.yaml`:
   ```yaml
   firebase:
     enabled: true
   ```
4. Install the library: `py -m pip install -r requirements.txt`
5. Allow yourself and the other person (their Google account email):
   ```powershell
   py -m homefinder allow you@gmail.com
   py -m homefinder allow them@gmail.com
   py -m homefinder allowed
   ```
6. First upload: `py -m homefinder run`

## 4. Publish the app on GitHub Pages

1. On GitHub: **repo Settings > Pages > Build and deployment > Source: GitHub Actions**.
2. Commit and push. The `Deploy phone app` workflow publishes `app/` to
   **https://dontdoubtdusty.github.io/home-finder/**

The repo is public, but only app code is in it. Your search location, the
listings, notes and keys are in Firebase or on your PC.

## 5. Install on Android

1. Open https://dontdoubtdusty.github.io/home-finder/ in **Chrome**.
2. **Sign in with Google**, using an email you allowed.
3. Tap **Install** at the top, or open Chrome's **⋮ menu > Install app** (or *Add to Home screen*).

It opens full-screen from its own icon, like any other app. It also works on
iPhone: open it in Safari, then **Share > Add to Home Screen**.

## 6. Update automatically every day

The app only gets new listings when the PC runs. To run daily at 8am:

```powershell
schtasks /Create /SC DAILY /ST 08:00 /TN "Home Finder" /TR "\"D:\My Documents\rpret\GitHub\home-finder\scripts\run-daily.bat\""
```

Then in **Task Scheduler > Home Finder > Properties > Settings**, tick **Run task
as soon as possible after a scheduled start is missed**, so it catches up if the PC
was off. Output goes to `data/run.log`.

Listings added on a phone are scored on the next run. To pick them up sooner,
run `py -m homefinder run`, or `py -m homefinder sync` (which makes no RentCast call
but doesn't pull phone adds). Running `run` more than once a day uses extra RentCast
requests.

## Limits (Firebase free "Spark" plan)

50,000 reads, 20,000 writes per day, 1 GB stored. A daily run writes at most a few
hundred listings, and each app open reads them once. That's far under the limits
for a couple of people.

## Troubleshooting

| Problem | Fix |
|---|---|
| "isn't on the list yet" | `py -m homefinder allow THEIR_EMAIL` (exactly the Google account they signed in with) |
| Sign-in popup fails / `auth/unauthorized-domain` | Step 1.3: add `dontdoubtdusty.github.io` to Authorized domains |
| "Setup needed" screen | Step 2: `app/firebase-config.js` still has `REPLACE_ME` values |
| `permission-denied` in the app | Rules not published (step 1.5) |
| PC: service account key not found | Step 3.2: check the file path |
| App shows old data | Check `data/run.log`; the "updated" time in the app header shows the last sync |
