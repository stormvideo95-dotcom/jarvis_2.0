// TimeGuard for Mac — menu-bar app that keeps social media sites locked until Jarvis opens them.
//
// - Every 2 s it reads the URL of the front browser tab (Safari, Chrome, Arc, Edge, Brave).
// - A guarded site that Jarvis didn't unlock -> the tab goes to Jarvis' "op slot" page.
// - Time on unlocked sites is sent to Jarvis. YouTube: /shorts/ counts full, other videos half.
// - instagram.com/direct (messages) works with the "only my Instagram messages" unlock.
// - Built by GitHub Actions (no Xcode needed).

import AppKit
import ServiceManagement

let defaults = UserDefaults.standard
var jarvisURL: String { (defaults.string(forKey: "url") ?? "http://192.168.0.249:8790").trimmingCharacters(in: CharacterSet(charactersIn: "/ ")) }
var jarvisKey: String { defaults.string(forKey: "key") ?? "" }

struct Browser { let bundle: String; let name: String; let safari: Bool }
let browsers = [
    Browser(bundle: "com.apple.Safari", name: "Safari", safari: true),
    Browser(bundle: "com.google.Chrome", name: "Google Chrome", safari: false),
    Browser(bundle: "company.thebrowser.Browser", name: "Arc", safari: false),
    Browser(bundle: "com.microsoft.edgemac", name: "Microsoft Edge", safari: false),
    Browser(bundle: "com.brave.Browser", name: "Brave Browser", safari: false),
]

// site -> app id (Jarvis sends the real list; this is the fallback)
var sites: [String: String] = [
    "web.whatsapp.com": "whatsapp", "instagram.com": "instagram", "threads.net": "instagram",
    "tiktok.com": "tiktok", "snapchat.com": "snapchat", "youtube.com": "youtube", "youtu.be": "youtube",
    "reddit.com": "reddit", "x.com": "x", "twitter.com": "x", "facebook.com": "facebook",
]
let nativeApps = ["net.whatsapp.WhatsApp": "whatsapp", "desktop.WhatsApp": "whatsapp"]

final class Guard: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var grants: [String: Double] = [:]
    var enabled = true
    var remaining: Double = -1
    var limit = 120
    var lastOK = Date.distantPast
    var offset: Double = 0            // Jarvis clock minus Mac clock
    var checking = false
    var lastError = ""
    var usage: [String: Double] = [:]      // "app|shorts" -> seconds
    var lastTick = Date()
    var lastReport = Date()
    let statusLine = NSMenuItem(title: "…", action: nil, keyEquivalent: "")

    func applicationDidFinishLaunching(_ n: Notification) {
        if let cached = defaults.dictionary(forKey: "grants") as? [String: Double] { grants = cached }
        buildMenu()
        if jarvisKey.isEmpty { askSettings() }
        refresh()
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in self.tick() }
        Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { _ in self.syncWithJarvis() }
    }

    // ---- menu -----------------------------------------------------------------
    func buildMenu() {
        let m = NSMenu()
        m.addItem(statusLine)
        m.addItem(.separator())
        m.addItem(NSMenuItem(title: "Open Jarvis-pagina", action: #selector(openJarvis), keyEquivalent: "j"))
        m.addItem(NSMenuItem(title: "Instellingen…", action: #selector(askSettings), keyEquivalent: ","))
        let login = NSMenuItem(title: "Start bij inloggen", action: #selector(toggleLogin), keyEquivalent: "")
        if #available(macOS 13.0, *) { login.state = SMAppService.mainApp.status == .enabled ? .on : .off }
        m.addItem(login)
        m.addItem(.separator())
        m.addItem(NSMenuItem(title: "Stop TimeGuard", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        for i in m.items { i.target = i.action == #selector(NSApplication.terminate(_:)) ? NSApp : self }
        item.menu = m
        updateTitle()
    }

    func updateTitle() {
        let mins = Int(max(0, remaining))
        let txt = !enabled ? "🔓" : remaining < 0 ? "🔒" : String(format: "🔒 %d:%02d", mins / 60, mins % 60)
        item.button?.title = txt
        let now = Date().timeIntervalSince1970 + offset
        let open = grants.filter { $0.value > now }.map { "\($0.key) \(Int(($0.value - now) / 60)) min" }
        statusLine.title = !enabled ? "TimeGuard staat uit op Jarvis"
            : Date().timeIntervalSince(lastOK) > 60 ? "Jarvis niet bereikbaar \(lastError.isEmpty ? "" : "(\(lastError))")"
            : "Nog \(mins) van \(limit) min · open: \(open.isEmpty ? "niets" : open.joined(separator: ", "))"
    }

    @objc func openJarvis() { NSWorkspace.shared.open(URL(string: jarvisURL)!) }

    @objc func toggleLogin(_ sender: NSMenuItem) {
        guard #available(macOS 13.0, *) else { return }
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister(); sender.state = .off }
            else { try SMAppService.mainApp.register(); sender.state = .on }
        } catch { alert("Lukt niet: \(error.localizedDescription)") }
    }

    @objc func askSettings() {
        let a = NSAlert()
        a.messageText = "TimeGuard koppelen aan Jarvis"
        a.informativeText = "Het adres van Jarvis op je Pi en de Jarvis key (staat onderaan de Pi-installatie)."
        let box = NSStackView(frame: NSRect(x: 0, y: 0, width: 320, height: 60))
        box.orientation = .vertical
        let u = NSTextField(string: jarvisURL); u.placeholderString = "http://192.168.0.249:8790"
        let k = NSTextField(string: jarvisKey); k.placeholderString = "Jarvis key"
        u.frame.size.width = 320; k.frame.size.width = 320
        box.addArrangedSubview(u); box.addArrangedSubview(k)
        a.accessoryView = box
        a.addButton(withTitle: "Opslaan"); a.addButton(withTitle: "Annuleren")
        NSApp.activate(ignoringOtherApps: true)
        if a.runModal() == .alertFirstButtonReturn {
            defaults.set(u.stringValue, forKey: "url")
            defaults.set(k.stringValue, forKey: "key")
            refresh()
        }
    }

    func alert(_ s: String) { let a = NSAlert(); a.messageText = s; NSApp.activate(ignoringOtherApps: true); a.runModal() }

    // ---- Jarvis -------------------------------------------------------------
    func request(_ path: String, body: [String: Any]? = nil, done: @escaping ([String: Any]?) -> Void) {
        guard let url = URL(string: jarvisURL + path) else { return done(nil) }
        var r = URLRequest(url: url, timeoutInterval: 8)
        r.setValue(jarvisKey, forHTTPHeaderField: "X-Jarvis-Key")
        if let b = body {
            r.httpMethod = "POST"
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: b)
        }
        URLSession.shared.dataTask(with: r) { data, resp, err in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? nil
            DispatchQueue.main.async {
                if code == 200, let j = json { self.apply(j); done(j) }
                else { self.lastError = code == 401 ? "verkeerde key" : (err?.localizedDescription ?? "HTTP \(code)"); self.updateTitle(); done(nil) }
            }
        }.resume()
    }

    func apply(_ s: [String: Any]) {
        enabled = s["enabled"] as? Bool ?? true
        remaining = s["remaining_min"] as? Double ?? -1
        limit = s["limit_min"] as? Int ?? 120
        if let n = (s["now"] as? NSNumber)?.doubleValue { offset = n - Date().timeIntervalSince1970 }
        grants = (s["grants"] as? [String: Any] ?? [:]).compactMapValues { ($0 as? NSNumber)?.doubleValue }
        defaults.set(grants, forKey: "grants")
        if let apps = s["apps"] as? [String: Any] {
            var m: [String: String] = [:]
            for (id, v) in apps { for site in ((v as? [String: Any])?["sites"] as? [String] ?? []) { m[site] = id } }
            if !m.isEmpty { sites = m }
        }
        lastOK = Date(); lastError = ""
        updateTitle()
    }

    func refresh() { request("/api/guard/status?device=mac") { _ in } }

    func syncWithJarvis() {
        if usage.isEmpty || Date().timeIntervalSince(lastReport) < 30 { refresh(); return }
        let batch = usage; usage = [:]; lastReport = Date()
        let items: [[String: Any]] = batch.map { k, v in
            let p = k.split(separator: "|"); return ["app": String(p[0]), "shorts": p.count > 1 && p[1] == "1", "seconds": v]
        }
        request("/api/guard/usage", body: ["device": "mac", "items": items]) { ok in
            if ok == nil { for (k, v) in batch { self.usage[k, default: 0] += v } }   // try again later
        }
    }

    func isOpen(_ app: String) -> Bool {
        if !enabled { return true }
        let now = Date().timeIntervalSince1970 + offset
        return (grants[app] ?? 0) > now || (grants["all"] ?? 0) > now
    }

    // ---- watching -----------------------------------------------------------
    func tick() {
        let dt = Date().timeIntervalSince(lastTick); lastTick = Date()
        updateTitle()
        guard let front = NSWorkspace.shared.frontmostApplication, let bundle = front.bundleIdentifier else { return }
        if let app = nativeApps[bundle] {                         // WhatsApp desktop app
            if isOpen(app) { count(app, shorts: false, dt) } else if freshOrCheck() { front.hide(); showBlocked(app: app, back: nil) }
            return
        }
        guard let b = browsers.first(where: { $0.bundle == bundle }), let url = currentURL(b),
              let comps = URLComponents(string: url), let host = comps.host?.lowercased() else { return }
        let path = comps.path.lowercased()
        if url.hasPrefix(jarvisURL) { return }
        guard let app = siteApp(host: host, path: path) else { return }
        if app == "instagram" && path.hasPrefix("/direct") && isOpen("instagram_dm") && !isOpen("instagram") {
            count("instagram_dm", shorts: false, dt); return
        }
        if isOpen(app) {
            count(app, shorts: app == "youtube" && path.hasPrefix("/shorts"), dt)
        } else if freshOrCheck() {
            let enc = url.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            setURL(b, "\(jarvisURL)/guard/blocked?app=\(app)&back=\(enc)")
        }
    }

    /// True when the last answer from Jarvis is recent enough to lock on. Otherwise ask Jarvis first
    /// and decide on the next tick — so a fresh voice unlock never bounces between open and locked.
    func freshOrCheck() -> Bool {
        if Date().timeIntervalSince(lastOK) < 3 || Date().timeIntervalSince(lastOK) > 60 { return true }
        if !checking { checking = true; request("/api/guard/status?device=mac") { _ in self.checking = false } }
        return false
    }

    func siteApp(host: String, path: String) -> String? {
        for (site, app) in sites where app != "instagram_dm" {
            if host == site || host.hasSuffix("." + site) { return app }
        }
        return nil
    }

    func count(_ app: String, shorts: Bool, _ dt: TimeInterval) {
        guard dt > 0 && dt < 30 else { return }
        usage["\(app)|\(shorts ? 1 : 0)", default: 0] += dt
    }

    func showBlocked(app: String, back: String?) {
        if let u = URL(string: "\(jarvisURL)/guard/blocked?app=\(app)") { NSWorkspace.shared.open(u) }
    }

    func runScript(_ src: String) -> String? {
        var err: NSDictionary?
        let out = NSAppleScript(source: src)?.executeAndReturnError(&err)
        return err == nil ? out?.stringValue : nil
    }

    func currentURL(_ b: Browser) -> String? {
        b.safari ? runScript("tell application \"Safari\" to return URL of front document")
                 : runScript("tell application \"\(b.name)\" to return URL of active tab of front window")
    }

    func setURL(_ b: Browser, _ url: String) {
        let u = url.replacingOccurrences(of: "\"", with: "%22")
        _ = b.safari ? runScript("tell application \"Safari\" to set URL of front document to \"\(u)\"")
                     : runScript("tell application \"\(b.name)\" to set URL of active tab of front window to \"\(u)\"")
    }
}

let app = NSApplication.shared
let delegate = Guard()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
