# Jarvis School → Google Drive

Jarvis puts every scan in **My Drive → Jarvis School → Week 03 · 23–27 nov**. It does that through a tiny
Google Apps Script on your own account (storm.video95@gmail.com), so no Google Cloud project or passwords on the Pi.

1. Go to **script.google.com** (logged in as storm.video95@gmail.com) → **New project**, name it *Jarvis School*.
2. Delete what's there and paste everything from [`Code.gs`](Code.gs).
3. On the Pi, get your secret: `grep DRIVE_SECRET ~/jarvis/.env` (the Pi install makes one).
   Put it in `const SECRET = '...'` at the top. Save (Ctrl/Cmd+S).
4. Pick the function **test** at the top and press **Run**. Google asks for permission → your account →
   *Advanced* → *Go to Jarvis School (unsafe)* → *Allow*. (It's your own script, that warning is normal.)
5. **Deploy → New deployment** → gear → **Web app**. *Execute as:* **Me**. *Who has access:* **Anyone**. → **Deploy**.
6. Copy the **Web app URL** (ends in `/exec`) and run the Pi install again; paste it when it asks.

"Anyone" only means anyone with the long secret URL **and** the secret can save a PDF into that one folder.
It can't read or delete your other files.
