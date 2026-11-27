package com.ictstorm.jarvisschool

import android.app.Activity
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** Three tabs: Scan (planner / studiewijzer), Jarvis (chat with link buttons), Weken (Drive folders). */
class MainActivity : Activity() {
    private val h = Handler(Looper.getMainLooper())
    private lateinit var content: FrameLayout
    private lateinit var nav: LinearLayout
    private var tab = "chat"

    // scan state
    private var pdfUri: Uri? = null
    private var pages: List<Uri> = emptyList()
    private var kind = "planner"
    private var week = localWeek()

    // chat state
    private var chatList: LinearLayout? = null
    private var chatScroll: ScrollView? = null
    private var lastId = ""
    private var sending = false
    private val poll = object : Runnable {
        override fun run() {
            if (tab == "chat") fetchNew()
            h.postDelayed(this, 5000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Ui.BG
        window.navigationBarColor = Ui.BG
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Ui.BG) }
        content = FrameLayout(this)
        root.addView(content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        nav = Ui.row(this).apply {
            setBackgroundColor(Ui.CARD)
            setPadding(0, Ui.dp(this@MainActivity, 6), 0, Ui.dp(this@MainActivity, 10))
        }
        root.addView(nav)
        setContentView(root)
        show(if (Api.hasKey(this)) "chat" else "settings")
    }

    override fun onResume() {
        super.onResume()
        h.removeCallbacks(poll)
        h.postDelayed(poll, 5000)
    }

    override fun onPause() {
        super.onPause()
        h.removeCallbacks(poll)
    }

    // ---------------------------------------------------------------- navigation
    private fun show(t: String) {
        tab = t
        nav.removeAllViews()
        for ((id, label) in listOf("scan" to "📄\nScan", "chat" to "💬\nJarvis", "weeks" to "📁\nWeken", "settings" to "⚙\nInstellen")) {
            nav.addView(TextView(this).apply {
                text = label; textSize = 13f; gravity = Gravity.CENTER
                setTextColor(if (id == t) Ui.ACCENT else Ui.MUTED)
                setPadding(0, Ui.dp(this@MainActivity, 6), 0, Ui.dp(this@MainActivity, 6))
                setOnClickListener { show(id) }
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
        }
        content.removeAllViews()
        chatList = null
        when (t) {
            "scan" -> scanScreen()
            "chat" -> chatScreen()
            "weeks" -> weeksScreen()
            else -> settingsScreen()
        }
    }

    private fun scroll(col: View) = ScrollView(this).apply { isFillViewport = true; addView(col) }

    private fun header(col: LinearLayout, title: String, sub: String) {
        col.addView(Ui.text(this, title, 28f, bold = true))
        col.addView(Ui.text(this, sub, 15f, Ui.MUTED))
    }

    private fun open(url: String) {
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            .onFailure { toast("Kan de link niet openen") }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    private fun bg(work: () -> Unit) = Thread { runCatching(work).onFailure { e -> h.post { toast(e.message ?: "Fout") } } }.start()

    // ---------------------------------------------------------------- scan
    private fun localWeek(): Int {
        val w1 = LocalDate.of(2026, 11, 9)
        val today = LocalDate.now()
        val monday = today.minusDays((today.dayOfWeek.value - 1).toLong())
        return (ChronoUnit.DAYS.between(w1, monday) / 7 + 1).toInt().coerceIn(1, 60)
    }

    private fun startScanner() {
        val opts = GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(true)
            .setPageLimit(20)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG, GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build()
        GmsDocumentScanning.getClient(opts).getStartScanIntent(this)
            .addOnSuccessListener { sender ->
                runCatching { startIntentSenderForResult(sender, SCAN, null, 0, 0, 0) }
                    .onFailure { toast("Scanner start niet: ${it.message}") }
            }
            .addOnFailureListener { toast("Scanner niet beschikbaar: ${it.message}") }
    }

    @Deprecated("Activity result for the scanner")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != SCAN || resultCode != RESULT_OK) return
        val res = GmsDocumentScanningResult.fromActivityResultIntent(data) ?: return
        pages = res.pages?.map { it.imageUri } ?: emptyList()
        pdfUri = res.pdf?.uri
        show("scan")
    }

    private fun scanScreen() {
        val col = Ui.column(this)
        header(col, "Scan", "Planner of studiewijzer, zoveel pagina's als je wil")

        col.addView(Ui.button(this, if (pages.isEmpty()) "📷  Scan pagina's" else "📷  Opnieuw scannen") { startScanner() })

        if (pages.isNotEmpty()) {
            col.addView(Ui.text(this, "${pages.size} pagina${if (pages.size == 1) "" else "'s"}", 14f, Ui.MUTED).apply {
                setPadding(0, Ui.dp(this@MainActivity, 14), 0, Ui.dp(this@MainActivity, 4))
            })
            val strip = Ui.row(this)
            for (p in pages) {
                val img = ImageView(this).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    background = Ui.bg(this@MainActivity, Ui.CARD, 8, Ui.LINE)
                    setPadding(2, 2, 2, 2)
                    layoutParams = LinearLayout.LayoutParams(Ui.dp(this@MainActivity, 84), Ui.dp(this@MainActivity, 112))
                        .apply { rightMargin = Ui.dp(this@MainActivity, 8) }
                }
                bg {
                    val o = BitmapFactory.Options().apply { inSampleSize = 8 }
                    val b = contentResolver.openInputStream(p)?.use { BitmapFactory.decodeStream(it, null, o) }
                    h.post { img.setImageBitmap(b) }
                }
                strip.addView(img)
            }
            col.addView(HorizontalScrollView(this).apply { addView(strip) })

            col.addView(Ui.text(this, "Wat is het?", 14f, Ui.MUTED).apply { setPadding(0, Ui.dp(this@MainActivity, 16), 0, 0) })
            val kinds = Ui.row(this)
            for ((k, label) in listOf("planner" to "Planner", "studiewijzer" to "Studiewijzer", "andere" to "Andere")) {
                kinds.addView(chip(label, k == kind) { kind = k; show("scan") })
            }
            col.addView(kinds)

            col.addView(Ui.text(this, "Welke week?", 14f, Ui.MUTED).apply { setPadding(0, Ui.dp(this@MainActivity, 16), 0, 0) })
            val wk = Ui.row(this)
            wk.addView(chip("−", false) { if (week > 1) { week--; show("scan") } })
            wk.addView(Ui.text(this, "  Week $week  ", 18f, bold = true))
            wk.addView(chip("+", false) { if (week < 60) { week++; show("scan") } })
            col.addView(wk)

            val status = Ui.text(this, "", 15f, Ui.ACCENT)
            col.addView(Ui.button(this, "Stuur naar Jarvis") {
                val pdf = pdfUri
                if (pdf == null) { toast("Geen PDF van de scanner, scan opnieuw"); return@button }
                status.text = "Versturen…"
                val k = kind; val w = week; val pg = pages
                bg {
                    try {
                        val r = Api.upload(this, k, w, pdf, pg)
                        h.post {
                            pages = emptyList(); pdfUri = null
                            toast("Bewaard: ${r.optJSONObject("doc")?.optString("name")}")
                            show("chat")
                        }
                    } catch (e: Exception) {
                        h.post { status.text = "Niet gelukt: ${e.message}" }
                    }
                }
            })
            col.addView(status)
            col.addView(Ui.text(this, "Jarvis bewaart het in Drive (Jarvis School → Week $week) en leest je toetsen en taken. Het antwoord komt in de chat.", 13f, Ui.MUTED))
        } else {
            col.addView(Ui.text(this, "Tip: in de scanner kan je ook foto's uit je galerij kiezen en extra pagina's toevoegen met +.", 14f, Ui.MUTED)
                .apply { setPadding(0, Ui.dp(this@MainActivity, 16), 0, 0) })
        }
        content.addView(scroll(col))
    }

    private fun chip(label: String, on: Boolean, onClick: () -> Unit) = TextView(this).apply {
        text = label; textSize = 15f
        setTextColor(if (on) Ui.ON_ACCENT else Ui.TEXT)
        background = Ui.bg(this@MainActivity, if (on) Ui.ACCENT else Ui.CARD, 12, if (on) 0 else Ui.LINE)
        setPadding(Ui.dp(this@MainActivity, 16), Ui.dp(this@MainActivity, 10), Ui.dp(this@MainActivity, 16), Ui.dp(this@MainActivity, 10))
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { rightMargin = Ui.dp(this@MainActivity, 8); topMargin = Ui.dp(this@MainActivity, 6) }
    }

    // ---------------------------------------------------------------- chat
    private fun chatScreen() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val list = Ui.column(this, 14, 12)
        list.addView(Ui.text(this, "Jarvis", 28f, bold = true).apply { setPadding(Ui.dp(this@MainActivity, 6), 0, 0, 0) })
        val sv = ScrollView(this).apply { addView(list) }
        box.addView(sv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        val input = Ui.row(this).apply { setPadding(Ui.dp(this@MainActivity, 12), Ui.dp(this@MainActivity, 8), Ui.dp(this@MainActivity, 12), Ui.dp(this@MainActivity, 8)) }
        val field = Ui.field(this, "Bericht aan Jarvis…", "", single = false).apply {
            imeOptions = EditorInfo.IME_ACTION_SEND
        }
        input.addView(Ui.wrap(field, this, 1f))
        val send = TextView(this).apply {
            text = "➤"; textSize = 22f; setTextColor(Ui.ON_ACCENT); gravity = Gravity.CENTER
            background = Ui.bg(this@MainActivity, Ui.ACCENT, 24)
            layoutParams = LinearLayout.LayoutParams(Ui.dp(this@MainActivity, 48), Ui.dp(this@MainActivity, 48))
                .apply { leftMargin = Ui.dp(this@MainActivity, 8) }
        }
        input.addView(send)
        box.addView(input)
        content.addView(box)

        chatList = list
        chatScroll = sv
        lastId = ""
        val doSend = {
            val t = field.text.toString().trim()
            if (t.isNotEmpty() && !sending) {
                sending = true
                field.setText("")
                addBubble(JSONObject().put("role", "storm").put("text", t).put("id", ""))
                val typing = addBubble(JSONObject().put("role", "jarvis").put("text", "…").put("id", ""))
                bg {
                    try {
                        Api.send(this, t)
                        h.post { list.removeView(typing); sending = false; fetchNew() }
                    } catch (e: Exception) {
                        h.post { list.removeView(typing); sending = false; toast(e.message ?: "Jarvis niet bereikbaar") }
                    }
                }
            }
        }
        send.setOnClickListener { doSend() }
        field.setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_SEND) { doSend(); true } else false }

        if (!Api.hasKey(this)) {
            addBubble(JSONObject().put("role", "jarvis").put("text", "Vul eerst het Jarvis-adres en de key in bij ⚙ Instellen.").put("id", ""))
            return
        }
        fetchNew()
    }

    private fun fetchNew() {
        val list = chatList ?: return
        if (sending) return
        val after = lastId
        bg {
            val msgs: JSONArray = Api.history(this, after)
            h.post {
                if (chatList !== list) return@post
                if (after.isEmpty()) { while (list.childCount > 1) list.removeViewAt(1) }
                for (i in 0 until msgs.length()) {
                    val m = msgs.getJSONObject(i)
                    addBubble(m)
                    lastId = m.optString("id", lastId)
                }
                if (after.isEmpty() && msgs.length() == 0) {
                    addBubble(JSONObject().put("role", "jarvis").put("id", "").put("text",
                        "Hoi Storm! Vraag me wat je moet doen, zeg wat je vergeten bent, of scan je planner bij 📄 Scan."))
                }
            }
        }
    }

    private fun addBubble(m: JSONObject): View {
        val list = chatList!!
        val mine = m.optString("role") == "storm"
        val wrap = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = if (mine) Gravity.END else Gravity.START
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = Ui.dp(this@MainActivity, 8) }
        }
        val bubble = TextView(this).apply {
            text = m.optString("text"); textSize = 16f
            setTextColor(if (mine) Ui.ON_ACCENT else Ui.TEXT)
            setTextIsSelectable(true)
            background = Ui.bg(this@MainActivity, if (mine) Ui.ACCENT else Ui.CARD, 16, if (mine) 0 else Ui.LINE)
            setPadding(Ui.dp(this@MainActivity, 14), Ui.dp(this@MainActivity, 10), Ui.dp(this@MainActivity, 14), Ui.dp(this@MainActivity, 10))
            maxWidth = (resources.displayMetrics.widthPixels * 0.82).toInt()
        }
        wrap.addView(bubble, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        val buttons = m.optJSONArray("buttons")
        if (buttons != null) {
            for (i in 0 until buttons.length()) {
                val b = buttons.getJSONObject(i)
                val url = b.optString("url")
                wrap.addView(Ui.link(this, b.optString("label")) { open(url) })
            }
        }
        list.addView(wrap)
        chatScroll?.post { chatScroll?.fullScroll(View.FOCUS_DOWN) }
        return wrap
    }

    // ---------------------------------------------------------------- weeks
    private fun weeksScreen() {
        val col = Ui.column(this)
        header(col, "Weken", "Alles wat Jarvis bewaarde, per week")
        val status = Ui.text(this, "Laden…", 15f, Ui.MUTED)
        col.addView(status)
        content.addView(scroll(col))
        if (!Api.hasKey(this)) { status.text = "Vul eerst je Jarvis key in bij ⚙ Instellen."; return }
        bg {
            try {
                val s = Api.state(this)
                h.post { fillWeeks(col, status, s) }
            } catch (e: Exception) {
                h.post { status.text = "Jarvis niet bereikbaar: ${e.message}" }
            }
        }
    }

    private fun fillWeeks(col: LinearLayout, status: TextView, s: JSONObject) {
        week = s.optInt("week", week)
        status.text = "Nu: ${s.optString("label")}" + if (!s.optBoolean("drive")) " · Drive nog niet gekoppeld (PDF's staan op de Pi)" else ""
        val up = s.optJSONArray("upcoming") ?: JSONArray()
        if (up.length() > 0) {
            val c = Ui.card(this)
            c.addView(Ui.text(this, "Binnenkort", 17f, Ui.ACCENT, bold = true))
            for (i in 0 until minOf(up.length(), 10)) {
                val it = up.getJSONObject(i)
                val tag = if (it.optString("kind") == "test") "📝" else "✅"
                val d = it.optString("date").takeIf { x -> x.isNotEmpty() && x != "null" }?.let { x -> nice(x) } ?: ""
                c.addView(Ui.text(this, "$tag ${it.optString("subject")}: ${it.optString("what")}" + if (d.isNotEmpty()) "  ·  $d" else "", 15f))
            }
            col.addView(c)
        }
        val weeks = s.optJSONArray("weeks") ?: JSONArray()
        for (i in 0 until weeks.length()) {
            val w = weeks.getJSONObject(i)
            val n = w.optInt("week")
            val c = Ui.card(this)
            c.addView(Ui.text(this, "📁  ${w.optString("folder")}", 17f, bold = true))
            val docs = w.optJSONArray("docs") ?: JSONArray()
            if (docs.length() == 0) c.addView(Ui.text(this, "Nog niets gescand", 14f, Ui.MUTED))
            var folderUrl = ""
            for (j in 0 until docs.length()) {
                val d = docs.getJSONObject(j)
                val url = d.optString("url").takeIf { it.startsWith("http") } ?: Api.fileUrl(this, n, d.optString("name"))
                if (folderUrl.isEmpty()) folderUrl = d.optString("folder_url").takeIf { it.startsWith("http") } ?: ""
                val pagesTxt = d.optInt("pages").let { p -> if (p > 0) "  ·  $p p." else "" }
                c.addView(Ui.link(this, d.optString("name") + pagesTxt) { open(url) })
            }
            val tests = w.optJSONArray("tests") ?: JSONArray()
            for (j in 0 until tests.length()) {
                val t = tests.getJSONObject(j)
                c.addView(Ui.text(this, "📝 ${t.optString("subject")}: ${t.optString("what")}", 14f, Ui.MUTED))
            }
            if (folderUrl.isNotEmpty()) c.addView(Ui.link(this, "Open map in Drive") { open(folderUrl) })
            col.addView(c)
        }
    }

    private fun nice(iso: String): String = runCatching {
        val d = LocalDate.parse(iso)
        val today = LocalDate.now()
        when (d) {
            today -> "vandaag"
            today.plusDays(1) -> "morgen"
            else -> listOf("ma", "di", "wo", "do", "vr", "za", "zo")[d.dayOfWeek.value - 1] + " ${d.dayOfMonth}/${d.monthValue}"
        }
    }.getOrDefault(iso)

    // ---------------------------------------------------------------- settings
    private fun settingsScreen() {
        val col = Ui.column(this)
        header(col, "Instellen", "Verbind de app met Jarvis op je Pi")
        col.addView(Ui.text(this, "Jarvis-adres (thuis-wifi)", 14f, Ui.MUTED).apply { setPadding(0, Ui.dp(this@MainActivity, 16), 0, 0) })
        val url = Ui.field(this, "http://192.168.0.249:8790", Api.url(this))
        col.addView(url)
        col.addView(Ui.text(this, "Jarvis key (JARVIS_KEY, onderaan de Pi-installatie)", 14f, Ui.MUTED).apply { setPadding(0, Ui.dp(this@MainActivity, 12), 0, 0) })
        val key = Ui.field(this, "JARVIS_KEY", Api.key(this))
        col.addView(key)
        val status = Ui.text(this, "", 15f, Ui.ACCENT)
        col.addView(Ui.button(this, "Opslaan en testen") {
            Api.save(this, url.text.toString(), key.text.toString())
            status.text = "Verbinden…"
            Thread {
                val msg = try { "Verbonden ✓ · " + Api.state(this).optString("label") } catch (e: Exception) { "Niet gelukt: ${e.message}" }
                h.post { status.text = msg }
            }.start()
        })
        col.addView(status)
        col.addView(Ui.text(this, "Werkt op je thuis-wifi. Buiten huis? Zet Tailscale aan en gebruik het Tailscale-adres van je Pi.", 13f, Ui.MUTED)
            .apply { setPadding(0, Ui.dp(this@MainActivity, 16), 0, 0) })
        content.addView(scroll(col))
    }

    companion object { const val SCAN = 7 }
}
