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

/** Tabs: Jarvis (chat with link buttons), Scan (planner / studiewijzer), Weken (Drive folders), Instellen. */
class MainActivity : Activity() {
    private val h = Handler(Looper.getMainLooper())
    private lateinit var content: FrameLayout
    private lateinit var nav: LinearLayout
    private var tab = "chat"
    private var weekLabel = ""

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

    private fun dp(v: Int) = Ui.dp(this, v)

    @Suppress("DEPRECATION")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Ui.BG
        window.navigationBarColor = Ui.WHITE
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(Ui.BG) }
        content = FrameLayout(this)
        root.addView(content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        nav = Ui.row(this).apply {
            background = Ui.shape(this@MainActivity, Ui.WHITE, 0)
            setPadding(0, dp(8), 0, dp(8))
            elevation = dp(8).toFloat()
        }
        root.addView(nav)
        setContentView(root)
        show(if (Api.hasKey(this)) "chat" else "settings")
        if (Api.hasKey(this)) bg { val s = Api.state(this); h.post { week = s.optInt("week", week); weekLabel = s.optString("label") } }
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
        val items = listOf(Triple("chat", "Jarvis", R.drawable.ic_chat), Triple("scan", "Scan", R.drawable.ic_doc),
            Triple("weeks", "Weken", R.drawable.ic_folder), Triple("settings", "Instellen", R.drawable.ic_tune))
        for ((id, label, res) in items) {
            val on = id == t
            nav.addView(LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
                addView(Ui.icon(this@MainActivity, res, if (on) Ui.BLUE_DARK else Ui.MUTED, 24))
                addView(Ui.text(this@MainActivity, label, 12f, if (on) Ui.BLACK else Ui.MUTED, bold = on).apply {
                    setPadding(0, dp(2), 0, 0)
                })
                addView(View(this@MainActivity).apply {
                    background = Ui.circle(if (on) Ui.BLUE_DARK else 0, this@MainActivity)
                    layoutParams = LinearLayout.LayoutParams(dp(5), dp(5)).apply { topMargin = dp(3) }
                })
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

    /** "Hoi, Storm" header with the logo and a settings button. */
    private fun header(col: LinearLayout, sub: String) {
        val r = Ui.row(this).apply { setPadding(0, dp(6), 0, dp(4)) }
        r.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_school)
            layoutParams = LinearLayout.LayoutParams(dp(50), dp(50)).apply { rightMargin = dp(12) }
        })
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        t.addView(Ui.text(this, "Hoi, Storm", 20f, bold = true))
        t.addView(Ui.text(this, sub, 13f, Ui.MUTED))
        r.addView(t, Ui.lp(0, weight = 1f))
        r.addView(Ui.roundButton(this, R.drawable.ic_tune) { show("settings") })
        col.addView(r)
    }

    private fun title(col: LinearLayout, s: String) =
        col.addView(Ui.text(this, s, 18f, bold = true).apply { setPadding(0, dp(22), 0, 0) })

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
        header(col, weekLabel.ifEmpty { "Week $week" })

        val hero = Ui.card(this, Ui.BLUE, 32).apply { setPadding(dp(22), dp(22), dp(22), dp(22)) }
        val top = Ui.row(this)
        top.addView(Ui.roundButton(this, R.drawable.ic_doc) { startScanner() })
        top.addView(Ui.spacer(this))
        top.addView(TextView(this).apply {
            text = if (pages.isEmpty()) "0" else "${pages.size}"; textSize = 15f; typeface = Ui.MEDIUM
            setTextColor(Ui.BLACK); gravity = Gravity.CENTER
            background = Ui.circle(0, this@MainActivity, Ui.BLACK)
            layoutParams = LinearLayout.LayoutParams(dp(48), dp(48))
        })
        hero.addView(top)
        hero.addView(Ui.text(this, "Scan je planner\nen studiewijzer", 26f, Ui.BLACK, bold = true).apply { setPadding(0, dp(18), 0, 0) })
        hero.addView(Ui.text(this, "Zoveel pagina's als je wil, of kies foto's uit je galerij", 14f, 0xFF3A3F55.toInt()).apply { setPadding(0, dp(6), 0, 0) })
        hero.addView(Ui.pill(this, if (pages.isEmpty()) "SCAN PAGINA'S" else "OPNIEUW SCANNEN") { startScanner() })
        col.addView(hero)

        if (pages.isNotEmpty()) {
            title(col, "${pages.size} pagina${if (pages.size == 1) "" else "'s"}")
            val strip = Ui.row(this).apply { setPadding(0, dp(10), 0, 0) }
            for (p in pages) {
                val img = ImageView(this).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    clipToOutline = true
                    background = Ui.shape(this@MainActivity, Ui.WHITE, 16, Ui.LINE)
                    layoutParams = LinearLayout.LayoutParams(dp(92), dp(124)).apply { rightMargin = dp(10) }
                }
                bg {
                    val o = BitmapFactory.Options().apply { inSampleSize = 8 }
                    val b = contentResolver.openInputStream(p)?.use { BitmapFactory.decodeStream(it, null, o) }
                    h.post { img.setImageBitmap(b) }
                }
                strip.addView(img)
            }
            col.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(strip) })

            title(col, "Wat is het?")
            val kinds = Ui.row(this)
            for ((k, label) in listOf("planner" to "Planner", "studiewijzer" to "Studiewijzer", "andere" to "Andere")) {
                kinds.addView(Ui.chip(this, label, k == kind) { kind = k; show("scan") })
            }
            col.addView(kinds)

            title(col, "Welke week?")
            val wk = Ui.row(this).apply {
                background = Ui.shape(this@MainActivity, Ui.WHITE, 32, Ui.LINE)
                setPadding(dp(8), dp(8), dp(8), dp(8))
                layoutParams = Ui.lp(top = dp(10))
            }
            wk.addView(Ui.roundButton(this, R.drawable.ic_minus, size = 44) { if (week > 1) { week--; show("scan") } })
            wk.addView(Ui.text(this, "Week $week", 18f, bold = true).apply { gravity = Gravity.CENTER }, Ui.lp(0, weight = 1f))
            wk.addView(Ui.roundButton(this, R.drawable.ic_plus, size = 44) { if (week < 60) { week++; show("scan") } })
            col.addView(wk)

            val status = Ui.text(this, "", 14f, Ui.BLUE_DARK).apply { setPadding(0, dp(8), 0, 0) }
            col.addView(Ui.pill(this, "STUUR NAAR JARVIS", full = true) {
                val pdf = pdfUri
                if (pdf == null) { toast("Geen PDF van de scanner, scan opnieuw"); return@pill }
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
            col.addView(Ui.text(this, "Jarvis bewaart het in Drive (Jarvis School → Week $week) en leest je toetsen en taken. Het antwoord komt in de chat.", 13f, Ui.MUTED)
                .apply { setPadding(0, dp(6), 0, 0) })
        }
        content.addView(scroll(col))
    }

    // ---------------------------------------------------------------- chat
    private fun chatScreen() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val list = Ui.column(this, 16, 8)

        // top bar
        val bar = Ui.row(this).apply { setPadding(0, dp(6), 0, dp(4)) }
        bar.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_school)
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
        })
        bar.addView(Ui.text(this, "Jarvis", 18f, bold = true).apply { gravity = Gravity.CENTER }, Ui.lp(0, weight = 1f))
        bar.addView(Ui.roundButton(this, R.drawable.ic_tune, size = 44) { show("settings") })
        list.addView(bar)

        // blue assistant card
        val hero = Ui.card(this, Ui.BLUE, 32).apply { gravity = Gravity.CENTER_HORIZONTAL; setPadding(dp(18), dp(10), dp(18), dp(20)) }
        hero.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_orb)
            layoutParams = LinearLayout.LayoutParams(dp(130), dp(130))
        })
        hero.addView(Ui.text(this, "Hoi Storm! Waarmee kan ik helpen?", 14f, Ui.BLACK).apply {
            background = Ui.shape(this@MainActivity, Ui.WHITE, 18)
            setPadding(dp(16), dp(9), dp(16), dp(9))
        })
        val actions = Ui.row(this).apply { gravity = Gravity.CENTER; setPadding(0, dp(16), 0, 0) }
        actions.addView(Ui.roundButton(this, R.drawable.ic_doc, size = 52) { show("scan") })
        actions.addView(View(this), LinearLayout.LayoutParams(dp(18), 1))
        lateinit var ask: (String) -> Unit
        actions.addView(Ui.roundButton(this, R.drawable.ic_spark, dark = true, size = 72) { ask("Wat moet ik deze week doen?") })
        actions.addView(View(this), LinearLayout.LayoutParams(dp(18), 1))
        actions.addView(Ui.roundButton(this, R.drawable.ic_folder, size = 52) { show("weeks") })
        hero.addView(actions)
        list.addView(hero)

        val sv = ScrollView(this).apply { addView(list) }
        box.addView(sv, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        // input card
        val inputCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Ui.shape(this@MainActivity, Ui.WHITE, 26, Ui.LINE)
            setPadding(dp(14), dp(8), dp(10), dp(10))
        }
        val inRow = Ui.row(this)
        val field = Ui.field(this, "Vraag me iets…", "", single = false).apply {
            background = null
            setPadding(dp(4), dp(8), dp(8), dp(8))
            imeOptions = EditorInfo.IME_ACTION_SEND
        }
        inRow.addView(field, Ui.lp(0, weight = 1f))
        inRow.addView(Ui.roundButton(this, R.drawable.ic_send, dark = true, size = 46) { ask(field.text.toString()) })
        inputCard.addView(inRow)
        val chips = Ui.row(this)
        for ((i, label) in listOf("Weekoverzicht", "Wat moet ik doen?", "Toetsen", "Ik ben iets vergeten").withIndex()) {
            chips.addView(Ui.chip(this, label, i == 0) {
                if (label == "Ik ben iets vergeten") { field.setText("Ik ben vergeten: "); field.setSelection(field.text.length); field.requestFocus() }
                else ask(mapOf("Weekoverzicht" to "Geef me een overzicht van deze week",
                    "Wat moet ik doen?" to "Wat moet ik doen?", "Toetsen" to "Welke toetsen heb ik de komende dagen?")[label]!!)
            })
        }
        inputCard.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(chips) })
        box.addView(FrameLayout(this).apply {
            setPadding(dp(12), dp(6), dp(12), dp(8))
            addView(inputCard)
        })
        content.addView(box)

        chatList = list
        chatScroll = sv
        lastId = ""
        ask = { raw ->
            val t = raw.trim()
            if (t.isNotEmpty() && !sending) {
                sending = true
                field.setText("")
                addBubble(JSONObject().put("role", "storm").put("text", t).put("id", ""))
                val typing = addBubble(JSONObject().put("role", "jarvis").put("text", "Jarvis denkt na…").put("id", ""))
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
        field.setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_SEND) { ask(field.text.toString()); true } else false }

        if (!Api.hasKey(this)) {
            addBubble(JSONObject().put("role", "jarvis").put("text", "Vul eerst het Jarvis-adres en de key in bij Instellen.").put("id", ""))
            return
        }
        fetchNew()
    }

    private var firstBubble = 2   // views above the messages: top bar + blue card

    private fun fetchNew() {
        val list = chatList ?: return
        if (sending) return
        val after = lastId
        bg {
            val msgs: JSONArray = Api.history(this, after)
            h.post {
                if (chatList !== list) return@post
                if (after.isEmpty()) { while (list.childCount > firstBubble) list.removeViewAt(firstBubble) }
                for (i in 0 until msgs.length()) {
                    val m = msgs.getJSONObject(i)
                    addBubble(m)
                    lastId = m.optString("id", lastId)
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
            layoutParams = Ui.lp(top = dp(10))
        }
        val bubble = TextView(this).apply {
            text = m.optString("text"); textSize = 15.5f
            setLineSpacing(0f, 1.15f)
            setTextColor(if (mine) Ui.WHITE else Ui.BLACK)
            setTextIsSelectable(true)
            background = Ui.shape(this@MainActivity, if (mine) Ui.BLACK else Ui.WHITE, 22, if (mine) 0 else Ui.LINE)
            setPadding(dp(16), dp(11), dp(16), dp(11))
            maxWidth = (resources.displayMetrics.widthPixels * 0.8).toInt()
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
        header(col, "Al je weken, netjes in Drive")
        val status = Ui.text(this, "Laden…", 14f, Ui.MUTED).apply { setPadding(0, dp(10), 0, 0) }
        col.addView(status)
        content.addView(scroll(col))
        if (!Api.hasKey(this)) { status.text = "Vul eerst je Jarvis key in bij Instellen."; return }
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
        weekLabel = s.optString("label")
        status.text = "Nu: $weekLabel" + if (!s.optBoolean("drive")) " · Drive nog niet gekoppeld (PDF's staan op de Pi)" else ""

        val up = s.optJSONArray("upcoming") ?: JSONArray()
        val hero = Ui.card(this, Ui.BLUE, 32)
        val hr = Ui.row(this)
        hr.addView(Ui.text(this, "Binnenkort", 22f, Ui.BLACK, bold = true), Ui.lp(0, weight = 1f))
        hr.addView(TextView(this).apply {
            text = "${up.length()}"; textSize = 15f; typeface = Ui.MEDIUM; setTextColor(Ui.BLACK); gravity = Gravity.CENTER
            background = Ui.circle(0, this@MainActivity, Ui.BLACK)
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
        })
        hero.addView(hr)
        if (up.length() == 0) hero.addView(Ui.text(this, "Nog geen toetsen of taken. Scan je planner!", 14f, 0xFF3A3F55.toInt()).apply { setPadding(0, dp(6), 0, 0) })
        for (i in 0 until minOf(up.length(), 8)) {
            val it = up.getJSONObject(i)
            val test = it.optString("kind") == "test"
            val d = it.optString("date").takeIf { x -> x.isNotEmpty() && x != "null" }?.let { x -> nice(x) } ?: ""
            val r = Ui.row(this).apply {
                background = Ui.shape(this@MainActivity, if (test) Ui.BLACK else Ui.WHITE, 22)
                setPadding(dp(8), dp(8), dp(14), dp(8))
                layoutParams = Ui.lp(top = dp(8))
            }
            r.addView(FrameLayout(this).apply {
                background = Ui.circle(if (test) Ui.WHITE else Ui.BLACK, this@MainActivity)
                addView(Ui.icon(this@MainActivity, if (test) R.drawable.ic_cap else R.drawable.ic_doc, if (test) Ui.BLACK else Ui.WHITE, 16).apply {
                    layoutParams = FrameLayout.LayoutParams(dp(16), dp(16), Gravity.CENTER)
                })
            }, LinearLayout.LayoutParams(dp(32), dp(32)).apply { rightMargin = dp(10) })
            r.addView(Ui.text(this, "${it.optString("subject")}: ${it.optString("what")}", 14f, if (test) Ui.WHITE else Ui.BLACK), Ui.lp(0, weight = 1f))
            if (d.isNotEmpty()) r.addView(Ui.text(this, d, 12f, if (test) 0xFFB9C6FF.toInt() else Ui.MUTED, bold = true).apply { setPadding(dp(8), 0, 0, 0) })
            hero.addView(r)
        }
        col.addView(hero)

        title(col, "Mappen per week")
        val colors = listOf(Ui.PINK, Ui.ORANGE, Ui.BLUE_TINT)
        val weeks = s.optJSONArray("weeks") ?: JSONArray()
        for (i in 0 until weeks.length()) {
            val w = weeks.getJSONObject(i)
            val n = w.optInt("week")
            val c = Ui.card(this, colors[i % colors.size], 28)
            val docs = w.optJSONArray("docs") ?: JSONArray()
            val top = Ui.row(this)
            top.addView(FrameLayout(this).apply {
                background = Ui.circle(Ui.BLACK, this@MainActivity)
                addView(Ui.icon(this@MainActivity, R.drawable.ic_folder, Ui.WHITE, 22).apply {
                    layoutParams = FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER)
                })
            }, LinearLayout.LayoutParams(dp(48), dp(48)))
            top.addView(Ui.spacer(this))
            top.addView(TextView(this).apply {
                text = "${docs.length()}"; textSize = 15f; typeface = Ui.MEDIUM; setTextColor(Ui.BLACK); gravity = Gravity.CENTER
                background = Ui.circle(0, this@MainActivity, Ui.BLACK)
                layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
            })
            c.addView(top)
            c.addView(Ui.text(this, w.optString("folder"), 19f, Ui.BLACK, bold = true).apply { setPadding(0, dp(12), 0, 0) })
            if (docs.length() == 0) c.addView(Ui.text(this, "Nog niets gescand", 14f, 0xFF4A4F60.toInt()))
            var folderUrl = ""
            for (j in 0 until docs.length()) {
                val d = docs.getJSONObject(j)
                val url = d.optString("url").takeIf { it.startsWith("http") } ?: Api.fileUrl(this, n, d.optString("name"))
                if (folderUrl.isEmpty()) folderUrl = d.optString("folder_url").takeIf { it.startsWith("http") } ?: ""
                val pagesTxt = d.optInt("pages").let { p -> if (p > 0) "  ·  $p p." else "" }
                c.addView(Ui.link(this, d.optString("name").removeSuffix(".pdf") + pagesTxt, onWhite = false) { open(url) })
            }
            val tests = w.optJSONArray("tests") ?: JSONArray()
            for (j in 0 until tests.length()) {
                val t = tests.getJSONObject(j)
                c.addView(Ui.text(this, "Toets ${t.optString("subject")}: ${t.optString("what")}", 13f, 0xFF3A3F55.toInt()).apply { setPadding(0, dp(6), 0, 0) })
            }
            if (folderUrl.isNotEmpty()) c.addView(Ui.pill(this, "OPEN MAP IN DRIVE") { open(folderUrl) })
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
        header(col, "Verbind de app met Jarvis")
        val c = Ui.card(this)
        c.addView(Ui.text(this, "Jarvis-adres (thuis-wifi)", 13f, Ui.MUTED))
        val url = Ui.field(this, "http://192.168.0.249:8790", Api.url(this)).apply { layoutParams = Ui.lp(top = dp(6)) }
        c.addView(url)
        c.addView(Ui.text(this, "Jarvis key (JARVIS_KEY, zoals bij TimeGuard)", 13f, Ui.MUTED).apply { setPadding(0, dp(14), 0, 0) })
        val key = Ui.field(this, "JARVIS_KEY", Api.key(this)).apply { layoutParams = Ui.lp(top = dp(6)) }
        c.addView(key)
        val status = Ui.text(this, "", 14f, Ui.BLUE_DARK).apply { setPadding(0, dp(10), 0, 0) }
        c.addView(Ui.pill(this, "OPSLAAN EN TESTEN", full = true) {
            Api.save(this, url.text.toString(), key.text.toString())
            status.text = "Verbinden…"
            Thread {
                val msg = try {
                    val s = Api.state(this)
                    h.post { week = s.optInt("week", week); weekLabel = s.optString("label") }
                    "Verbonden ✓ · " + s.optString("label")
                } catch (e: Exception) { "Niet gelukt: ${e.message}" }
                h.post { status.text = msg }
            }.start()
        })
        c.addView(status)
        col.addView(c)
        col.addView(Ui.text(this, "Werkt op je thuis-wifi. Buiten huis? Zet Tailscale aan en gebruik het Tailscale-adres van je Pi.", 13f, Ui.MUTED)
            .apply { setPadding(dp(4), dp(14), dp(4), 0) })
        content.addView(scroll(col))
    }

    companion object { const val SCAN = 7 }
}
