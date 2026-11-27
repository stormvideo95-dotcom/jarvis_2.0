/**
 * Jarvis School → Google Drive (runs on storm.video95@gmail.com).
 * Jarvis on the Pi sends the scanned PDFs here; this saves them in
 *   My Drive / Jarvis School / Week 03 · 23–27 nov / Planner week 3.pdf
 * Setup: see README.md in this folder. Change SECRET to the DRIVE_SECRET in the Pi's .env.
 */
const SECRET = 'PLAK-HIER-JE-DRIVE_SECRET';
const ROOT = 'Jarvis School';

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out({ ok: false, error: 'bad json' }); }
  if (!SECRET || SECRET.indexOf('PLAK-HIER') === 0 || body.secret !== SECRET) return out({ ok: false, error: 'wrong secret' });

  const root = folder(DriveApp.getRootFolder(), ROOT);
  if (body.action === 'ping') return out({ ok: true, url: root.getUrl() });
  if (body.action !== 'save') return out({ ok: false, error: 'unknown action' });

  const name = String(body.name || 'Document.pdf').replace(/[\\/]/g, '-').slice(0, 120);
  const week = folder(root, String(body.folder || 'Zonder week').slice(0, 80));
  const old = week.getFilesByName(name);          // a new scan replaces the old one
  while (old.hasNext()) old.next().setTrashed(true);
  const blob = Utilities.newBlob(Utilities.base64Decode(body.data), body.mime || 'application/pdf', name);
  const file = week.createFile(blob);
  return out({ ok: true, url: file.getUrl(), folderUrl: week.getUrl(), id: file.getId() });
}

function folder(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/** Run this once from the editor so Google asks for Drive permission. */
function test() {
  Logger.log(folder(DriveApp.getRootFolder(), ROOT).getUrl());
}
