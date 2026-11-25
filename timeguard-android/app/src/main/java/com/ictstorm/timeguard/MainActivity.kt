package com.ictstorm.timeguard

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.widget.ScrollView

/** Setup + status: Jarvis address and key, and the switch to turn the guard on. */
class MainActivity : Activity() {
    private val h = Handler(Looper.getMainLooper())

    override fun onResume() {
        super.onResume()
        build()
    }

    private fun serviceOn(): Boolean {
        val list = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
        return TextUtils.SimpleStringSplitter(':').apply { setString(list) }
            .any { it.contains("com.ictstorm.timeguard/") }
    }

    private fun build() {
        val col = Ui.column(this)
        col.addView(Ui.lock(this))
        col.addView(Ui.text(this, "TimeGuard", 30f, bold = true))
        val status = Ui.text(this, "…", 16f, Ui.MUTED)
        col.addView(status)

        if (!serviceOn()) {
            col.addView(Ui.text(this, "Stap 1: zet TimeGuard aan bij Toegankelijkheid. Android vraagt dat zodat TimeGuard ziet welke app open is.", 15f, Ui.ACCENT))
            col.addView(Ui.button(this, "Open Toegankelijkheid") {
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            })
        } else {
            col.addView(Ui.text(this, "✓ TimeGuard staat aan", 16f, Ui.ACCENT))
        }

        col.addView(Ui.text(this, "Jarvis-adres", 14f, Ui.MUTED))
        val url = Ui.field(this, "http://192.168.0.249:8790", Jarvis.url(this))
        col.addView(url)
        col.addView(Ui.text(this, "Jarvis key (onderaan de Pi-installatie)", 14f, Ui.MUTED))
        val key = Ui.field(this, "JARVIS_KEY", Jarvis.key(this))
        col.addView(key)
        col.addView(Ui.button(this, "Opslaan en testen") {
            Jarvis.save(this, url.text.toString(), key.text.toString())
            status.text = "Verbinden…"
            Thread {
                val ok = Jarvis.refresh(this)
                h.post { status.text = describe(ok) }
            }.start()
        })
        col.addView(Ui.text(this, "Openen gaat alleen via Jarvis: \"Jarvis, unlock WhatsApp 15 minuten\".", 14f, Ui.MUTED))

        setContentView(ScrollView(this).apply { setBackgroundColor(Ui.BG); addView(col) })
        Thread {
            val ok = Jarvis.refresh(this)
            h.post { status.text = describe(ok) }
        }.start()
    }

    private fun describe(ok: Boolean): String {
        if (!ok) return "Jarvis niet bereikbaar: ${Jarvis.lastError}"
        if (!Jarvis.enabled) return "Verbonden ✓ · TimeGuard staat uit op Jarvis"
        val open = Jarvis.grants.keys.filter { Jarvis.isOpen(it) }.joinToString { Jarvis.NAMES[it] ?: it }
        return "Verbonden ✓ · nog ${Ui.minutes(Jarvis.remainingMin)} van ${Ui.minutes(Jarvis.limitMin.toDouble())}" +
            if (open.isNotEmpty()) " · open: $open" else " · alles op slot"
    }
}
