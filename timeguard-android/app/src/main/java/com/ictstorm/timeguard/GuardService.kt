package com.ictstorm.timeguard

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.PowerManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Sees which app is in front. A guarded app that Jarvis didn't unlock -> home + lock screen.
 * Time in unlocked apps is counted and sent to Jarvis (YouTube: Shorts vs long videos).
 */
class GuardService : AccessibilityService() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var net: Handler
    private var currentPkg = ""
    private var currentApp: String? = null
    private var inShorts = false
    private var lastShortsCheck = 0L
    private var lastTick = 0L
    private val usage = HashMap<Pair<String, Boolean>, Double>()
    private var lastReport = 0L
    private var lastBlock = 0L
    private var dmOnly = false          // Instagram opened with only "messages" unlocked
    private var lastDmSeen = 0L

    private val IGNORE = setOf("com.android.systemui", "com.ictstorm.timeguard", "android",
        "com.google.android.apps.nexuslauncher", "com.android.launcher3")

    override fun onServiceConnected() {
        val t = HandlerThread("timeguard-net").apply { start() }
        net = Handler(t.looper)
        Jarvis.loadCached(this)
        net.post { Jarvis.refresh(this) }
        lastTick = System.currentTimeMillis()
        main.post(tick)
    }

    private val tick = object : Runnable {
        override fun run() {
            val now = System.currentTimeMillis()
            val dt = (now - lastTick) / 1000.0
            lastTick = now
            val screenOn = (getSystemService(POWER_SERVICE) as PowerManager).isInteractive
            val app = currentApp
            if (app == "instagram" && screenOn && !Jarvis.isOpen("instagram") && Jarvis.isOpen("instagram_dm")) {
                if (now - lastDmSeen > 5000) block("instagram")     // left the messages for the feed/Reels
                else if (dt in 0.0..30.0) usage["instagram_dm" to false] = (usage["instagram_dm" to false] ?: 0.0) + dt
            } else if (app != null && screenOn) {
                if (Jarvis.isOpen(app)) {
                    if (dt in 0.0..30.0) {
                        val k = app to (app == "youtube" && inShorts)
                        usage[k] = (usage[k] ?: 0.0) + dt
                    }
                } else {
                    block(app)       // unlock ran out while using it
                }
            }
            if (now - lastReport > 30_000) {
                lastReport = now
                val batch = HashMap(usage)
                usage.clear()
                net.post {
                    val ok = if (batch.isEmpty()) Jarvis.refresh(this@GuardService) else Jarvis.report(this@GuardService, batch)
                    if (!ok && batch.isNotEmpty()) main.post { batch.forEach { (k, v) -> usage[k] = (usage[k] ?: 0.0) + v } }
                }
            } else if (now - Jarvis.lastOk > 15_000) {
                net.post { Jarvis.refresh(this@GuardService) }
            }
            main.postDelayed(this, 5000)
        }
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        e ?: return
        val pkg = e.packageName?.toString() ?: return
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            if (pkg in IGNORE && pkg != "com.ictstorm.timeguard") {
                if (pkg != "com.android.systemui") { currentPkg = pkg; currentApp = null }
                return
            }
            currentPkg = pkg
            currentApp = Jarvis.packages[pkg]
            inShorts = false
            val a = currentApp
            if (a == "instagram" && !Jarvis.isOpen("instagram") && Jarvis.isOpen("instagram_dm")) {
                if (!dmOnly) openDmInbox()
                dmOnly = true
                lastDmSeen = System.currentTimeMillis()
            } else {
                dmOnly = false
                a?.let { if (!Jarvis.isOpen(it)) block(it) }
            }
        }
        if (pkg == currentPkg && currentApp == "instagram" && dmOnly) {
            val now = System.currentTimeMillis()
            if (now - lastShortsCheck > 1000) {
                lastShortsCheck = now
                if (onDirectScreen()) lastDmSeen = now
            }
        }
        if (pkg == currentPkg && currentApp == "youtube") {
            val now = System.currentTimeMillis()
            if (now - lastShortsCheck > 2000) {
                lastShortsCheck = now
                inShorts = detectShorts()
            }
        }
    }

    private fun detectShorts(): Boolean {
        val root = rootInActiveWindow ?: return false
        return try {
            listOf("reel_player_page_container", "reel_recycler", "reel_watch_player", "shorts_container")
                .any { id -> root.findAccessibilityNodeInfosByViewId("com.google.android.youtube:id/$id").isNotEmpty() }
        } catch (_: Exception) { false }
    }

    /** Instagram's Direct (messages) screens have view ids with "direct" or "thread" in them. */
    private fun onDirectScreen(): Boolean {
        val root = rootInActiveWindow ?: return false
        val ids = listOf("direct_inbox_container", "row_inbox_container", "direct_thread_container",
            "thread_message_list", "row_thread_composer_edittext", "direct_thread_title", "inbox_refreshable_thread_list_recyclerview")
        return try {
            ids.any { root.findAccessibilityNodeInfosByViewId("com.instagram.android:id/$it").isNotEmpty() } || hasDirectId(root, 0)
        } catch (_: Exception) { false }
    }

    private fun hasDirectId(n: AccessibilityNodeInfo?, depth: Int): Boolean {
        if (n == null || depth > 7) return false
        val id = n.viewIdResourceName ?: ""
        if (id.startsWith("com.instagram.android:id/") && (id.contains("direct_") || id.contains("thread_"))) return true
        for (i in 0 until minOf(n.childCount, 30)) if (hasDirectId(n.getChild(i), depth + 1)) return true
        return false
    }

    private fun openDmInbox() {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://www.instagram.com/direct/inbox/"))
                .setPackage("com.instagram.android").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) { }
    }

    private fun block(app: String) {
        val now = System.currentTimeMillis()
        if (now - lastBlock < 1500) return
        lastBlock = now
        performGlobalAction(GLOBAL_ACTION_HOME)
        startActivity(Intent(this, BlockActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("app", app))
        currentApp = null
        dmOnly = false
    }

    override fun onInterrupt() {}
}
