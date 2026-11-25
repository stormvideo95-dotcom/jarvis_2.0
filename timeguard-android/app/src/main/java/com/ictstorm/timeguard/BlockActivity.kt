package com.ictstorm.timeguard

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity

/** Full-screen "op slot" screen. Closes by itself once Jarvis unlocks the app. */
class BlockActivity : Activity() {
    private val h = Handler(Looper.getMainLooper())
    private var app = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        show(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        show(intent)
    }

    private fun show(i: Intent) {
        app = i.getStringExtra("app") ?: ""
        val name = Jarvis.NAMES[app] ?: app
        val col = Ui.column(this).apply { gravity = Gravity.CENTER }
        col.addView(Ui.lock(this))
        col.addView(Ui.text(this, "$name staat op slot", 28f, bold = true).apply { gravity = Gravity.CENTER })
        val left = Jarvis.remainingMin
        col.addView(Ui.text(this,
            if (left in 0.0..0.9) "Je social media tijd van vandaag is op. Morgen weer!"
            else if (left > 0) "Nog ${Ui.minutes(left)} van je ${Ui.minutes(Jarvis.limitMin.toDouble())} vandaag."
            else "Vraag het aan Jarvis.", 17f, Ui.MUTED).apply { gravity = Gravity.CENTER })
        val dmOpen = app == "instagram" && Jarvis.isOpen("instagram_dm")
        if (dmOpen) {
            col.addView(Ui.text(this, "Alleen je berichten zijn open, niet de feed of Reels.", 18f, Ui.ACCENT).apply { gravity = Gravity.CENTER })
            col.addView(Ui.button(this, "Open mijn berichten") {
                runCatching {
                    startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://www.instagram.com/direct/inbox/"))
                        .setPackage("com.instagram.android").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                finish()
            })
        } else {
            col.addView(Ui.text(this, "Zeg: \"Jarvis, unlock $name 15 minuten\"", 18f, Ui.ACCENT).apply { gravity = Gravity.CENTER })
        }
        col.addView(Ui.button(this, "Oké, terug", primary = !dmOpen) { goHome() })
        setContentView(col)
        h.removeCallbacksAndMessages(null)
        h.postDelayed(object : Runnable {
            override fun run() {
                if (Jarvis.isOpen(app)) {
                    // unlocked by voice: open the app right away
                    packageManager.getLaunchIntentForPackage(Jarvis.packages.entries.firstOrNull { it.value == app }?.key ?: "")
                        ?.let { startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    finish()
                } else {
                    // ask Jarvis now, so a voice unlock opens the app within ~2 s
                    Thread { Jarvis.refresh(this@BlockActivity) }.start()
                    h.postDelayed(this, 2000)
                }
            }
        }, 2000)
    }

    private fun goHome() {
        startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        finish()
    }

    @Deprecated("Back goes home, not back into the locked app")
    override fun onBackPressed() = goHome()

    override fun onDestroy() {
        h.removeCallbacksAndMessages(null)
        super.onDestroy()
    }
}
